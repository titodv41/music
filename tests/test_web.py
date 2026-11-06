import json
import tempfile
import threading
import time
import unittest
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mutagen.wave import WAVE
from mutagen.id3 import TIT2, TPE1, TCON, TBPM, TKEY, TXXX
from djlib.web import App, Handler


class BrowserApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = App(self.root / 'data')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, path, body=None, token=True, origin=None):
        headers = {'X-DJ-Token': self.app.token} if token else {}
        if origin:
            headers['Origin'] = origin
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.url + path, data=data, headers=headers)
        with urlopen(request, timeout=10) as response:
            return response.read()

    def wait(self):
        deadline = time.monotonic() + 10
        while self.app.busy and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(self.app.busy)
        self.assertFalse(self.app.error, self.app.error)

    def test_library_workflow_over_http(self):
        source = self.root / 'music'
        source.mkdir()
        track = source / 'test.wav'
        with wave.open(str(track), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
            stream.writeframes(b'\0\0' * 8000)
        audio = WAVE(track); audio.add_tags()
        for frame in [TIT2(text=['Fixture']), TPE1(text=['Artist']), TCON(text=['House']),
                      TBPM(text=['126']), TKEY(text=['9A']), TXXX(desc='Energy', text=['6'])]:
            audio.tags.add(frame)
        audio.save()
        destination = self.root / 'organized'
        self.request('/api/settings', {'source': str(source), 'destination': str(destination)})
        self.request('/api/scan', {}); self.wait()
        state = json.loads(self.request('/api/state'))
        self.assertEqual(state['total'], 1)
        self.assertEqual(state['review_count'], 0)
        self.assertEqual(json.loads(self.request('/api/tracks?q=Fixture'))['matching'], 1)
        preview = json.loads(self.request('/api/preview', {}))
        self.assertEqual(preview['count'], 1)
        self.request('/api/copy', {}); self.wait()
        self.assertTrue(self.app.playlist.exists())
        self.assertEqual(len(list(destination.rglob('*.wav'))), 1)
        self.request('/api/undo', {}); self.wait()
        self.assertEqual(len(list(destination.rglob('*.wav'))), 0)
        self.assertTrue(track.exists())

    def test_local_page_requires_token(self):
        with self.assertRaises(HTTPError) as error:
            self.request('/', token=False)
        self.assertEqual(error.exception.code, 403)
        page = self.request('/?token=' + self.app.token).decode()
        self.assertIn('<title>DJ Library · Tito</title>', page)
        self.assertNotIn('__TOKEN__', page)

    def test_api_rejects_missing_token_and_foreign_origin(self):
        for options in [{'token': False}, {'origin': 'https://other.example'}]:
            with self.assertRaises(HTTPError) as error:
                self.request('/api/settings', {'source': '/tmp'}, **options)
            self.assertEqual(error.exception.code, 403)

    def test_copy_requires_preview(self):
        with self.assertRaises(HTTPError) as error:
            self.request('/api/copy', {})
        self.assertEqual(error.exception.code, 400)

    def test_wishlist_persists(self):
        self.request('/api/settings', {'wishlist': ['Mau P - Track', 'Mau P - Track', '']})
        other = App(self.root / 'data')
        self.assertEqual(other.settings['wishlist'], ['Mau P - Track'])


if __name__ == '__main__':
    unittest.main()
