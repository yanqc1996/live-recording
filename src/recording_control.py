"""In-memory engine controls. Credentials travel over a private stdin pipe only."""
import json
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import re


def room_key(url):
    parsed = urlparse(url)
    return (parse_qs(parsed.query).get('lr_sec_user_id') or [url.split('?')[0]])[0]


def recording_cookie(url, current_cookie, fallback_cookie):
    """Select credentials per room without changing the global login session."""
    query = parse_qs(urlparse(url).query)
    if (query.get('lr_anonymous_recording') or [''])[0] == '1':
        return ''
    return current_cookie if current_cookie is not None else fallback_cookie


class EngineControl:
    def __init__(self):
        self.lock = threading.RLock()
        self.events = {}
        self.attempts = {}
        self.failures = {}
        self.cookie = None
        self.active = set()
        self.latest_urls = {}

    def event(self, url):
        with self.lock:
            return self.events.setdefault(room_key(url), threading.Event())

    def claim(self, url):
        with self.lock:
            key = room_key(url)
            if key in self.active:
                return False
            self.active.add(key)
            self.event(url)
            return True

    def release(self, url):
        with self.lock:
            self.active.discard(room_key(url))

    def consume(self, command):
        with self.lock:
            if command.get('action') == 'auth':
                self.cookie = str(command.get('cookie', ''))
                for event in self.events.values():
                    event.set()
            elif command.get('action') == 'retry' and command.get('url'):
                url = str(command['url'])
                key = room_key(url)
                # A radio room's room_id identifies one live session and can
                # rotate while its sec_user_id remains stable.  Keep the newest
                # desktop-resolved identity so an existing worker does not wake
                # up and retry its stale startup URL forever.
                self.latest_urls[key] = url
                self.event(url).set()

    def current_url(self, url):
        with self.lock:
            return self.latest_urls.get(room_key(url), url)

    def listen(self, pipe):
        for line in pipe:
            try:
                self.consume(json.loads(line))
            except (ValueError, TypeError, AttributeError):
                continue

    def failed(self, url):
        with self.lock:
            key = room_key(url)
            self.attempts[key] = self.attempts.get(key, 0) + 1
            self.failures[key] = self.failures.get(key, 0) + 1
            self.event(url).set()

    def healthy(self, url):
        with self.lock:
            self.failures[room_key(url)] = 0

    def retry_delay(self, url):
        with self.lock:
            return min(60, 2 ** min(6, self.failures.get(room_key(url), 0) + 1))

    def source(self, url, info):
        candidates = list(dict.fromkeys(value for value in (
            info.get('source_candidates') or [info.get('flv_url'), info.get('m3u8_url'), info.get('record_url')]
        ) if value))
        candidates = [value for value in candidates if not (
            (value == info.get('flv_url') or '.flv' in value.split('?')[0])
            and (parse_qs(urlparse(value).query).get('codec') or [''])[0] == 'h265')]
        if not candidates:
            return None
        with self.lock:
            return candidates[self.attempts.get(room_key(url), 0) % len(candidates)]

    def prefer_page(self, url):
        with self.lock:
            return self.attempts.get(room_key(url), 0) % 3 == 2


class FileProgress:
    """Missing files count as stalled too; supports FFmpeg numbered segments."""
    def __init__(self, path, timeout=90):
        self.path = Path(path)
        self.timeout = timeout
        self.size = 0
        self.changed = time.monotonic()
        self.growth_since = None
        self.healthy = False

    def stalled(self):
        try:
            pattern = re.sub(r'%0?\d*d', '*', self.path.name)
            files = self.path.parent.glob(pattern) if '%' in self.path.name else [self.path]
            size = sum(p.stat().st_size for p in files if p.is_file())
        except OSError:
            size = self.size
        now = time.monotonic()
        if size > self.size:
            if self.growth_since is None or now - self.changed > 15:
                self.growth_since = now
            self.healthy = now - self.growth_since >= 60
            self.size, self.changed = size, now
        else:
            self.healthy = False
            if size < self.size or now - self.changed > 15:
                self.growth_since = None
            self.size = size
        return now - self.changed >= self.timeout


def stop_capture(process):
    """Give FFmpeg time to finalize before bounded escalation."""
    import subprocess
    try:
        if process.stdin:
            process.stdin.write(b'q\n')
            process.stdin.flush()
        process.wait(timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
