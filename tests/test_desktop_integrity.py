import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_integrity import MediaIntegrityStore, inspect_media_file


class MediaIntegrityTest(unittest.TestCase):
    def test_zero_byte_file_fails_without_running_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.mp4"
            path.touch()
            self.assertEqual("failed", inspect_media_file(path, ffmpeg="/fake/ffmpeg")["status"])

    def test_healthy_audio_video_is_detected_and_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "recording.mp4"
            path.write_bytes(b"video")
            output = "Duration: 00:02:03.50\nStream #0:0: Video: h264\nStream #0:1: Audio: aac"
            result = type("Result", (), {"returncode": 0, "stdout": "", "stderr": output})()
            store = MediaIntegrityStore(root / "integrity.json")
            with patch("desktop_integrity.subprocess.run", return_value=result) as run:
                first = store.inspect(str(path)); second = store.inspect(str(path))
            self.assertEqual("healthy", first["status"])
            self.assertAlmostEqual(123.5, first["duration_seconds"])
            self.assertEqual(first, second)
            run.assert_called_once()

    def test_video_without_audio_is_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silent.mp4"
            path.write_bytes(b"video")
            result = type("Result", (), {"returncode": 0, "stdout": "", "stderr": "Stream #0:0: Video: h264"})()
            with patch("desktop_integrity.subprocess.run", return_value=result):
                report = inspect_media_file(path, ffmpeg="/fake/ffmpeg")
            self.assertEqual("warning", report["status"])


if __name__ == "__main__": unittest.main()
