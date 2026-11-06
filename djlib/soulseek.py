"""Managed slskd process and API adapter. Credentials stay on the user's Mac."""
import atexit
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Soulseek:
    def __init__(self, directory, executable=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.executable = Path(executable) if executable else Path(__file__).parent.parent / 'vendor/slskd/slskd'
        self.process = None
        self.port = None
        self.key = secrets.token_urlsafe(32)
        self.selections = {}
        self.search_ids = set()
        self.download_dir = Path.home() / 'Music/DJ Inbox'
        self.api = build_opener(ProxyHandler({}), NoRedirect())
        self.log = None
        atexit.register(self.stop)

    def status(self):
        return {'installed': self.executable.is_file(),
                'running': bool(self.process and self.process.poll() is None),
                'inbox': str(self.download_dir), 'version': '0.24.5',
                'note': 'Close your other Soulseek client before connecting with the same account.'}

    def connect(self, username, password):
        self.stop()
        if not self.executable.is_file():
            raise ValueError('Bundled slskd is missing. Run the Mac installer again.')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]
        self.download_dir.mkdir(parents=True, exist_ok=True)
        incomplete = self.directory / 'incomplete'
        incomplete.mkdir(exist_ok=True)
        # All dynamic YAML strings are JSON quoted, which is valid YAML scalar syntax.
        config = '\n'.join([
            'web:', f'  port: {self.port}', '  ip_address: 127.0.0.1',
            '  https:', '    disabled: true',
            '  authentication:', '    username: dj-library',
            '    password: ' + json.dumps(secrets.token_urlsafe(32)),
            '    api_keys:', '      dj_library:', '        key: ' + json.dumps(self.key),
            '        role: administrator', '        cidr: 127.0.0.1/32',
            'directories:', '  downloads: ' + json.dumps(str(self.download_dir)),
            '  incomplete: ' + json.dumps(str(incomplete)),
            'shares:', '  directories: []',
            'soulseek:', '  username: ' + json.dumps(username),
            # Password is supplied in child process environment, never persisted here.
            '  listen_port: 50319',
        ]) + '\n'
        config_path = self.directory / 'slskd.yml'
        with config_path.open('w') as stream:
            os.chmod(config_path, 0o600)
            stream.write(config)
        environment = os.environ.copy()
        environment.update(SLSKD_SLSK_PASSWORD=password, SLSKD_SLSK_USERNAME=username,
                           DOTNET_BUNDLE_EXTRACT_BASE_DIR=str(self.directory / 'runtime'),
                           DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1')
        self.log = (self.directory / 'service.log').open('a')
        os.chmod(self.directory / 'service.log', 0o600)
        try:
            self.process = subprocess.Popen([str(self.executable), '--app-dir', str(self.directory),
                                             '--config', str(config_path)],
                                            cwd=self.executable.parent, env=environment,
                                            stdout=self.log, stderr=self.log)
        except OSError:
            self.stop()
            raise ValueError('slskd could not start. macOS may require approval in System Preferences → Security & Privacy. Its executable is inside DJ-Library/vendor/slskd.') from None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ValueError('slskd exited during startup. Local diagnostic log: ' + str(self.directory / 'service.log'))
            try:
                server = self.request('GET', 'server')
                if server.get('isLoggedIn'):
                    return 'Connected to Soulseek. Search for an artist and track in the Downloads tab.'
                if server.get('isConnected'):
                    # Do not call a TCP connection a successful account login.
                    pass
            except ValueError:
                pass
            time.sleep(0.5)
        raise ValueError('slskd is running, but a Soulseek login was not confirmed. Check your username/password, close other clients using this account, and retry. Log: ' + str(self.directory / 'service.log'))

    def request(self, method, endpoint, payload=None):
        if not self.process or self.process.poll() is not None:
            raise ValueError('Connect to Soulseek first.')
        request = Request(f'http://127.0.0.1:{self.port}/api/v0/' + endpoint, method=method,
                          headers={'X-API-Key': self.key, 'Content-Type': 'application/json'},
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with self.api.open(request, timeout=20) as response:
                data = response.read()
                return json.loads(data) if data else {'queued': True}
        except HTTPError as error:
            raise ValueError(f'Soulseek client returned HTTP {error.code}. Confirm it is logged in and retry.') from None
        except (URLError, OSError, ValueError):
            raise ValueError('The local Soulseek client is not responding yet. Check the connection and retry.') from None

    def search(self, query):
        result = self.request('POST', 'searches', {'searchText': query})
        self.search_ids.add(str(result['id']))
        return {'id': result['id'], 'message': 'Search started. Refresh results in a few seconds.'}

    def results(self, identifier):
        if identifier not in self.search_ids:
            raise ValueError('Start a search in this session first.')
        result = self.request('GET', 'searches/' + quote(identifier, safe='') + '?includeResponses=true')
        files = []
        for response in result.get('responses', []):
            for file in response.get('files', []):
                filename = file.get('filename', '')
                if Path(filename.replace('\\', '/')).suffix.lower() not in {'.flac', '.mp3', '.wav', '.aiff', '.aif', '.m4a'}:
                    continue
                selection = uuid.uuid5(uuid.NAMESPACE_URL, identifier + response['username'] + filename).hex
                entry = {'selection': selection, 'username': response['username'],
                         'filename': filename, 'size': file['size'],
                         'extended': 'extended' in filename.lower(),
                         'freeUploadSlots': response.get('hasFreeUploadSlot', False)}
                self.selections[selection] = entry
                files.append(entry)
        files.sort(key=lambda x: (not x['extended'], not x['freeUploadSlots'], x['filename']))
        return {'files': files[:300], 'total': len(files), 'state': result.get('state', '')}

    def download(self, selection):
        entry = self.selections.get(selection)
        if not entry:
            raise ValueError('Choose a file from the current search results.')
        self.request('POST', 'transfers/downloads/' + quote(entry['username'], safe=''),
                     [{'filename': entry['filename'], 'size': entry['size']}])
        return {'message': 'Download queued. Check transfer status below. Completed files go to ' + str(self.download_dir)}

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process = None
        if self.log:
            self.log.close()
            self.log = None
