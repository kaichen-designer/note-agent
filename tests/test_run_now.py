import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import run_now


class RunNowLauncherTests(unittest.TestCase):
    """run_now.py is the manual-trigger entry point behind run_now.bat:
    it must launch main.py under pythonw detached from the console."""

    def test_command_targets_main_under_venv_pythonw(self):
        cmd = run_now.build_command()
        self.assertTrue(cmd[0].endswith("pythonw.exe"))
        self.assertIn(".venv", cmd[0])
        self.assertTrue(cmd[1].endswith("main.py"))

    def test_launch_is_detached_from_console(self):
        with (
            patch.object(run_now, "PYTHONW", Path(sys.executable)),
            patch.object(run_now.subprocess, "Popen") as mock_popen,
        ):
            exit_code = run_now.main()
        self.assertEqual(exit_code, 0)
        _, kwargs = mock_popen.call_args
        self.assertEqual(kwargs["creationflags"], subprocess.DETACHED_PROCESS)

    def test_missing_venv_reports_error_without_launching(self):
        with (
            patch.object(run_now, "PYTHONW", Path("does-not-exist/pythonw.exe")),
            patch.object(run_now.subprocess, "Popen") as mock_popen,
        ):
            exit_code = run_now.main()
        self.assertEqual(exit_code, 1)
        mock_popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
