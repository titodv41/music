"""Build an offline Intel Mac package from verified upstream release archives."""
import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {
    'slskd-0.24.5-osx-x64.zip': '8bdb6bbb04c8144510cbd58fcd62c3c81779e6aaa13c29b3c4f4788807c2dd70',
    'mutagen-1.47.0-py3-none-any.whl': 'edd96f50c5907a9539d8e5bba7245f62c9f520aef333d13392a79a4f70aca719',
    'mutagen-1.47.0.tar.gz': '719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99',
}


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stage = args.output / 'DJ-Library'
    if stage.exists():
        shutil.rmtree(stage)
    (stage / 'vendor').mkdir(parents=True)
    for name, expected in EXPECTED.items():
        source = args.assets / name
        if digest(source) != expected:
            raise ValueError('Official artifact checksum mismatch: ' + name)
        shutil.copy2(source, stage / 'vendor' / name)
    source_archive = args.assets / 'slskd-0.24.5-source.zip'
    shutil.copy2(source_archive, stage / 'vendor' / source_archive.name)
    with zipfile.ZipFile(source_archive) as archive:
        license_text = archive.read('slskd-0.24.5/LICENSE')
    (stage / 'vendor/SLSKD-LICENSE.txt').write_bytes(license_text)
    for name in ['djlib', 'tests', 'scripts']:
        shutil.copytree(ROOT / name, stage / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['Install.command', 'mac_bootstrap.py', 'START-HERE.txt', 'README.md', 'pyproject.toml']:
        shutil.copy2(ROOT / name, stage / name)
    (stage / 'Install.command').chmod(0o755)
    (stage / 'LICENSE').write_bytes(license_text)
    notices = '''THIRD-PARTY COMPONENTS

slskd 0.24.5, unmodified official self-contained Intel Mac release.
License: AGPL-3.0; bundled license: vendor/SLSKD-LICENSE.txt.
Exact upstream source: vendor/slskd-0.24.5-source.zip.
Official source: https://github.com/slskd/slskd/tree/0.24.5
Official binary: https://github.com/slskd/slskd/releases/tag/0.24.5
SHA-256 was verified against the official GitHub release asset metadata.
The embedded .NET runtime and web dependencies retain their upstream notices.

mutagen 1.47.0, unmodified pure Python wheel.
License: GPL-2.0-or-later. See its wheel .dist-info/licenses/COPYING.
Exact upstream source and COPYING: vendor/mutagen-1.47.0.tar.gz.
Official release: https://pypi.org/project/mutagen/1.47.0/
SHA-256 was verified against PyPI release metadata over HTTPS.

DJ Library app source is included in this package under AGPL-3.0; see LICENSE.
The source archives are included so this package does not depend on the
availability of upstream source downloads.

VERIFIED ARTIFACT HASHES
'''
    for name, checksum in EXPECTED.items():
        notices += checksum + '  ' + name + '\n'
    notices += digest(source_archive) + '  ' + source_archive.name + '\n'
    (stage / 'THIRD-PARTY.txt').write_text(notices)
    files = {str(path.relative_to(stage)): digest(path) for path in sorted(stage.rglob('*')) if path.is_file()}
    build = '0.2.0-' + hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
    (stage / 'package-manifest.json').write_text(json.dumps({'version': '0.2.0', 'build': build, 'files': files}, indent=2))
    output = args.output / 'DJ-Library-Mac.zip'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                # Upstream zip/wheel assets are already compressed.
                compression = zipfile.ZIP_STORED if path.suffix in {'.zip', '.whl', '.gz'} else zipfile.ZIP_DEFLATED
                archive.write(path, 'DJ-Library/' + str(path.relative_to(stage)), compress_type=compression)
    (args.output / 'DJ-Library-Mac.sha256').write_text(digest(output) + '  DJ-Library-Mac.zip\n')
    print(json.dumps({'package': str(output), 'bytes': output.stat().st_size, 'sha256': digest(output), 'build': build}))


if __name__ == '__main__':
    main()
