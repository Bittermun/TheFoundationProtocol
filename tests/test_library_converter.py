import asyncio
import hashlib
import json
import shutil
import socket
from urllib.request import urlopen

import pytest

from tfp_client.lib.media.fountain_streamer import MediaDropletPacket
from tfp_core_v4.cli import main
from tfp_core_v4.library_updates.manifest import key_id, verify_descriptor
from tfp_core_v4.library_updates.receive import TRANSPORT_CHUNK, artifact_packets, receive_artifact
from test_library_update_activation import config, live_library as live_library
from test_library_update_delivery import free_port


@pytest.fixture
def author_files(tmp_path):
    documents = tmp_path / 'documents'
    documents.mkdir()
    (documents / 'map.txt').write_bytes(b'Map & route\nTake the <north> trail.')
    (documents / 'weather.txt').write_bytes(b'Weather\nExpect rain after noon.')
    recipe = tmp_path / 'recipe.json'
    recipe.write_text(json.dumps({
        'schema_version': 1,
        'title': 'Trail notes',
        'description': 'Volunteer field notes',
        'language': 'eng',
        'creator': 'Volunteers',
        'publisher': 'Volunteers',
        'date': '2026-11-18',
        'documents': ['map.txt', 'weather.txt'],
    }), encoding='utf-8')
    converter = tmp_path / 'author_converter.py'
    converter.write_text(
        'TFP_CONVERTER_API = 1\n'
        'def convert(document, *, filename):\n'
        '    title, body = document.decode("utf-8").split("\\n", 1)\n'
        '    return title, body + "\\nSource: " + filename\n',
        encoding='utf-8',
    )
    return recipe, documents, converter, tmp_path / 'converted.zim'


def build_command(files):
    recipe, documents, converter, output = files
    return [
        'library-build', str(recipe), '--input-dir', str(documents),
        '--converter-file', str(converter), '--out', str(output),
    ]


@pytest.mark.parametrize('selection', ['file', 'module'])
def test_build_reads_documents_in_recipe_order_and_escapes_output(author_files, capsys, monkeypatch, selection):
    from library_update_support import tools
    tools()
    from libzim.reader import Archive
    from libzim.search import Query, Searcher

    command = build_command(author_files)
    if selection == 'module':
        converter = author_files[2]
        monkeypatch.syspath_prepend(str(converter.parent))
        index = command.index('--converter-file')
        command[index:index + 2] = ['--converter-module', converter.stem]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)['documents'] == 2
    archive = Archive(author_files[3])
    index = bytes(archive.get_entry_by_path('index.html').get_item().content).decode()
    assert index.index('Map &amp; route') < index.index('Weather')
    page = bytes(archive.get_entry_by_path('document-001.html').get_item().content).decode()
    assert 'Take the &lt;north&gt; trail.\nSource: map.txt' in page
    assert '<north>' not in page
    assert 'Expect rain after noon.' in bytes(
        archive.get_entry_by_path('document-002.html').get_item().content
    ).decode()
    search = Searcher(archive).search(Query().set_query('rain after noon'))
    assert list(search.getResults(0, 10)) == ['document-002.html']


@pytest.mark.parametrize(('changes', 'message'), [
    ({'converter_module': 'author_converter'}, 'Unsupported library recipe fields'),
    ({'documents': ['map.txt', 'MAP.TXT']}, 'Duplicate document'),
    ({'documents': ['../map.txt']}, 'Invalid document basename'),
    ({'documents': ['CON.txt']}, 'Invalid document basename'),
    ({'documents': ['missing.txt']}, 'missing.txt'),
])
def test_invalid_recipe_refused_before_converter_load(author_files, changes, message, capsys):
    recipe, _, converter, output = author_files
    payload = json.loads(recipe.read_text(encoding='utf-8'))
    recipe.write_text(json.dumps(payload | changes), encoding='utf-8')
    converter.write_text('raise RuntimeError("Converter was loaded")\n', encoding='utf-8')
    assert main(build_command(author_files)) == 1
    error = capsys.readouterr().err
    assert message in error
    assert 'Converter was loaded' not in error
    assert not output.exists()


@pytest.mark.asyncio
async def test_converted_library_resumes_missing_chunks_and_opens_offline(
    author_files, live_library, tmp_path, capsys,
):
    _, documents, _, target = author_files
    # Preserve meaningful text alongside enough unique bytes for a multi-chunk archive.
    with (documents / 'map.txt').open('ab') as stream:
        stream.write(b'\n' + hashlib.shake_256(b'trail appendix').digest(140000).hex().encode())
    assert main(build_command(author_files)) == 0
    publisher_package = tmp_path / 'publisher-package'
    assert main([
        'library-prepare', str(live_library['base']), str(target),
        '--library-id', 'school', '--revision', '1', '--signing-key', str(live_library['private']),
        '--out', str(publisher_package),
    ]) == 0

    recipient = tmp_path / 'recipient'
    recipient.mkdir()
    for name in ('update.json', 'update.sig'):
        shutil.copyfile(publisher_package / name, recipient / name)
    public = live_library['public'].read_bytes()
    update = verify_descriptor(recipient, {key_id(public): public}, 'school', 0)
    artifact = publisher_package / update.artifact_name
    destination = recipient / update.artifact_name
    adapter, cfg = config(live_library)
    original_catalog = cfg.library_xml.read_bytes()
    with pytest.raises(ValueError, match=f'Missing required artifact {update.artifact_name}.*{update.artifact_sha3}'):
        adapter.activate_package(recipient, cfg)
    assert cfg.library_xml.read_bytes() == original_catalog

    key = b'r' * 32
    raw = artifact.read_bytes()
    assert len(raw) > TRANSPORT_CHUNK
    packets = list(artifact_packets(artifact, key, redundancy=0))

    async def transfer(send_first, timeout):
        port = free_port()
        checkpoints = recipient / 'checkpoints'
        task = asyncio.create_task(receive_artifact(
            update.artifact_size, update.artifact_sha3, destination,
            checkpoints, '127.0.0.1', port, timeout, key,
        ))
        try:
            await asyncio.sleep(.05)
            loop = asyncio.get_running_loop()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setblocking(False)
                for packet in packets:
                    if not packet.startswith(b'FM'):
                        index = MediaDropletPacket.from_bytes(packet, secret_key=key).chunk_index
                        if (index == 0) != send_first:
                            continue
                    await loop.sock_sendto(sock, packet, ('127.0.0.1', port))
                    # Like the CLI sender, let the receiver drain between packets.
                    await asyncio.sleep(.002)
            return await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    with pytest.raises(TimeoutError) as interrupted:
        await transfer(send_first=True, timeout=1.5)
    error = str(interrupted.value)
    assert update.artifact_sha3 in error
    for index, offset in enumerate(range(TRANSPORT_CHUNK, len(raw), TRANSPORT_CHUNK), start=1):
        digest = hashlib.sha3_256(raw[offset:offset + TRANSPORT_CHUNK]).hexdigest()
        assert f'{index}:{digest}' in error
    assert f'0:{hashlib.sha3_256(raw[:TRANSPORT_CHUNK]).hexdigest()}' not in error
    assert not destination.exists()
    assert not (cfg.state_dir / 'accepted.json').exists()
    assert await transfer(send_first=False, timeout=5) == destination
    assert destination.read_bytes() == raw

    result = adapter.activate_package(recipient, cfg)
    assert result.status == 'committed'
    assert result.target_path.read_bytes() == target.read_bytes()
    url = f'{cfg.serve_base_url}/raw/{result.target_path.stem}/content'
    with urlopen(f'{url}/index.html', timeout=3) as response:
        assert b'<a href="document-002.html">Weather</a>' in response.read()
    with urlopen(f'{url}/document-002.html', timeout=3) as response:
        assert b'Expect rain after noon.' in response.read()
