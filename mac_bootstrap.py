"""Offline, per-user installer. Run using the bundled Install.command launcher."""
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def hash_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def install():
    if sys.platform != 'darwin' or platform.machine() != 'x86_64':
        raise RuntimeError('This package is built for an Intel Mac. No system changes were made.')
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required. The installer found ' + platform.python_version())
    source = Path(__file__).resolve().parent
    manifest = json.loads((source / 'package-manifest.json').read_text())
    print('Checking the package and bundled dependencies…', flush=True)
    for name, checksum in manifest['files'].items():
        candidate = (source / name).resolve()
        if source not in candidate.parents or hash_file(candidate) != checksum:
            raise RuntimeError('Package verification failed: ' + name)
    release = Path.home() / 'Applications/DJ Library/releases' / manifest['build']
    release.mkdir(parents=True, exist_ok=True)
    for name in manifest['files']:
        target = release / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source / name, target)
        elif hash_file(target) != manifest['files'][name]:
            raise RuntimeError('An installed file has been changed; leaving it in place: ' + str(target))
    dependency = release / 'vendor/mutagen-1.47.0-py3-none-any.whl'
    slskd_archive = release / 'vendor/slskd-0.24.5-osx-x64.zip'
    binary_dir = release / 'vendor/slskd'
    if not (binary_dir / 'slskd').exists():
        print('Installing the verified Intel Mac Soulseek client…', flush=True)
        binary_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(slskd_archive) as archive:
            for item in archive.infolist():
                resolved = (binary_dir / item.filename).resolve()
                if binary_dir.resolve() not in resolved.parents:
                    raise RuntimeError('Unexpected archive path')
            archive.extractall(binary_dir)
    (binary_dir / 'slskd').chmod(0o755)
    python = release / '.venv/bin/python'
    if not python.exists():
        print('Creating the app’s private Python environment…', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(release / '.venv')], check=True)
    print('Installing the bundled audio-tag reader. No online package downloads needed…', flush=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps',
                    '--disable-pip-version-check', str(dependency)], check=True)
    subprocess.run([str(python), '-c', 'import mutagen; from djlib.web import App'], cwd=release, check=True)
    launcher = '#!/bin/bash\n# DJ-LIBRARY-MANAGED-LAUNCHER\nset -e\ncd ' + shlex.quote(str(release)) + '\nexec ' + shlex.quote(str(python)) + ' -m djlib.web\n'
    locations = [Path.home() / 'Applications/DJ Library/Start DJ Library.command']
    desktop = Path.home() / 'Desktop'
    if desktop.is_dir():
        locations.append(desktop / 'DJ Library.command')
    for path in locations:
        if path.exists() and 'DJ-LIBRARY-MANAGED-LAUNCHER' not in path.read_text():
            print('Keeping your existing file: ' + str(path), flush=True)
            continue
        path.write_text(launcher)
        path.chmod(0o755)
    print('\nInstallation complete. Opening DJ Library in your browser.\nNext time, double-click DJ Library.command on your Desktop.\nKeep the launcher’s Terminal window open while using the app.\n', flush=True)
    os.chdir(release)
    os.execv(str(python), [str(python), '-m', 'djlib.web'])


if __name__ == '__main__':
    try:
        install()
    except Exception as error:
        print('\nInstallation stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
