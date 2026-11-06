"""Optional browser acceptance check; requires Playwright in the developer environment."""
import json
import shutil
import tempfile
import threading
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

from mutagen.wave import WAVE
from mutagen.id3 import TIT2, TPE1, TCON, TBPM, TKEY, TXXX
from playwright.sync_api import sync_playwright, expect
from djlib.web import App, Handler


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / 'source'; source.mkdir()
        track = source / 'test.wav'
        with wave.open(str(track), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
            stream.writeframes(b'\0\0' * 8000)
        audio = WAVE(track); audio.add_tags()
        for tag in [TIT2(text=['Test Extended Mix']), TPE1(text=['Test Artist']), TCON(text=['House']),
                    TBPM(text=['128']), TKEY(text=['8A']), TXXX(desc='Energy Level', text=['7'])]:
            audio.tags.add(tag)
        audio.save()
        app = App(root / 'data')
        app.settings['destination'] = str(root / 'organized')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.app = app
        threading.Thread(target=server.serve_forever, daemon=True).start()
        errors = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=shutil.which('chromium'), args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/?token={app.token}')
                page.locator('#source').fill(str(source))
                page.locator('#scan').click()
                expect(page.locator('#total')).to_have_text('1', timeout=15000)
                expect(page.locator('#tracks')).to_contain_text('Test Extended Mix')
                page.locator('[data-tab="organize"]').click()
                page.locator('#preview').click()
                expect(page.locator('#planTitle')).to_contain_text('1 unique')
                page.locator('#copy').click()
                expect(page.locator('#playlist')).to_contain_text('.m3u8', timeout=15000)
                assert len(list((root / 'organized').rglob('*.wav'))) == 1
                page.on('dialog', lambda dialog: dialog.accept())
                page.locator('#undo').click()
                expect(page.locator('#status')).to_contain_text('Removed 1', timeout=15000)
                assert track.exists()
                page.locator('[data-tab="discover"]').click()
                page.locator('#query').fill('Mau P Test')
                page.locator('#saveWish').click()
                expect(page.locator('#wishlist')).to_have_value('Mau P Test')
                page.locator('#discoverLinks').click()
                assert page.locator('#links a').count() == 3
                page.locator('[data-tab="library"]').click()
                page.screenshot(path='/tmp/dj-library-desktop.png', full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/dj-library-mobile.png', full_page=True)
                assert not errors, errors
                browser.close()
            print(json.dumps({'browser_workflow': 'passed', 'page_errors': errors,
                              'checks': ['scan', 'preview', 'copy', 'playlist', 'undo', 'wishlist', 'discovery links']}))
        finally:
            app.soulseek.stop()
            server.shutdown(); server.server_close()


if __name__ == '__main__':
    main()
