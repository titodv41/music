"""Loopback-only browser interface; no remote access to the music library."""
import argparse
import collections
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .library import ARTISTS, copy_library, export_m3u, plan, scan, undo
from .soulseek import Soulseek


def save_json(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    temp.replace(path)


class App:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.busy = False
        self.message = 'Choose your music folder to begin.'
        self.error = ''
        self.report = None
        self.preview = None
        self.last_journal = None
        self.playlist = None
        self.settings = {'source': '', 'destination': str(Path.home() / 'DJ Organized'),
                         'artists': ARTISTS, 'wishlist': []}
        for name in ('settings', 'report'):
            path = self.directory / (name + '.json')
            if path.exists():
                try:
                    value = json.loads(path.read_text())
                    if name == 'settings':
                        self.settings.update(value)
                    else:
                        self.report = value
                except (OSError, ValueError):
                    self.message = 'A saved session could not be read. You can scan again.'
        self.soulseek = Soulseek(self.directory / 'soulseek')

    def start(self, label, operation):
        with self.lock:
            if self.busy:
                raise ValueError('Another operation is still running. Wait for it to finish.')
            self.busy, self.error, self.message = True, '', label

        def run():
            try:
                message = operation()
                with self.lock:
                    self.message = message or 'Done.'
            except Exception as error:
                with self.lock:
                    self.error = str(error)
                    self.message = 'Operation stopped. See the message below.'
            finally:
                with self.lock:
                    self.busy = False
        threading.Thread(target=run, daemon=True).start()
        return {'started': True}

    def snapshot(self):
        with self.lock:
            report = self.report or {'tracks': [], 'errors': []}
            tracks = report['tracks']
            missing = collections.Counter(k for t in tracks for k in t['needs_review'])
            genres = collections.Counter(t['genre'] or 'Needs genre review' for t in tracks)
            return {'busy': self.busy, 'message': self.message, 'error': self.error,
                    'settings': self.settings.copy(), 'total': len(tracks),
                    'duplicates': sum(bool(t['duplicate_of']) for t in tracks),
                    'missing': dict(missing), 'review_count': sum(bool(t['needs_review']) for t in tracks),
                    'genres': dict(genres), 'errors': report['errors'][:100],
                    'preview': self.preview, 'has_report': self.report is not None,
                    'last_journal': str(self.last_journal) if self.last_journal else None,
                    'playlist': str(self.playlist) if self.playlist else None,
                    'soulseek': self.soulseek.status()}

    def action(self, name, body):
        if name == 'settings':
            with self.lock:
                if self.busy:
                    raise ValueError('Wait for the current operation before changing folders.')
                for key in ('source', 'destination'):
                    if key in body:
                        self.settings[key] = str(body[key]).strip()
                if 'wishlist' in body:
                    self.settings['wishlist'] = list(dict.fromkeys(str(v).strip() for v in body['wishlist'] if str(v).strip()))[:1000]
                save_json(self.directory / 'settings.json', self.settings)
                self.preview = None
            return {'saved': True}
        if name == 'pick':
            if sys.platform != 'darwin':
                raise ValueError('Type the folder path instead. The folder picker needs macOS.')
            def pick():
                result = subprocess.run(['osascript', '-e',
                    'POSIX path of (choose folder with prompt "Choose the music folder to scan")'],
                    capture_output=True, text=True)
                if result.returncode:
                    return 'Folder selection cancelled.'
                with self.lock:
                    self.settings['source'] = result.stdout.strip()
                    self.preview = None
                    save_json(self.directory / 'settings.json', self.settings)
                return 'Music folder selected. Click Scan library.'
            return self.start('Choose a folder in the macOS dialog…', pick)
        if name == 'scan':
            source = self.settings['source']
            if not source:
                raise ValueError('Choose a music folder first.')
            def do_scan():
                report = scan(source)
                save_json(self.directory / 'report.json', report)
                with self.lock:
                    self.report, self.preview = report, None
                return f"Scan finished: {len(report['tracks'])} tracks, {len(report['errors'])} unreadable files."
            return self.start('Reading tags and checking exact duplicates. Large collections can take a while…', do_scan)
        if name == 'preview':
            with self.lock:
                if self.busy or self.report is None:
                    raise ValueError('Finish a library scan first.')
                entries = plan(self.report, self.settings['destination'])
                total_bytes = sum(t['bytes'] for t in self.report['tracks'] if not t['duplicate_of'])
                self.preview = {'count': len(entries), 'bytes': total_bytes, 'entries': entries[:100]}
                return self.preview
        if name == 'copy':
            with self.lock:
                if self.report is None or self.preview is None:
                    raise ValueError('Preview the folder plan before organizing.')
                report, destination = self.report, self.settings['destination']
            def organize():
                if not report['tracks']:
                    raise ValueError('The scan has no readable music files.')
                stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
                journal = self.directory / ('copies-' + stamp + '.jsonl')
                with self.lock:
                    self.last_journal = journal
                result = copy_library(report, destination, journal)
                playlist = Path(destination).expanduser() / ('DJ Library-' + stamp + '.m3u8')
                export_m3u(report, destination, playlist)
                with self.lock:
                    self.playlist = playlist
                return f"Organized {result['copied']} new tracks; {result['already_present']} already present. Playlist saved in your organized folder."
            return self.start('Copying and verifying audio files. Originals stay in place…', organize)
        if name == 'undo':
            journal = self.last_journal
            if journal is None:
                raise ValueError('There is no copy run to undo in this session. Older journals are kept in the app data folder.')
            def do_undo():
                result = undo(journal)
                return f"Removed {result['removed_copies']} unchanged copies. Originals and Rekordbox entries were left in place."
            return self.start('Undoing the most recent copy run…', do_undo)
        if name == 'open-mik':
            if sys.platform != 'darwin':
                raise ValueError('Opening Mixed In Key requires your Mac.')
            import glob
            apps = sorted(glob.glob('/Applications/Mixed*Key*.app') + glob.glob(str(Path.home() / 'Applications/Mixed*Key*.app')))
            if not apps:
                raise ValueError('Mixed In Key was not found in Applications. Open it normally, analyze the source folder, save tags, then scan again.')
            subprocess.run(['open', '-a', apps[-1]], check=True)
            return {'message': 'Mixed In Key opened. Analyze the source folder and write its results to tags, then rescan here.'}
        if name == 'soulseek-connect':
            username, password = str(body.get('username', '')).strip(), str(body.get('password', ''))
            if not username or not password:
                raise ValueError('Enter your Soulseek username and password locally.')
            return self.start('Starting the bundled Soulseek client…', lambda: self.soulseek.connect(username, password))
        if name == 'soulseek-search':
            query = str(body.get('query', '')).strip()
            if not query:
                raise ValueError('Enter an artist and track title.')
            return self.soulseek.search(query)
        if name == 'soulseek-results':
            return self.soulseek.results(str(body.get('id', '')))
        if name == 'soulseek-download':
            return self.soulseek.download(str(body.get('selection', '')))
        if name == 'soulseek-transfers':
            return self.soulseek.request('GET', 'transfers/downloads')
        if name == 'soulseek-stop':
            self.soulseek.stop()
            return {'message': 'Soulseek client stopped.'}
        raise ValueError('Unknown action')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # URLs contain a local session token. Do not log them.

    @property
    def app(self):
        return self.server.app

    def send(self, code, value, content_type='application/json; charset=utf-8'):
        payload = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'nonce-" + self.app.token + "'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self):
        expected_host = f'127.0.0.1:{self.server.server_port}'
        return (self.headers.get('Host') == expected_host and
                secrets.compare_digest(self.headers.get('X-DJ-Token', ''), self.app.token) and
                self.headers.get('Origin', 'http://' + expected_host) == 'http://' + expected_host)

    def do_GET(self):
        parts = urlparse(self.path)
        if parts.path == '/':
            token = parse_qs(parts.query).get('token', [''])[0]
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or not secrets.compare_digest(token, self.app.token):
                return self.send(403, {'error': 'Open the app using its launcher.'})
            html = Path(__file__).with_name('ui.html').read_text().replace('__TOKEN__', self.app.token)
            return self.send(200, html.encode(), 'text/html; charset=utf-8')
        if not self.authorized():
            return self.send(403, {'error': 'Invalid local session'})
        if parts.path == '/api/state':
            return self.send(200, self.app.snapshot())
        if parts.path == '/api/tracks':
            query = parse_qs(parts.query)
            term = query.get('q', [''])[0].casefold()
            mode = query.get('mode', ['all'])[0]
            with self.app.lock:
                tracks = (self.app.report or {}).get('tracks', [])
                tracks = [t for t in tracks if (not term or term in ' '.join(str(t.get(k, '')) for k in ('artist', 'title', 'genre', 'key', 'bpm')).casefold())
                          and (mode != 'review' or t['needs_review']) and (mode != 'duplicates' or t['duplicate_of'])]
                return self.send(200, {'tracks': tracks[:500], 'matching': len(tracks)})
        return self.send(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.authorized():
            return self.send(403, {'error': 'Invalid local session'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 1024 * 1024:
                raise ValueError('Request too large')
            body = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body, dict):
                raise ValueError('Expected an object')
            path = urlparse(self.path).path
            if not path.startswith('/api/'):
                return self.send(404, {'error': 'Not found'})
            self.send(200, self.app.action(path[5:], body))
        except Exception as error:
            self.send(400, {'error': str(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=str(Path.home() / 'Library/Application Support/DJ Library'))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    app = App(args.data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.app = app
    address = f'http://127.0.0.1:{server.server_port}/?token={app.token}'
    print('DJ Library is running. Keep this Terminal window open. Press Control-C to stop.', flush=True)
    print(address, flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.soulseek.stop()
        server.server_close()


if __name__ == '__main__':
    main()
