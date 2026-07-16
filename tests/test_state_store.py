import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from state_store import FAILED, NEEDS_MANUAL_INTERVENTION, SUCCESS, StateStore


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "state.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_duplicate_write_overwrites_and_is_queryable(self):
        store = StateStore(self.path)
        file_id = StateStore.make_file_id("meeting_0704.m4a", 1000)

        store.mark_success(file_id)
        self.assertTrue(store.is_processed(file_id))

        # Second write for the same file identity should overwrite, not duplicate.
        store.mark_success(file_id)
        self.assertEqual(len(store._records), 1)
        self.assertEqual(store.get(file_id).status, SUCCESS)

        # Reloading from disk should reflect the same overwritten state.
        reloaded = StateStore(self.path)
        self.assertTrue(reloaded.is_processed(file_id))
        self.assertEqual(len(reloaded._records), 1)

    def test_failed_retry_below_limit_stays_failed(self):
        store = StateStore(self.path)
        file_id = StateStore.make_file_id("broken.m4a", 2000)

        store.mark_failed(file_id, "corrupt audio", max_retry_count=3)
        record = store.get(file_id)
        self.assertEqual(record.status, FAILED)
        self.assertEqual(record.retry_count, 1)

    def test_failed_retry_exceeding_limit_needs_manual_intervention(self):
        store = StateStore(self.path)
        file_id = StateStore.make_file_id("broken.m4a", 2000)

        for _ in range(3):
            store.mark_failed(file_id, "corrupt audio", max_retry_count=3)

        record = store.get(file_id)
        self.assertEqual(record.status, NEEDS_MANUAL_INTERVENTION)
        self.assertNotIn(file_id, store.retryable_failed_ids(max_retry_count=3))


if __name__ == "__main__":
    unittest.main()
