import unittest
from unittest.mock import MagicMock, patch

from scripts.upload_to_baidu_netdisk import stream_command


class BaiduPanUploadScriptTest(unittest.TestCase):
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
