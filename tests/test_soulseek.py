import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from djlib.soulseek import Soulseek


class SoulseekAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = Soulseek(Path(self.temp.name))
        self.addCleanup(self.client.stop)

    def test_results_sort_extended_and_queue_exact_file(self):
        self.client.search_ids.add('search')
        self.client.request = Mock(return_value={'state': 'Completed', 'responses': [
            {'username': 'peer', 'hasFreeUploadSlot': True, 'files': [
                {'filename': 'Music\\Radio Mix.mp3', 'size': 100},
                {'filename': 'Music\\Extended Mix.flac', 'size': 200},
                {'filename': 'cover.jpg', 'size': 30}]}]})
        result = self.client.results('search')
        self.assertEqual(result['total'], 2)
        self.assertTrue(result['files'][0]['extended'])
        selection = result['files'][0]['selection']
        self.client.download(selection)
        self.client.request.assert_called_with('POST', 'transfers/downloads/peer',
            [{'filename': 'Music\\Extended Mix.flac', 'size': 200}])

    def test_unknown_selection_and_search_rejected(self):
        with self.assertRaises(ValueError):
            self.client.download('not-selected')
        with self.assertRaises(ValueError):
            self.client.results('not-started')

    def test_search_records_returned_id(self):
        self.client.request = Mock(return_value={'id': 'fixture-id'})
        self.assertEqual(self.client.search('artist extended')['id'], 'fixture-id')
        self.assertIn('fixture-id', self.client.search_ids)


@unittest.skipUnless(os.environ.get('DJ_TEST_SLSKD'), 'Set DJ_TEST_SLSKD to run the real native client API test')
class NativeSlskdTests(unittest.TestCase):
    def test_official_binary_starts_with_authenticated_loopback_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            key = 'integration-test-key-not-a-real-credential'
            config = root / 'slskd.yml'
            config.write_text(f'''flags:
  no_connect: true
  no_share_scan: true
web:
  port: {port}
  ip_address: 127.0.0.1
  https:
    disabled: true
  authentication:
    username: local-test
    password: generated-test-only
    api_keys:
      test:
        key: {key}
        role: administrator
        cidr: 127.0.0.1/32
shares:
  directories: []
''')
            environment = os.environ.copy()
            environment['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = '1'
            environment['DOTNET_BUNDLE_EXTRACT_BASE_DIR'] = str(root / 'runtime')
            executable = Path(os.environ['DJ_TEST_SLSKD'])
            with (root / 'service.log').open('w') as log:
                process = subprocess.Popen([str(executable), '--app-dir', str(root), '--config', str(config)],
                                            cwd=executable.parent, env=environment, stdout=log, stderr=log)
                try:
                    address = f'http://127.0.0.1:{port}/api/v0/server'
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        self.assertIsNone(process.poll(), 'Native slskd exited during startup')
                        try:
                            with urlopen(Request(address, headers={'X-API-Key': key}), timeout=1) as response:
                                state = json.load(response)
                            break
                        except OSError:
                            time.sleep(.2)
                    else:
                        self.fail('Native slskd API did not become ready')
                    self.assertFalse(state['isLoggedIn'])
                    with self.assertRaises(HTTPError) as error:
                        urlopen(address, timeout=2)
                    self.assertEqual(error.exception.code, 401)
                    with urlopen(Request(address.replace('/server', '/transfers/downloads'), headers={'X-API-Key': key}), timeout=2) as response:
                        self.assertEqual(json.load(response), [])
                finally:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
