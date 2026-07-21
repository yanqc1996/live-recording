"""Build the self-contained Python/FFmpeg/Node runtime for this host OS."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build" / "desktop-runtime"
BUILD_VENV = ROOT / "build" / "desktop-build-venv"
RUNTIME_NAME = "LiveRecorderRuntime"


def require_binary(name: str) -> Path:
    resolved = shutil.which(name)
    if not resolved:
        raise SystemExit(f"缺少构建依赖：{name}")
    return Path(resolved).resolve()


def main() -> None:
    if os.environ.get("LIVERECORDER_CLEAN_BUILD_ENV") != "1":
        venv_python = BUILD_VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not venv_python.exists():
            subprocess.run([sys.executable, "-m", "venv", str(BUILD_VENV)], check=True)
        subprocess.run([
            str(venv_python), "-m", "pip", "install", "--disable-pip-version-check",
            "-r", str(ROOT / "requirements.txt"), "-r", str(ROOT / "requirements-build.txt")
        ], cwd=ROOT, check=True)
        environment = os.environ.copy()
        environment["LIVERECORDER_CLEAN_BUILD_ENV"] = "1"
        subprocess.run([str(venv_python), str(Path(__file__).resolve())], cwd=ROOT, env=environment, check=True)
        return

    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise SystemExit("请先执行：python3 -m pip install -r requirements-build.txt") from exc

    node = require_binary("node")
    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    if not ffmpeg.exists():
        raise SystemExit("无法取得可分发的 FFmpeg 二进制")

    shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    pyinstaller_work = Path(tempfile.mkdtemp(prefix="liverecorder-pyinstaller-"))

    separator = os.pathsep
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        RUNTIME_NAME,
        "--distpath",
        str(BUILD_ROOT),
        "--workpath",
        str(pyinstaller_work),
        "--specpath",
        str(pyinstaller_work),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{ROOT / 'desktop'}{separator}desktop",
        "--add-data",
        f"{ROOT / 'src' / 'javascript'}{separator}src/javascript",
        "--add-data",
        f"{ROOT / 'douyin_static'}{separator}douyin_static",
        "--add-data",
        f"{ROOT / 'i18n'}{separator}i18n",
        "--add-data",
        f"{ROOT / 'scripts' / 'upload_to_baidu_netdisk.py'}{separator}scripts",
        "--collect-all",
        "bypy",
        "--collect-all",
        "gmssl",
        "--hidden-import",
        "douyin_static.work_abogus",
    ]
    jsrsasign = ROOT / "node_modules" / "jsrsasign"
    if jsrsasign.exists():
        command.extend(["--add-data", f"{jsrsasign}{separator}node_modules/jsrsasign"])
    command.append(str(ROOT / "packaging" / "runtime_entry.py"))
    pyinstaller_environment = os.environ.copy()
    pyinstaller_environment["PYINSTALLER_CONFIG_DIR"] = str(pyinstaller_work / "config")
    subprocess.run(command, cwd=ROOT, env=pyinstaller_environment, check=True)

    bin_dir = BUILD_ROOT / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    node_name = "node.exe" if os.name == "nt" else "node"
    ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    shutil.copy2(node, bin_dir / node_name)
    shutil.copy2(ffmpeg, bin_dir / ffmpeg_name)
    if os.name != "nt":
        (bin_dir / node_name).chmod(0o755)
        (bin_dir / ffmpeg_name).chmod(0o755)

    runtime = BUILD_ROOT / RUNTIME_NAME / (f"{RUNTIME_NAME}.exe" if os.name == "nt" else RUNTIME_NAME)
    if not runtime.exists():
        raise SystemExit(f"运行时构建失败：{runtime} 不存在")
    print(f"桌面运行时已生成：{runtime}")
    print(f"内置 Node：{bin_dir / node_name}")
    print(f"内置 FFmpeg：{bin_dir / ffmpeg_name}")


if __name__ == "__main__":
    main()
