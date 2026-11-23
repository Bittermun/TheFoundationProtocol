import json

from tfp_core_v4.cli import main


def import_args(source, output):
    return [
        'library-import', str(source), '--out', str(output), '--title', 'School library',
        '--publisher', 'Test school', '--date', '2026-11-20',
    ]


def test_installed_source_adapter_builds_searchable_zim(tmp_path, monkeypatch, capsys):
    from library_update_support import tools
    tools()
    from libzim.reader import Archive
    from libzim.search import Query, Searcher

    (tmp_path / 'outside_adapter.py').write_text(
        "TFP_SOURCE_API = 1\n"
        "def read_pages(source, *, filename):\n"
        "    return [(filename, source.decode('utf-8'))]\n",
        encoding='utf-8',
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    source = tmp_path / 'glossary.data'
    source.write_text('The reading room keeps an observation notebook.', encoding='utf-8')
    output = tmp_path / 'glossary.zim'
    assert main(import_args(source, output) + ['--source-module', 'outside_adapter']) == 0
    assert json.loads(capsys.readouterr().out)['documents'] == 1
    search = Searcher(Archive(output)).search(Query().set_query('observation notebook'))
    assert list(search.getResults(0, 10)) == ['document-001.html']


def test_incomplete_runbook_does_not_publish_an_archive(tmp_path, capsys):
    source = tmp_path / 'runbook.json'
    source.write_text('{"playbooks":[{"title":"Reconnect","trigger":"Outage","steps":[]}]}', encoding='utf-8')
    output = tmp_path / 'library.zim'
    assert main(import_args(source, output) + ['--kit', 'runbook']) == 1
    assert 'trigger and at least one step' in capsys.readouterr().err
    assert not output.exists()
