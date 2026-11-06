import tempfile
import unittest
import wave
import json
import subprocess
import sys
from pathlib import Path

from mutagen.wave import WAVE
from mutagen.id3 import TIT2, TPE1, TCON, TBPM, TKEY, TXXX

from djlib.library import scan, plan, copy_library, export_m3u, undo


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.track = self.source / 'test.wav'
        with wave.open(str(self.track), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
            stream.writeframes(b'\0\0' * 8000)
        audio = WAVE(self.track)
        audio.add_tags()
        for frame in [TIT2(text=['Track']), TPE1(text=['Artist']), TCON(text=['Tech House']),
                      TBPM(text=['128']), TKEY(text=['8A']), TXXX(desc='EnergyLevel', text=['7'])]:
            audio.tags.add(frame)
        audio.save()
        self.destination = self.root / 'organized'
        self.journal = self.root / 'copies.jsonl'

    def test_scan_copy_playlist_undo(self):
        # Common comment spelling is also supported.
        audio = WAVE(self.track)
        audio.tags.add(TXXX(desc='Energy Level', text=['7'])); audio.save()
        (self.source / 'duplicate.wav').write_bytes(self.track.read_bytes())
        report = scan(self.source)
        self.assertEqual(len(report['tracks']), 2)
        self.assertEqual(sum(bool(t['duplicate_of']) for t in report['tracks']), 1)
        entry = plan(report, self.destination)[0]
        self.assertIn('Tech House/Energy 07/125-129 BPM/', entry['destination'])
        self.assertEqual(copy_library(report, self.destination, self.journal)['copied'], 1)
        self.assertEqual(copy_library(report, self.destination, self.journal)['already_present'], 1)
        playlist = self.root / 'set.m3u8'
        self.assertEqual(export_m3u(report, self.destination, playlist)['tracks'], 1)
        self.assertIn(entry['destination'], playlist.read_text())
        self.assertEqual(undo(self.journal)['removed_copies'], 1)
        self.assertTrue(self.track.exists())

    def test_cli_scan_and_summary(self):
        report = self.root / 'report.json'
        run = subprocess.run([sys.executable, '-m', 'djlib.cli', 'scan', str(self.source),
                              '--output', str(report)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['tracks'], 1)
        self.assertEqual(json.loads(report.read_text())['tracks'][0]['energy'], 7)
        summary = subprocess.run([sys.executable, '-m', 'djlib.cli', 'summary', str(report)],
                                 capture_output=True, text=True)
        self.assertEqual(summary.returncode, 0, summary.stderr)
        self.assertEqual(json.loads(summary.stdout)['missing_tags'], {})

    def test_changed_source_is_not_copied(self):
        report = scan(self.source)
        self.track.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            copy_library(report, self.destination, self.journal)

    def test_changed_copy_is_not_deleted(self):
        report = scan(self.source)
        copy_library(report, self.destination, self.journal)
        target = Path(plan(report, self.destination)[0]['destination'])
        target.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            undo(self.journal)
        self.assertTrue(target.exists())

    def test_source_and_destination_must_be_separate(self):
        report = scan(self.source)
        for target in [self.source, self.source / 'nested', self.root]:
            with self.assertRaises(ValueError):
                plan(report, target)

    def test_unreadable_file_reported(self):
        (self.source / 'broken.mp3').write_bytes(b'broken')
        self.assertEqual(len(scan(self.source)['errors']), 1)

    def test_playlist_requires_existing_copies(self):
        with self.assertRaises(ValueError):
            export_m3u(scan(self.source), self.destination, self.root / 'set.m3u8')


if __name__ == '__main__':
    unittest.main()
