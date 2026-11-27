"""Exercise local Chinese audio -> Whisper -> timestamped TXT/SRT (macOS)."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_transcription import TranscriptionManager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='local-transcription-smoke-') as folder:
        root = Path(folder)
        media = root / 'media'
        media.mkdir()
        aiff, wav = media / 'test.aiff', media / 'test.wav'
        subprocess.run(['say', '-v', 'Tingting', '-o', str(aiff),
                        '你好，这是本地录音转文字测试。今天我们测试中文识别，音频不会上传到服务器。'], check=True, timeout=30)
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', str(aiff), str(wav)], check=True, timeout=30)
        os.utime(wav, (time.time()-120, time.time()-120))
        state = root / 'state'
        state.mkdir()
        (state / 'ggml-base.bin').symlink_to(Path(args.model).resolve())
        manager = TranscriptionManager(state, lambda: media)
        try:
            job = manager.start(str(wav), 'zh')
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                current = manager.status()['jobs'][0]
                if current['state'] not in {'queued', 'running'}:
                    break
                time.sleep(.5)
            assert current['state'] == 'success', current
            result = manager.result(job['id'])
            assert result['segments'] and '-->' in result['srt'], result
            print('PASS: local Chinese transcription, timestamped text and SRT')
            print(result['text'])
        finally:
            manager.stop()


if __name__ == '__main__':
    main()
