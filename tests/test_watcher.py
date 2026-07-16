import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from state_store import StateStore
from watcher import get_files_to_process, scan_stable_files


class WatcherStabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)
        self.snapshot_path = self.folder / "_snapshot.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_file_still_syncing_is_not_processed(self):
        audio = self.folder / "meeting.m4a"
        audio.write_bytes(b"a" * 100)

        # Pass 1: first time seeing the file, nothing to compare against yet.
        stable = scan_stable_files(self.folder, self.snapshot_path)
        self.assertEqual(stable, [])

        # Simulate the cloud sync client still writing (size changes).
        audio.write_bytes(b"a" * 200)
        stable = scan_stable_files(self.folder, self.snapshot_path)
        self.assertEqual(stable, [], "file size changed between scans, should not be stable yet")

    def test_stable_file_is_processed(self):
        audio = self.folder / "meeting.m4a"
        audio.write_bytes(b"a" * 200)

        scan_stable_files(self.folder, self.snapshot_path)  # Pass 1: baseline
        stable = scan_stable_files(self.folder, self.snapshot_path)  # Pass 2: unchanged

        self.assertEqual(stable, [audio])


class WatcherRetryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmpdir.name)
        self.snapshot_path = self.folder / "_snapshot.json"
        self.state_path = self.folder / "_state.json"
        self.store = StateStore(self.state_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_file_at_retry_limit_is_excluded(self):
        audio = self.folder / "broken.m4a"
        audio.write_bytes(b"b" * 50)

        file_id = StateStore.make_file_id(audio.name, audio.stat().st_mtime)
        for _ in range(3):
            self.store.mark_failed(file_id, "corrupt", max_retry_count=3)

        to_process = get_files_to_process(
            self.folder, self.snapshot_path, self.store, max_retry_count=3
        )
        self.assertNotIn(audio, to_process)


if __name__ == "__main__":
    unittest.main()
