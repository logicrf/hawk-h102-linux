"""Check original service archives and refuse unsafe staging without device access."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tarfile

import pytest

SPEC = importlib.util.spec_from_file_location(
    'h102_board_services', Path(__file__).resolve().parents[1] / 'scripts/h102_board_services.py')
TOOLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOLS)


@pytest.fixture
def bundle(tmp_path):
    """Copy explicitly supplied published firmware inputs; absence is not a hardware PASS."""
    source = os.environ.get('H102_BOARD_SERVICE_BUNDLE')
    if not source:
        pytest.skip('Original device-service archives supplied separately')
    target = tmp_path / 'bundle'
    target.mkdir()
    for name in ('BOARD-SERVICES.json', *(entry['filename'] for entry in TOOLS.PINS.values())):
        shutil.copyfile(Path(source) / name, target / name)
    return target


def test_original_archives_verify_and_stage_all_files(bundle, tmp_path):
    """Read every actual output back and preserve inputs; the receipt never claims installation."""
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    manifest, payloads = TOOLS.verify_bundle(bundle)
    assert manifest['requirements']['installed_api'] == '0.1.0-ip36'
    assert {name: len(files) for name, files in payloads.items()} == {'hotmeta': 39, 'network': 7}
    output = tmp_path / 'new staging directory'
    receipt = TOOLS.stage(bundle, output)
    assert receipt['status'] == 'PASS_STAGED_NOT_INSTALLED' and receipt['hardware'] == 'NOT_RUN'
    assert len(receipt['files']) == 46
    for name, expected in receipt['files'].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
    assert {p.name: p.read_bytes() for p in bundle.iterdir()} == before
    assert 'install_hotmeta_addon.py' in receipt['administrator_commands']['first_on_idle_device']
    assert '--prepare-grc-profile' not in receipt['administrator_commands']['after_reboot']
    with pytest.raises(FileExistsError):
        TOOLS.stage(bundle, output)
    assert json.loads((output / 'STAGED.json').read_text()) == receipt


@pytest.mark.parametrize('component', ['hotmeta', 'network'])
def test_corrupted_archive_rejected_before_creating_output(bundle, tmp_path, component):
    """A single-byte payload error cannot create a misleading successful staging tree."""
    path = bundle / TOOLS.PINS[component]['filename']
    raw = bytearray(path.read_bytes()); raw[len(raw) // 2] ^= 1; path.write_bytes(raw)
    output = tmp_path / 'should-not-exist'
    with pytest.raises(ValueError, match='ARCHIVE_SHA_MISMATCH'):
        TOOLS.stage(bundle, output)
    assert not output.exists()


def test_sidecar_cannot_authorize_new_payload(bundle):
    path = bundle / 'BOARD-SERVICES.json'
    manifest = json.loads(path.read_text())
    manifest['components']['hotmeta']['sha256'] = '0' * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='UNAPPROVED_SERVICE_DELIVERY'):
        TOOLS.verify_bundle(bundle)


def test_archive_symlink_is_rejected(bundle):
    path = bundle / TOOLS.PINS['network']['filename']
    source = path.with_suffix('.original')
    path.rename(source); path.symlink_to(source.name)
    with pytest.raises(OSError):
        TOOLS.verify_bundle(bundle)


def archive_bytes(members):
    """Construct tiny hostile archive models without any filesystem extraction."""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name, kind in members:
            member = tarfile.TarInfo(name); member.type = kind
            if kind == tarfile.REGTYPE:
                member.size = 1; archive.addfile(member, io.BytesIO(b'x'))
            else:
                member.linkname = '/outside'; archive.addfile(member)
    return data.getvalue()


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'root/a/../escape', 'other/file', 'root//file'])
def test_path_aliases_and_escape_are_rejected(name):
    with pytest.raises(ValueError, match='UNSAFE_ARCHIVE_MEMBER'):
        TOOLS.archive_files(archive_bytes([(name, tarfile.REGTYPE)]), 'root')


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_links_and_special_members_are_rejected(kind):
    with pytest.raises(ValueError, match='UNSAFE_ARCHIVE_MEMBER'):
        TOOLS.archive_files(archive_bytes([('root/file', kind)]), 'root')


def test_duplicate_members_and_file_parents_are_rejected():
    with pytest.raises(ValueError, match='UNSAFE_ARCHIVE_MEMBER'):
        TOOLS.archive_files(archive_bytes([('root/file', tarfile.REGTYPE)] * 2), 'root')
    with pytest.raises(ValueError, match='ARCHIVE_FILE_PARENT'):
        TOOLS.archive_files(archive_bytes([('root/file', tarfile.REGTYPE),
                                          ('root/file/child', tarfile.REGTYPE)]), 'root')


def test_source_size_bound_and_output_parent_symlink(tmp_path):
    path = tmp_path / 'data'; path.write_bytes(b'12345')
    with pytest.raises(ValueError, match='BOUNDED_REGULAR_FILE_REQUIRED'):
        TOOLS.read_regular(path, limit=4)
    link = tmp_path / 'link'; link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='PLAIN_PATH_REQUIRED'):
        TOOLS.plain_path(link / 'output')
