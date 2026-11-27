"""Offline, single-worker transcription using whisper.cpp; no media leaves this Mac."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import requests

MODEL_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin'
MODEL_SHA256 = '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe'
MODEL_SIZE = 147951465
MEDIA_SUFFIXES = {'.ts', '.mp4', '.mkv', '.flv', '.mov', '.webm', '.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'}


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def stamp(seconds: float, separator=',') -> str:
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}{separator}{ms:03}'


def normalize_segments(data: dict, offset: float, duration: float) -> list[dict]:
    segments = []
    for item in data.get('transcription', []):
        text = str(item.get('text') or '').strip()
        start = max(0, float(item['offsets']['from']) / 1000)
        end = min(duration, float(item['offsets']['to']) / 1000)
        if text and end > start:
            segments.append({'start': round(start + offset, 3), 'end': round(end + offset, 3), 'text': text})
    return segments


class TranscriptionManager:
    def __init__(self, root: Path, output_root: Callable[[], Path], active_paths: Callable[[], list[str]] = lambda: []):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.output_root = output_root
        self.active_paths = active_paths
        self.model = root / 'ggml-base.bin'
        self.path = root / 'jobs.json'
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.cancelled = set()
        self.download = {'state': 'idle', 'progress': 0, 'error': ''}
        try:
            self.jobs = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self.jobs, list) or any(not isinstance(j, dict) or not re.fullmatch(r'[a-f0-9]{24}', str(j.get('id', ''))) for j in self.jobs):
                raise ValueError('invalid task history')
        except (OSError, ValueError):
            if self.path.exists():
                self.path.replace(root / f'jobs.invalid-{time.time_ns()}.json')
            self.jobs = []
        for job in self.jobs:
            if job['state'] in {'queued', 'running'}:
                job.update(state='failed', error='上次退出时转写未完成，可点击重试')
        self._save()
        self.worker = threading.Thread(target=self._run, name='local-transcription', daemon=True)
        self.worker.start()

    def _save(self):
        atomic_json(self.path, self.jobs)

    @staticmethod
    def executable():
        for value in [shutil.which('whisper-cli'), '/opt/homebrew/bin/whisper-cli', '/usr/local/bin/whisper-cli']:
            if value and Path(value).is_file():
                return str(value)
        return ''

    def status(self):
        with self.lock:
            return {'engine_ready': bool(self.executable()), 'model_ready': self.model.is_file() and self.model.stat().st_size == MODEL_SIZE,
                    'model': 'Whisper base · 多语言', 'download': dict(self.download),
                    'jobs': [dict(j) for j in reversed(self.jobs)]}

    def install_model(self):
        with self.lock:
            if self.download['state'] == 'downloading' or self.status()['model_ready']:
                return self.status()
            if shutil.disk_usage(self.root).free < MODEL_SIZE + 100 * 1024 ** 2:
                raise RuntimeError('磁盘空间不足，无法下载模型')
            self.download = {'state': 'downloading', 'progress': 0, 'error': ''}
        threading.Thread(target=self._download, daemon=True, name='whisper-model-download').start()
        return self.status()

    def _download(self):
        part = self.model.with_suffix('.part')
        try:
            digest, received = hashlib.sha256(), 0
            with requests.get(MODEL_URL, stream=True, timeout=(15, 30)) as response:
                response.raise_for_status()
                with part.open('wb') as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if self.closed.is_set():
                            raise RuntimeError('模型下载已停止')
                        received += len(chunk)
                        if received > MODEL_SIZE:
                            raise RuntimeError('模型文件大小异常')
                        handle.write(chunk)
                        digest.update(chunk)
                        with self.lock:
                            self.download['progress'] = round(received * 100 / MODEL_SIZE)
            if received != MODEL_SIZE or digest.hexdigest() != MODEL_SHA256:
                raise RuntimeError('模型校验失败，请重新下载')
            part.replace(self.model)
            with self.lock:
                self.download.update(state='ready', progress=100)
        except Exception as exc:
            part.unlink(missing_ok=True)
            with self.lock:
                self.download.update(state='failed', error=str(exc))

    def validate(self, value):
        path = Path(value).resolve()
        if self.output_root().resolve() not in path.parents or not path.is_file() or path.suffix.lower() not in MEDIA_SUFFIXES:
            raise ValueError('只能转写当前媒体目录中的音视频文件')
        for active in self.active_paths():
            target = Path(active).resolve()
            pattern = re.sub(r'%0?\d*d', '*', target.name)
            if path.parent == target.parent and path.match(pattern):
                raise ValueError('该文件仍在录制，请结束录制后转写')
        if time.time() - path.stat().st_mtime < 60:
            raise ValueError('文件刚刚更新，请等待 60 秒后转写')
        return path

    def start(self, value: str, language='zh', creator=''):
        if language not in {'zh', 'en', 'auto'}:
            raise ValueError('不支持的转写语言')
        path = self.validate(value)
        if not self.executable():
            raise RuntimeError('未安装本地识别引擎，请安装 whisper.cpp（brew install whisper-cpp）')
        if not self.status()['model_ready']:
            raise RuntimeError('请先下载本地识别模型')
        stat = path.stat()
        identity = hashlib.sha256(f'{path}|{stat.st_size}|{stat.st_mtime_ns}|{language}|base'.encode()).hexdigest()[:24]
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == identity), None)
            if job and job['state'] in {'queued', 'running', 'success'}:
                if creator:
                    job['creator'] = creator
                    self._save()
                return dict(job)
            if not job:
                job = {'id': identity, 'path': str(path), 'name': path.name, 'language': language,
                       'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'created_at': time.time()}
                self.jobs.append(job)
            date_match = re.search(r'(20\d{2}-\d{2}-\d{2})', path.name)
            job.update(creator=creator or job.get('creator') or path.parent.name,
                       recorded_date=date_match[1] if date_match else time.strftime('%Y-%m-%d', time.localtime(stat.st_mtime)),
                       date_source='filename' if date_match else 'file_mtime')
            self.cancelled.discard(identity)
            job.update(state='queued', progress=0, error='', phase='等待转写')
            self._save()
            result = dict(job)
        self.wake.set()
        return result

    def archive_before_upload(self, paths, creator, cancelled):
        for path in paths:
            while time.time() - path.stat().st_mtime < 60:
                if cancelled() or self.closed.wait(1):
                    raise InterruptedError('上传前转写已停止，视频仍保留')
            job = self.start(str(path), creator=creator)
            while True:
                if cancelled() or self.closed.is_set():
                    raise InterruptedError('上传已停止，转写记录独立保留')
                with self.lock:
                    current = dict(next(j for j in self.jobs if j['id'] == job['id']))
                if current['state'] == 'success':
                    self.result(job['id'])  # Verify durable result before allowing deletion.
                    break
                if current['state'] in {'failed', 'cancelled'}:
                    raise RuntimeError('上传前转写未完成：' + current.get('error', current['state']))
                self.closed.wait(.5)

    def search(self, creator='', date='', query=''):
        with self.lock:
            jobs = [dict(j) for j in reversed(self.jobs)]
        found = []
        for job in jobs:
            if creator.casefold() not in job.get('creator', '').casefold() or (date and job.get('recorded_date') != date):
                continue
            segments = []
            if query:
                if job['state'] != 'success':
                    continue
                try:
                    segments = [s for s in self.result(job['id'])['segments'] if query.casefold() in s['text'].casefold()]
                except (OSError, ValueError):
                    continue
                if not segments:
                    continue
            found.append({**job, 'source_exists': Path(job['path']).is_file(), 'matches': segments[:5]})
        return {'jobs': found}

    def cancel(self, identity):
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == identity), None)
            if not job:
                raise ValueError('转写任务不存在')
            if job['state'] in {'queued', 'running'}:
                self.cancelled.add(identity)
                if job['state'] == 'queued':
                    job.update(state='cancelled', phase='已取消')
                    self._save()
            return dict(job)

    def result(self, identity):
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == identity), None)
            if not job or job['state'] != 'success':
                raise ValueError('转写尚未完成')
        return json.loads((self.root / (identity + '.json')).read_text(encoding='utf-8'))

    def _check_cancel(self, job):
        if self.closed.is_set() or job['id'] in self.cancelled:
            raise InterruptedError('转写已取消')

    def _command(self, job, command, timeout=3600, allow_failure=False):
        self._check_cancel(job)
        # Bound log memory, avoid stdout pipe deadlocks, and always reap the child.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    self._check_cancel(job)
                    if time.monotonic() > deadline:
                        raise RuntimeError('本地处理超时，可重试')
                    self.closed.wait(.2)
                output.seek(0, 2)
                output.seek(max(0, output.tell() - 16000))
                message = output.read().decode('utf-8', errors='replace')
                if process.returncode and not allow_failure:
                    raise RuntimeError('本地音频处理失败：' + message[-1200:])
                return message
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)

    def _update(self, job, **values):
        with self.lock:
            job.update(values)
            self._save()

    def _transcribe(self, job):
        path = self.validate(job['path'])
        stat = path.stat()
        if stat.st_size != job['size'] or stat.st_mtime_ns != job['mtime_ns']:
            raise RuntimeError('源文件已经变化，请重新发起转写')
        if shutil.disk_usage(self.root).free < 100 * 1024 ** 2:
            raise RuntimeError('磁盘可用空间不足 100 MiB，请释放空间后重试')
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            raise RuntimeError('未找到 FFmpeg')
        output = self._command(job, [ffmpeg, '-nostdin', '-hide_banner', '-i', str(path)], timeout=30, allow_failure=True)
        match = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', output)
        if not match or not re.search(r'Audio:', output):
            raise RuntimeError('未找到有效音轨或时长，无法转写')
        duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        if duration <= 0:
            raise RuntimeError('音轨时长为零')
        segments = []
        with tempfile.TemporaryDirectory(prefix='transcription-', dir=self.root) as folder:
            wav, result = Path(folder) / 'chunk.wav', Path(folder) / 'chunk'
            for index in range(math.ceil(duration / 300)):
                self._update(job, phase=f'处理第 {index + 1}/{math.ceil(duration / 300)} 段', progress=round(index * 300 / duration * 100))
                offset = index * 300
                length = min(300, duration - offset)
                self._command(job, [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(offset),
                    '-i', str(path), '-t', str(length), '-map', '0:a:0', '-vn', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', '-threads', '2', str(wav)])
                command = [self.executable(), '-m', str(self.model), '-f', str(wav), '-l', job['language'],
                           '-t', '2', '-ng', '-oj', '-of', str(result)]
                if os.name == 'posix':
                    command = ['/usr/bin/nice', '-n', '10', *command]
                self._command(job, command)
                data = json.loads(result.with_suffix('.json').read_text(encoding='utf-8'))
                segments.extend(normalize_segments(data, offset, length))
        self._check_cancel(job)
        if path.stat().st_size != job['size'] or path.stat().st_mtime_ns != job['mtime_ns']:
            raise RuntimeError('转写过程中源文件发生变化，请重新转写')
        text = '\n'.join(f"[{stamp(s['start'], '.')}] {s['text']}" for s in segments)
        srt = '\n\n'.join(f"{i + 1}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}" for i, s in enumerate(segments))
        atomic_json(self.root / (job['id'] + '.json'), {'segments': segments, 'text': text, 'srt': srt, 'duration': duration})

    def _run(self):
        while not self.closed.is_set():
            with self.lock:
                job = next((j for j in self.jobs if j['state'] == 'queued'), None)
                if job:
                    self._update(job, state='running', phase='读取音轨')
            if not job:
                self.wake.wait(1)
                self.wake.clear()
                continue
            try:
                self._transcribe(job)
                with self.lock:
                    self._check_cancel(job)
                    self._update(job, state='success', progress=100, phase='转写完成')
            except InterruptedError:
                self._update(job, state='cancelled', phase='已取消')
            except Exception as exc:
                self._update(job, state='failed', error=str(exc), phase='转写失败')

    def stop(self):
        self.closed.set()
        self.wake.set()
        self.worker.join(timeout=8)
