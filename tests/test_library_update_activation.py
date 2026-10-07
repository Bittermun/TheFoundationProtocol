import importlib
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import sys
import os
import stat
import psutil

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from library_update_support import tools, create_zim, run


@pytest.fixture
def live_library(tmp_path):
    programs = tools()
    base, target = tmp_path / 'base.zim', tmp_path / 'target.zim'
    old_page = create_zim(base, 0)
    new_page = create_zim(target, 1)
    catalog = tmp_path / 'library.xml'
    run([programs['kiwix-manage'], catalog, 'add', base])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([str(programs['kiwix-serve']), '--library', '--monitorLibrary', '--address=127.0.0.1', f'--port={port}', str(catalog)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}'
    try:
        deadline = time.monotonic() + 8
        while True:
            try:
                with urllib.request.urlopen(url + '/raw/base/content/index.html', timeout=.5) as response:
                    assert response.read() == old_page
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
        key = Ed25519PrivateKey.generate()
        private, public = tmp_path / 'publisher.key', tmp_path / 'publisher.pub'
        private.write_bytes(key.private_bytes_raw())
        public.write_bytes(key.public_key().public_bytes_raw())
        from tfp_core_v4.library_updates.prepare import prepare_update
        package = prepare_update(base, target, tmp_path / 'package', 'school', 1, private)
        yield dict(root=tmp_path, programs=programs, base=base, target=target, catalog=catalog, url=url, public=public, package=package, old_page=old_page, new_page=new_page, private=private)
    finally:
        process.terminate()
        process.wait(timeout=10)


def config(library, **overrides):
    adapter = importlib.import_module('tfp_core_v4.library_updates.activation')
    values = dict(library_id='school', archive_dir=library['root'] / 'archives', library_xml=library['catalog'], state_dir=library['root'] / 'state', base_archive=library['base'], trusted_public_key=library['public'], kiwix_manage=library['programs']['kiwix-manage'], zimcheck=library['programs']['zimcheck'], serve_base_url=library['url'], probe_article_path='index.html', command_timeout_seconds=15)
    return adapter, adapter.KiwixConfig(**dict(values, **overrides))


@pytest.mark.parametrize('delta_backend', ['cdc', 'zstd'])
def test_real_kiwix_activation_across_backends(live_library, delta_backend):
    from tfp_core_v4.library_updates.prepare import prepare_update
    adapter, cfg = config(live_library)
    pkg = prepare_update(
        live_library['base'],
        live_library['target'],
        live_library['root'] / f'package_{delta_backend}',
        'school',
        1,
        live_library['private'],
        delta_backend=delta_backend,
    )
    result = adapter.activate_package(pkg, cfg)
    assert result.status == 'committed'
    with urllib.request.urlopen(live_library['url'] + f'/raw/{result.target_path.stem}/content/index.html', timeout=3) as response:
        assert response.read() == live_library['new_page']
    assert adapter.activate_package(pkg, cfg).status == 'duplicate'
    assert live_library['base'].exists()


def test_real_kiwix_activation_and_duplicate_idempotence(live_library):
    adapter, cfg = config(live_library)
    result = adapter.activate_package(live_library['package'], cfg)
    assert result.status == 'committed'
    with urllib.request.urlopen(live_library['url'] + f'/raw/{result.target_path.stem}/content/index.html', timeout=3) as response:
        assert response.read() == live_library['new_page']
    assert adapter.activate_package(live_library['package'], cfg).status == 'duplicate'
    assert live_library['base'].exists()


def test_reader_failure_restores_old_catalog(live_library):
    adapter, cfg = config(live_library, probe_article_path='missing-page.html', command_timeout_seconds=.6)
    original = live_library['catalog'].read_bytes()
    with pytest.raises((OSError, ValueError, TimeoutError)):
        adapter.activate_package(live_library['package'], cfg)
    assert live_library['catalog'].read_bytes() == original
    assert not (cfg.state_dir / 'accepted.json').exists()


def test_corrupt_artifact_never_changes_catalog(live_library):
    adapter, cfg = config(live_library)
    raw = json.loads((live_library['package'] / 'update.json').read_bytes())
    artifact = live_library['package'] / ('artifact.tfp' if raw['artifact_kind'] == 'delta' else 'artifact.zim')
    artifact.write_bytes(b'corrupt')
    original = live_library['catalog'].read_bytes()
    with pytest.raises(ValueError):
        adapter.activate_package(live_library['package'], cfg)
    assert live_library['catalog'].read_bytes() == original


def test_corrupt_zstd_artifact_never_changes_catalog(live_library):
    from tfp_core_v4.library_updates.prepare import prepare_update
    adapter, cfg = config(live_library)
    pkg = prepare_update(
        live_library['base'],
        live_library['target'],
        live_library['root'] / 'package_zstd_corrupt',
        'school',
        1,
        live_library['private'],
        delta_backend='zstd',
    )
    artifact = pkg / 'artifact.zst'
    artifact.write_bytes(b'corrupt_zstd_bytes')
    original = live_library['catalog'].read_bytes()
    with pytest.raises(ValueError):
        adapter.activate_package(pkg, cfg)
    assert live_library['catalog'].read_bytes() == original


def test_lock_excludes_competing_updater(live_library):
    adapter, cfg = config(live_library)
    with adapter.update_lock(cfg):
        with pytest.raises(RuntimeError, match='another updater'):
            adapter.activate_package(live_library['package'], cfg)


def test_process_death_after_catalog_switch_recovers(live_library):
    adapter, cfg = config(live_library, probe_article_path='missing-page.html', command_timeout_seconds=20)
    raw = {name: str(value) if isinstance(value, Path) else value for name, value in vars(cfg).items()}
    configfile = live_library['root'] / 'config.json'
    configfile.write_text(json.dumps(raw))
    original = live_library['catalog'].read_bytes()
    child_env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(Path(entry or '.').resolve()) for entry in sys.path))
    process = subprocess.Popen([sys.executable, '-m', 'tfp_core_v4.library_updates.cli', 'library-activate', str(live_library['package']), '--config', str(configfile)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=child_env)
    try:
        deadline = time.monotonic() + 8
        while live_library['catalog'].read_bytes() == original:
            if process.poll() is not None:
                pytest.fail('Updater exited before catalog switch: ' + process.stdout.read().decode(errors='replace'))
            assert time.monotonic() < deadline
            time.sleep(.02)
        children = psutil.Process(process.pid).children(recursive=True)
        for child in children:
            child.kill()
        process.kill()
        process.wait(timeout=5)
        psutil.wait_procs(children, timeout=5)
        assert adapter.recover_activation(cfg).recovered
        assert live_library['catalog'].read_bytes() == original
        assert not (cfg.state_dir / 'accepted.json').exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_external_catalog_edit_is_not_overwritten_by_recovery(live_library):
    adapter, cfg = config(live_library)
    cfg.state_dir.mkdir()
    original = live_library['catalog'].read_bytes()
    (cfg.state_dir / 'catalog.backup').write_bytes(original)
    from tfp_core_v4.library_updates.manifest import file_digest
    journal = {'old_catalog_sha3': file_digest(cfg.state_dir / 'catalog.backup'), 'new_catalog_sha3': '0' * 64, 'previous_state': adapter.accepted_state(cfg), 'next_state': {}}
    (cfg.state_dir / 'activation.json').write_text(json.dumps(journal))
    live_library['catalog'].write_bytes(b'external edit')
    with pytest.raises(ValueError, match='externally'):
        adapter.recover_activation(cfg)
    assert live_library['catalog'].read_bytes() == b'external edit'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX reader permissions')
def test_catalog_access_mode_preserved_on_switch_and_rollback(live_library):
    adapter, cfg = config(live_library)
    live_library['catalog'].chmod(0o640)
    adapter.activate_package(live_library['package'], cfg)
    assert stat.S_IMODE(live_library['catalog'].stat().st_mode) == 0o640
    assert stat.S_IMODE(cfg.archive_dir.stat().st_mode) & 0o005 == 0o005
    accepted = adapter.accepted_state(cfg)
    assert stat.S_IMODE(Path(accepted['target_path']).stat().st_mode) & 0o004


def test_catalog_edit_after_real_reader_probe_cannot_advance_revision(live_library, monkeypatch):
    adapter, cfg = config(live_library)
    original = live_library['catalog'].read_bytes()
    real_probe = adapter.probe_reader
    def edit_after_probe(*args):
        real_probe(*args)
        live_library['catalog'].write_bytes(original)
    monkeypatch.setattr(adapter, 'probe_reader', edit_after_probe)
    with pytest.raises(ValueError, match='Catalog changed'):
        adapter.activate_package(live_library['package'], cfg)
    assert not (cfg.state_dir / 'accepted.json').exists()
    assert live_library['catalog'].read_bytes() == original


def test_utf16_xml_entity_expansion_rejected():
    tools()  # Also makes the optional parser dependency available locally.
    from tfp_core_v4.library_updates.kiwix import parse_xml
    from defusedxml.common import DefusedXmlException
    raw = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE library [<!ENTITY attack "expanded">]><library>&attack;</library>'.encode('utf-16')
    with pytest.raises((ValueError, DefusedXmlException)):
        parse_xml(raw)


def test_verification_script_tiny_delivery(live_library):
    import asyncio
    import secrets
    from tfp_core_v4.library_updates.prepare import prepare_update
    from scripts.verify_library_update import demonstrate
    import argparse

    wheel_python = Path('.superpowers/wheel-env/Scripts/python.exe').resolve()
    wheels = list(Path('.superpowers/wheels').glob('*.whl'))
    if not wheel_python.exists() or not wheels:
        pytest.skip('Installed wheel environment required for process boundary proof')

    adapter, cfg = config(live_library)
    transport_key = live_library['root'] / 'transport_tiny.key'
    transport_key.write_bytes(secrets.token_bytes(32))

    cfg_dict = {name: str(value) if isinstance(value, Path) else value for name, value in vars(cfg).items()}
    config_file = live_library['root'] / 'config_tiny.json'
    config_file.write_text(json.dumps(cfg_dict), encoding='utf-8')

    pkg = prepare_update(
        live_library['base'],
        live_library['target'],
        live_library['root'] / 'pkg_tiny_zstd',
        'school',
        1,
        live_library['private'],
        delta_backend='zstd',
    )

    out_dir = live_library['root'] / 'verify_tiny_out'
    args = argparse.Namespace(
        package=pkg,
        public_key=live_library['public'],
        transport_key=transport_key,
        config=config_file,
        python=wheel_python,
        output=out_dir,
        scenario='delivery',
        wheel=wheels[0],
        loss=0.3,
        seed=20261005,
    )

    ret = asyncio.run(demonstrate(args))
    assert ret == 0

    report = json.loads((out_dir / 'report.json').read_text(encoding='utf-8'))
    assert report['status'] == 'passed'
    assert report['scenario'] == 'delivery'
    assert report['restart_count'] == 0
    assert report['stages']['delivery'] == 'passed'
    assert report['stages']['reader_activation'] == 'passed'
    assert report['operator_process_tree_peak_rss_bytes'] <= 256 * 1024 * 1024


@pytest.mark.timeout(120)
def test_verification_script_multi_chunk_restart(tmp_path):
    import asyncio
    import secrets
    from tfp_core_v4.library_updates.prepare import prepare_update
    from scripts.verify_library_update import demonstrate
    import argparse

    wheel_python = Path('.superpowers/wheel-env/Scripts/python.exe').resolve()
    wheels = list(Path('.superpowers/wheels').glob('*.whl'))
    if not wheel_python.exists() or not wheels:
        pytest.skip('Installed wheel environment required for process boundary proof')

    programs = tools()
    base_mc = tmp_path / 'base_mc.zim'
    target_mc = tmp_path / 'target_mc.zim'
    old_page = create_zim(base_mc, revision=10, changed_asset_bytes=150 * 1024)
    new_page = create_zim(target_mc, revision=11, changed_asset_bytes=150 * 1024)

    catalog = tmp_path / 'catalog_mc.xml'
    run([programs['kiwix-manage'], catalog, 'add', base_mc])

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen(
        [str(programs['kiwix-serve']), '--library', '--monitorLibrary', '--address=127.0.0.1', f'--port={port}', str(catalog)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f'http://127.0.0.1:{port}'

    try:
        deadline = time.monotonic() + 8
        while True:
            try:
                with urllib.request.urlopen(url + '/raw/base_mc/content/index.html', timeout=0.5) as response:
                    assert response.read() == old_page
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)

        key = Ed25519PrivateKey.generate()
        private = tmp_path / 'publisher_mc.key'
        public = tmp_path / 'publisher_mc.pub'
        private.write_bytes(key.private_bytes_raw())
        public.write_bytes(key.public_key().public_bytes_raw())

        pkg_mc = prepare_update(
            base_mc,
            target_mc,
            tmp_path / 'package_mc',
            'school_mc',
            11,
            private,
            delta_backend='zstd',
        )
        assert (pkg_mc / 'artifact.zst').stat().st_size > 64 * 1024

        from tfp_core_v4.library_updates.activation import KiwixConfig
        cfg = KiwixConfig(
            library_id='school_mc',
            archive_dir=tmp_path / 'archives_mc',
            library_xml=catalog,
            state_dir=tmp_path / 'state_mc',
            base_archive=base_mc,
            trusted_public_key=public,
            kiwix_manage=programs['kiwix-manage'],
            zimcheck=programs['zimcheck'],
            serve_base_url=url,
            probe_article_path='index.html',
            command_timeout_seconds=5,
        )

        transport_key = tmp_path / 'transport_mc.key'
        transport_key.write_bytes(secrets.token_bytes(32))

        cfg_dict = {name: str(value) if isinstance(value, Path) else value for name, value in vars(cfg).items()}
        config_file = tmp_path / 'config_mc.json'
        config_file.write_text(json.dumps(cfg_dict), encoding='utf-8')

        out_dir = tmp_path / 'verify_mc_out'
        args = argparse.Namespace(
            package=pkg_mc,
            public_key=public,
            transport_key=transport_key,
            config=config_file,
            python=wheel_python,
            output=out_dir,
            scenario='restart',
            wheel=wheels[0],
            loss=0.3,
            seed=20261005,
        )

        ret = asyncio.run(demonstrate(args))
        assert ret == 0

        report = json.loads((out_dir / 'report.json').read_text(encoding='utf-8'))
        assert report['status'] == 'passed'
        assert report['scenario'] == 'restart'
        assert report['restart_count'] == 1
        assert report['checkpoint_chunks_before_restart'] >= 1
        assert report['stages']['restart_delivery'] == 'passed'
        assert report['stages']['reader_activation'] == 'passed'
        assert report['operator_process_tree_peak_rss_bytes'] <= 256 * 1024 * 1024

        with urllib.request.urlopen(url + f'/raw/{report["fixture_target_sha3"]}/content/index.html', timeout=3) as resp:
            assert resp.read() == new_page

    finally:
        proc.terminate()
        proc.wait(timeout=10)

