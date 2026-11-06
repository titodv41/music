"""Fetch pinned official assets when installing from a Git checkout or source ZIP."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    'slskd-0.24.5-osx-x64.zip': (
        'https://github.com/slskd/slskd/releases/download/0.24.5/slskd-0.24.5-osx-x64.zip',
        '8bdb6bbb04c8144510cbd58fcd62c3c81779e6aaa13c29b3c4f4788807c2dd70'),
    'slskd-0.24.5-source.zip': (
        'https://codeload.github.com/slskd/slskd/zip/refs/tags/0.24.5',
        '1418af8887fad958bf40d3bc4762a8bb29a2bb3cf24eaed0ed713662ed8c1123'),
}
MUTAGEN = {
    'mutagen-1.47.0-py3-none-any.whl': 'edd96f50c5907a9539d8e5bba7245f62c9f520aef333d13392a79a4f70aca719',
    'mutagen-1.47.0.tar.gz': '719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99',
}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fetch(url, target):
    subprocess.run(['curl', '--fail', '--location', '--show-error', '--silent',
                    '--retry', '2', '--connect-timeout', '20', '--max-time', '300',
                    '--proto', '=https', '--proto-redir', '=https',
                    '--output', str(target), url], check=True)


def ensure(name, url, checksum, cache):
    target = cache / name
    if target.exists() and digest(target) == checksum:
        print('Already verified: ' + name, flush=True)
        return
    print('Downloading and verifying ' + name + '…', flush=True)
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        fetch(url, temporary)
        if digest(temporary) != checksum:
            raise ValueError('Upstream checksum mismatch. Stopping: ' + name)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--cache', type=Path, default=ROOT / '.dj-library/downloads')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise ValueError('Python 3.10 or newer is required.')
    if not args.prepare_only and sys.platform != 'darwin':
        raise ValueError('This installer is for macOS.')
    args.cache.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in SOURCES.items():
        ensure(name, url, checksum, args.cache)
    missing = [name for name, checksum in MUTAGEN.items()
               if not (args.cache / name).exists() or digest(args.cache / name) != checksum]
    if missing:
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / 'metadata.json'
            fetch('https://pypi.org/pypi/mutagen/1.47.0/json', metadata_path)
            assets = {asset['filename']: asset for asset in json.loads(metadata_path.read_text())['urls']}
        for name in missing:
            asset = assets[name]
            parsed = urlparse(asset['url'])
            if parsed.scheme != 'https' or parsed.hostname != 'files.pythonhosted.org':
                raise ValueError('Unexpected package host. Stopping installation.')
            ensure(name, asset['url'], MUTAGEN[name], args.cache)
    subprocess.run([sys.executable, str(ROOT / 'scripts/build_mac.py'), '--assets', str(args.cache)], check=True)
    if args.prepare_only:
        print('Verified installer package is ready in ' + str(ROOT / 'dist'), flush=True)
        return
    bootstrap = ROOT / 'dist/DJ-Library/mac_bootstrap.py'
    os.execv(sys.executable, [sys.executable, str(bootstrap)])


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Installation stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
