import os
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


class InterviewFolderStateIsolationTests(unittest.TestCase):
    """Interview Processing State Isolation / Independent Watch Folder
    Support: the meeting and interview watch folders each get their own
    scan snapshot and StateStore, so a same-named file in both folders is
    tracked with completely independent success/failed/retry state."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.meeting_folder = Path(self.tmpdir.name) / "meeting"
        self.interview_folder = Path(self.tmpdir.name) / "interview"
        self.meeting_folder.mkdir()
        self.interview_folder.mkdir()

        self.meeting_snapshot = self.meeting_folder / "_snapshot.json"
        self.interview_snapshot = self.interview_folder / "_snapshot.json"
        self.meeting_store = StateStore(self.meeting_folder / "_state.json")
        self.interview_store = StateStore(self.interview_folder / "_state.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_same_filename_success_in_one_folder_does_not_affect_the_other(self):
        meeting_file = self.meeting_folder / "recording.mp4"
        interview_file = self.interview_folder / "recording.mp4"
        meeting_file.write_bytes(b"meeting bytes")
        interview_file.write_bytes(b"interview bytes")
        # Pin both files to the identical mtime so make_file_id (filename +
        # mtime) would collide if the two folders shared one StateStore --
        # the exact scenario Independent Watch Folder Support guards
        # against: a shared store would make is_processed() report the
        # interview file as already-done because the meeting file with the
        # same id succeeded, silently skipping it forever.
        shared_mtime = meeting_file.stat().st_mtime
        os.utime(interview_file, (shared_mtime, shared_mtime))

        meeting_file_id = StateStore.make_file_id(meeting_file.name, meeting_file.stat().st_mtime)
        self.meeting_store.mark_success(meeting_file_id)

        # The interview file of the same name+mtime, in its own folder with
        # its own store, was never touched there -- two stable-scan passes
        # make it ready for processing as normal, unaffected by the
        # meeting store's success record.
        get_files_to_process(
            self.interview_folder, self.interview_snapshot, self.interview_store, max_retry_count=3
        )
        interview_to_process = get_files_to_process(
            self.interview_folder, self.interview_snapshot, self.interview_store, max_retry_count=3
        )
        self.assertIn(interview_file, interview_to_process)

        interview_file_id = StateStore.make_file_id(interview_file.name, interview_file.stat().st_mtime)
        self.assertIsNone(self.interview_store.get(interview_file_id))


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
