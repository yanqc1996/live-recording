import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.upload_to_baidu_netdisk import resolve_upload_files, stream_command


class BaiduPanUploadScriptTest(unittest.TestCase):
    def test_base_ts_path_finds_converted_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "主播_2026-10-11_01-37-23_000.mp4"
            second = root / "主播_2026-10-11_01-37-23_001.mp4"
            unrelated = root / "主播_2026-10-11_02-00-00_000.mp4"
            for path in (first, second, unrelated):
                path.write_bytes(b"video")

            files = resolve_upload_files(
                str(root / "主播_2026-10-11_01-37-23.ts"),
                "TS",
                split_video_by_time=True,
                converts_to_mp4=True,
                wait_timeout=0,
            )

            self.assertEqual(files, [first, second])

    def test_percent_template_still_finds_converted_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment = root / "主播_000.mp4"
            segment.write_bytes(b"video")

            files = resolve_upload_files(
                str(root / "主播_%03d.ts"),
                "TS",
                split_video_by_time=True,
                converts_to_mp4=True,
                wait_timeout=0,
            )

            self.assertEqual(files, [segment])

    @patch("scripts.upload_to_baidu_netdisk.subprocess.Popen")
    def test_progress_output_is_forwarded_without_buffering(self, popen):
        process = MagicMock()
        process.stdout = ["\r[=====_____] 50% (5.0MB/10.0MB)"]
        process.returncode = 0
        popen.return_value = process

        with patch("builtins.print") as output:
            result = stream_command(["bypy", "upload", "file", "/remote"])

        self.assertEqual(result, 0)
        self.assertIn(
            unittest.mock.call("\r[=====_____] 50% (5.0MB/10.0MB)", end="", flush=True),
            output.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
