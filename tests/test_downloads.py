import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_downloads import ensure


class VerifiedDownloadTests(unittest.TestCase):
    def test_bad_download_is_rejected_and_existing_file_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            target = cache / 'asset.zip'
            target.write_bytes(b'existing')
            def untrusted_download(url, path):
                path.write_bytes(b'wrong artifact')
            with patch('scripts.prepare_downloads.fetch', side_effect=untrusted_download):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    ensure('asset.zip', 'https://example.com/asset', hashlib.sha256(b'expected').hexdigest(), cache)
            self.assertEqual(target.read_bytes(), b'existing')
            self.assertEqual(list(cache.iterdir()), [target])

    def test_verified_cache_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            (cache / 'asset.zip').write_bytes(b'expected')
            with patch('scripts.prepare_downloads.fetch') as fetch:
                ensure('asset.zip', 'https://example.com/asset', hashlib.sha256(b'expected').hexdigest(), cache)
            fetch.assert_not_called()
