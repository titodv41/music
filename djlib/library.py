import hashlib
import json
import os
import re
import shutil
import unicodedata
from pathlib import Path

from mutagen import File

EXTENSIONS = {'.mp3', '.flac', '.aiff', '.aif', '.m4a', '.mp4', '.wav', '.ogg', '.opus'}
ARTISTS = ['Ben Sterling', 'Mau P', 'Solomun', 'Joseph Capriati', 'Prospa', 'ANOTR',
           'Brunello', 'Beltran', 'David Guetta', 'Vintage Culture']


def safe(value):
    value = unicodedata.normalize('NFC', str(value))
    return re.sub(r'[\x00-\x1f/\\:]', '_', value).strip(' .')[:90] or 'Unknown'


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tags_for(path):
    audio = File(path)
    tags = {}
    if audio is None:
        raise ValueError('Unsupported or invalid audio file')
    for key, value in (audio.tags or {}).items():
        name = str(key).lower()
        if hasattr(value, 'text'):
            value = value.text
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ''
        tags[name] = str(value)

    def get(*names):
        for name in names:
            if tags.get(name):
                return tags[name].strip()
        return ''

    def number(value):
        try:
            n = float(value)
            return n if 0 < n < 1000 else None
        except (ValueError, TypeError):
            return None

    comments = ' '.join(v for k, v in tags.items() if 'comm' in k or 'description' in k)
    energy = number(get('txxx:energy level', 'txxx:energylevel', 'txxx:energy', 'energy', 'energy level', 'energylevel',
                        '----:com.apple.itunes:energy level'))
    if energy is None:
        match = re.search(r'\benergy(?:\s+level)?\s*[:=]?\s*(10|[1-9])\b', comments, re.I)
        energy = float(match.group(1)) if match else None
    if energy is not None and (not energy.is_integer() or energy > 10):
        energy = None
    key = get('tkey', 'initialkey', 'key', '----:com.apple.itunes:initialkey')
    if not key:
        match = re.search(r'\b(1[0-2]|[1-9])([AB])\b', comments, re.I)
        key = match.group(0).upper() if match else ''
    return {
        'artist': get('tpe1', 'artist', '\xa9art'),
        'title': get('tit2', 'title', '\xa9nam') or path.stem,
        'genre': get('tcon', 'genre', '\xa9gen'),
        'bpm': number(get('tbpm', 'bpm', 'tmpo')),
        'key': key,
        'energy': int(energy) if energy else None,
        'duration': round(audio.info.length, 2),
    }


def scan(root):
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Choose a music folder')
    tracks, errors, hashes = [], [], {}
    def walk_error(error):
        errors.append({'path': str(error.filename), 'error': str(error)})
    for directory, dirs, files in os.walk(root, onerror=walk_error, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                continue
            try:
                track = tags_for(path)
                checksum = digest(path)
                track.update(path=str(path), sha256=checksum, bytes=path.stat().st_size,
                             duplicate_of=hashes.get(checksum))
                hashes.setdefault(checksum, str(path))
                track['needs_review'] = [k for k in ('artist', 'genre', 'bpm', 'key', 'energy')
                                         if not track.get(k)]
                tracks.append(track)
            except Exception as error:
                errors.append({'path': str(path), 'error': str(error)})
    return {'version': 1, 'root': str(root), 'tracks': tracks, 'errors': errors}


def relative_path(track):
    bpm = track.get('bpm')
    start = int(bpm // 5) * 5 if bpm else None
    band = f'{start:03d}-{start + 4:03d} BPM' if start is not None else 'Unknown BPM'
    energy = track.get('energy')
    level = f'Energy {energy:02d}' if energy else 'Unknown energy'
    label = f"{track.get('artist') or 'Unknown artist'} - {track['title']} [{track.get('key') or 'Unknown key'}]"
    # A full content hash prevents collisions and makes repeat copies idempotent.
    filename = f"{safe(label)}--{track['sha256']}{Path(track['path']).suffix.lower()}"
    return Path(safe(track.get('genre') or 'Needs genre review')) / level / band / filename


def plan(report, destination):
    root = Path(report['root']).resolve()
    target = Path(destination).expanduser().resolve()
    if target == root or root in target.parents or target in root.parents:
        raise ValueError('The organized library must be separate from the scanned library')
    return [{'source': t['path'], 'destination': str(target / relative_path(t)),
             'sha256': t['sha256']} for t in report['tracks'] if not t['duplicate_of']]


def copy_library(report, destination, journal):
    entries = plan(report, destination)
    journal = Path(journal).expanduser()
    journal.parent.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    with journal.open('a') as log:
        for entry in entries:
            source, target = Path(entry['source']), Path(entry['destination'])
            if source.is_symlink() or digest(source) != entry['sha256']:
                raise ValueError(f'Source changed since scan: {source}')
            target.parent.mkdir(parents=True, exist_ok=True)
            # Reject symlinked destination directories, including pre-existing ones.
            if target.parent.resolve() != target.parent or target.is_symlink():
                raise ValueError(f'Unsafe destination: {target}')
            if target.exists():
                if digest(target) != entry['sha256']:
                    raise ValueError(f'Destination conflict: {target}')
                skipped += 1
                continue
            created = False
            try:
                with target.open('xb') as output:
                    created = True
                    with source.open('rb') as input_stream:
                        shutil.copyfileobj(input_stream, output)
                if digest(target) != entry['sha256']:
                    raise ValueError(f'Copy verification failed: {target}')
            except Exception:
                if created and target.exists():
                    target.unlink()
                raise
            log.write(json.dumps(entry) + '\n')
            log.flush()
            os.fsync(log.fileno())
            copied += 1
    return {'copied': copied, 'already_present': skipped, 'journal': str(journal)}


def undo(journal):
    removed = 0
    for line in Path(journal).read_text().splitlines():
        entry = json.loads(line)
        target = Path(entry['destination'])
        if target.exists():
            if target.is_symlink() or digest(target) != entry['sha256']:
                raise ValueError(f'Copied file changed; leaving it in place: {target}')
            target.unlink()
            removed += 1
    return {'removed_copies': removed}


def export_m3u(report, destination, output):
    paths = [e['destination'] for e in plan(report, destination)]
    if any('\n' in p or '\r' in p for p in paths):
        raise ValueError('Playlist paths cannot contain newlines')
    missing = [p for p in paths if not Path(p).is_file()]
    if missing:
        raise ValueError('Copy the organized library before exporting its playlist')
    Path(output).write_text('#EXTM3U\n' + '\n'.join(paths) + '\n', encoding='utf-8')
    return {'playlist': str(output), 'tracks': len(paths)}
