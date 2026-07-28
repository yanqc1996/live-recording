#!/usr/bin/env python3
import argparse
import glob
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}

def cli_command(cli: str) -> list[str]:
    cli = str(cli or "").strip()
    if not cli:
        return ["bypy"]
    if cli == "__python_module_bypy__":
        return [sys.executable, "-m", "bypy"]
    return shlex.split(cli)



def run_command(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def stream_command(cmd: list[str]) -> int:
    print(f"[baidupan] running: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")

    process.wait()
    return process.returncode


def ensure_remote_dir(cli: str, remote_dir: str) -> None:
    result = run_command([*cli_command(cli), "mkdir", remote_dir])
    if result.returncode == 0:
        print(f"[baidupan] ensured remote dir: {remote_dir}")
        return
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    merged = f"{stdout}\n{stderr}".lower()
    if "exists" in merged or "already" in merged or "文件已存在" in merged:
        print(f"[baidupan] remote dir already exists: {remote_dir}")
        return

    print(f"[baidupan] failed to create remote dir: {remote_dir}")
    if stdout:
        print(stdout)
    if stderr:
        print(stderr)
    raise SystemExit(result.returncode or 1)


def stable_files(pattern: str, timeout: int, stable_seconds: int = 8) -> list[Path]:
    deadline = time.time() + timeout
    last_snapshot: tuple[str, ...] = ()
    stable_since = 0.0

    while time.time() < deadline:
        files = sorted(
            p for p in (Path(path) for path in glob.glob(pattern))
            if p.is_file()
        )
        snapshot = tuple(f"{p}:{p.stat().st_size}" for p in files)

        if snapshot and snapshot == last_snapshot:
            if stable_since == 0.0:
                stable_since = time.time()
            elif time.time() - stable_since >= stable_seconds:
                return files
        else:
            last_snapshot = snapshot
            stable_since = 0.0

        time.sleep(2)

    return [
        p for p in sorted(Path(path) for path in glob.glob(pattern))
        if p.is_file()
    ]


def wait_for_single_file(path: Path, timeout: int, stable_seconds: int = 8) -> Path | None:
    deadline = time.time() + timeout
    last_size = -1
    stable_since = 0.0

    while time.time() < deadline:
        if path.exists() and path.is_file():
            size = path.stat().st_size
            if size > 0 and size == last_size:
                if stable_since == 0.0:
                    stable_since = time.time()
                elif time.time() - stable_since >= stable_seconds:
                    return path
            else:
                last_size = size
                stable_since = 0.0
        time.sleep(2)

    if path.exists() and path.is_file():
        return path
    return None

def resolve_upload_files(
    save_file_path: str,
    save_type: str,
    split_video_by_time: bool,
    converts_to_mp4: bool,
    wait_timeout: int,
) -> list[Path]:
    source = Path(save_file_path)
    source_ext = source.suffix
    converted_ext = ".mp4" if converts_to_mp4 and save_type.upper() == "TS" else source_ext

    if split_video_by_time:
        wildcard_name = source.name.replace("%03d", "*")
        prefix_name = source.name.split("%03d", maxsplit=1)[0]
        pattern = str(source.parent / f"{prefix_name}*{converted_ext}")
        files = stable_files(pattern, timeout=wait_timeout)
        if files:
            return files

        fallback_pattern = str(source.parent / wildcard_name)
        return stable_files(fallback_pattern, timeout=4)

    target = source.with_suffix(converted_ext)
    file_path = wait_for_single_file(target, timeout=wait_timeout)
    if file_path:
        return [file_path]

    if target != source:
        fallback = wait_for_single_file(source, timeout=4)
        if fallback:
            return [fallback]
    return []

def upload_file(
    cli: str,
    local_file: Path,
    remote_dir: str,
    retries: int,
    slice_size: str | None = None,
    verbose: bool = False,
) -> None:
    for attempt in range(1, retries + 1):
        cmd = cli_command(cli)
        if verbose:
            cmd.append("-v")
        if slice_size:
            cmd.extend(["-s", slice_size])
        cmd.extend(["upload", str(local_file), remote_dir])
        return_code = stream_command(cmd)
        if return_code == 0:
            print(f"[baidupan] uploaded: {local_file} -> {remote_dir}")
            return

        print(f"[baidupan] upload failed ({attempt}/{retries}): {local_file}")
        time.sleep(min(attempt * 3, 10))

    raise SystemExit(1)


def delete_local_file(local_file: Path) -> None:
    try:
        local_file.unlink()
        print(f"[baidupan] deleted local file: {local_file}")
    except FileNotFoundError:
        print(f"[baidupan] local file already missing: {local_file}")
    except Exception as exc:
        print(f"[baidupan] failed to delete local file: {local_file}")
        print(str(exc))



def main() -> int:
    parser = argparse.ArgumentParser(description="Upload recorder output files to Baidu Netdisk via bypy.")
    parser.add_argument("--remote-dir", required=True, help="Remote Baidu Netdisk directory, e.g. /apps/LiveRecorder")
    parser.add_argument("--bypy-bin", default=os.environ.get("BAIDUPAN_CLI", "__python_module_bypy__"))
    parser.add_argument("--wait-timeout", type=int, default=900, help="Seconds to wait for converted files.")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--bypy-slice-size", default=os.environ.get("BAIDUPAN_SLICE_SIZE"))
    parser.add_argument("--bypy-verbose", action="store_true")
    parser.add_argument("--record_name", required=True)
    parser.add_argument("--save_file_path", required=True)
    parser.add_argument("--save_type", required=True)
    parser.add_argument("--split_video_by_time", default="False")
    parser.add_argument("--converts_to_mp4", default="False")
    parser.add_argument("--delete-after-upload", action="store_true")
    args = parser.parse_args()

    split_video_by_time = parse_bool(args.split_video_by_time)
    converts_to_mp4 = parse_bool(args.converts_to_mp4)

    print(f"[baidupan] record_name={args.record_name}")
    print(f"[baidupan] remote_dir={args.remote_dir}")
    print(f"[baidupan] bypy_bin={args.bypy_bin}")
    if args.bypy_slice_size:
        print(f"[baidupan] bypy_slice_size={args.bypy_slice_size}")

    version_result = run_command([*cli_command(args.bypy_bin), "--help"])
    if version_result.returncode != 0:
        print("[baidupan] bypy command is unavailable. Install and authorize bypy first.")
        if version_result.stderr.strip():
            print(version_result.stderr.strip())
        return version_result.returncode or 1

    ensure_remote_dir(args.bypy_bin, args.remote_dir)
    files = resolve_upload_files(
        save_file_path=args.save_file_path,
        save_type=args.save_type,
        split_video_by_time=split_video_by_time,
        converts_to_mp4=converts_to_mp4,
        wait_timeout=args.wait_timeout,
    )

    if not files:
        print("[baidupan] no files found for upload")
        return 1

    print("[baidupan] files to upload:")
    for file_path in files:
        print(f"  - {file_path}")

    for file_path in files:
        upload_file(
            args.bypy_bin,
            file_path,
            args.remote_dir,
            retries=args.retries,
            slice_size=args.bypy_slice_size,
            verbose=args.bypy_verbose,
        )
        if args.delete_after_upload:
            delete_local_file(file_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
