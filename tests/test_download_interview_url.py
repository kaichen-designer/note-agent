import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import download_interview_url as dl


def _install_fake_yt_dlp(youtube_dl_factory):
    """Build a fake `yt_dlp` module and register it in sys.modules so
    download_interview_url's deferred `import yt_dlp` (kept out of module
    top-level because yt-dlp is an optional dependency not needed by the
    rest of the test suite) picks up the fake instead of the real package."""
    fake_yt_dlp = types.ModuleType("yt_dlp")
    fake_yt_dlp.YoutubeDL = youtube_dl_factory
    return patch.dict(sys.modules, {"yt_dlp": fake_yt_dlp})


class BuildYdlOptsTests(unittest.TestCase):
    """Building yt-dlp options is a pure function (no network), so its
    output shape can be tested directly without downloading anything."""

    def test_output_template_points_into_interview_folder(self):
        opts = dl.build_ydl_opts(r"G:\Interview Record")
        self.assertTrue(opts["outtmpl"].startswith(r"G:\Interview Record"))

    def test_merge_output_format_is_mp4(self):
        opts = dl.build_ydl_opts(r"G:\Interview Record")
        self.assertEqual(opts["merge_output_format"], "mp4")

    def test_no_cookies_file_omits_cookiefile_option(self):
        opts = dl.build_ydl_opts(r"G:\Interview Record", cookies_file=None)
        self.assertNotIn("cookiefile", opts)

    def test_cookies_file_given_sets_cookiefile_option(self):
        opts = dl.build_ydl_opts(r"G:\Interview Record", cookies_file="config/cookies.txt")
        self.assertEqual(opts["cookiefile"], "config/cookies.txt")


class MainArgumentValidationTests(unittest.TestCase):
    """main() must fail fast with a clear message instead of calling
    yt-dlp when the required inputs are missing -- matching the project's
    existing config-validation style in main.py's _load_config()."""

    def test_missing_url_argument_returns_error_without_downloading(self):
        with (
            patch.object(sys, "argv", ["download_interview_url.py"]),
            patch.object(dl, "load_dotenv"),
        ):
            exit_code = dl.main()
        self.assertEqual(exit_code, 1)

    def test_missing_interview_folder_config_returns_error_without_downloading(self):
        with (
            patch.object(sys, "argv", ["download_interview_url.py", "https://vimeo.com/123"]),
            patch.object(dl, "load_dotenv"),
            patch.dict("os.environ", {}, clear=True),
        ):
            exit_code = dl.main()
        self.assertEqual(exit_code, 1)


class MainDownloadTests(unittest.TestCase):
    """When inputs are valid, main() hands the URL to yt-dlp configured to
    save directly into the interview watch folder, so the existing
    scan-transcribe-structure-Notion pipeline picks the result up on its
    next run without any pipeline changes."""

    def test_valid_inputs_invoke_yt_dlp_with_interview_folder_and_url(self):
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
        mock_ydl_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_factory = MagicMock(return_value=mock_ydl_instance)

        env = {"INTERVIEW_WATCH_FOLDER_PATH": r"G:\Interview Record"}
        with (
            patch.object(sys, "argv", ["download_interview_url.py", "https://vimeo.com/123/abc"]),
            patch.object(dl, "load_dotenv"),
            patch.dict("os.environ", env, clear=True),
            _install_fake_yt_dlp(mock_ydl_factory),
        ):
            exit_code = dl.main()

        self.assertEqual(exit_code, 0)
        mock_ydl_instance.download.assert_called_once_with(["https://vimeo.com/123/abc"])
        called_opts = mock_ydl_factory.call_args.args[0]
        self.assertTrue(called_opts["outtmpl"].startswith(r"G:\Interview Record"))
        self.assertNotIn("cookiefile", called_opts)

    def test_cookies_file_env_var_is_forwarded_to_yt_dlp(self):
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
        mock_ydl_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_factory = MagicMock(return_value=mock_ydl_instance)

        env = {
            "INTERVIEW_WATCH_FOLDER_PATH": r"G:\Interview Record",
            "YT_DLP_COOKIES_FILE": "config/cookies.txt",
        }
        with (
            patch.object(sys, "argv", ["download_interview_url.py", "https://vimeo.com/123/abc"]),
            patch.object(dl, "load_dotenv"),
            patch.dict("os.environ", env, clear=True),
            _install_fake_yt_dlp(mock_ydl_factory),
        ):
            exit_code = dl.main()

        self.assertEqual(exit_code, 0)
        called_opts = mock_ydl_factory.call_args.args[0]
        self.assertEqual(called_opts["cookiefile"], "config/cookies.txt")


if __name__ == "__main__":
    unittest.main()
