"""Single frozen entry point for both the local API and recorder engine."""

from __future__ import annotations

import os
import multiprocessing
import runpy
import sys
from pathlib import Path


def run() -> None:
    multiprocessing.freeze_support()
    if len(sys.argv) >= 3 and sys.argv[1] == "-m" and sys.argv[2] == "bypy":
        sys.argv = [sys.argv[0], *sys.argv[3:]]
        runpy.run_module("bypy", run_name="__main__")
        return
    if "--upload-to-baidupan" in sys.argv:
        flag_index = sys.argv.index("--upload-to-baidupan")
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        script = bundle_root / "scripts" / "upload_to_baidu_netdisk.py"
        sys.argv = [str(script), *sys.argv[flag_index + 1:]]
        runpy.run_path(str(script), run_name="__main__")
        return
    if "--engine" in sys.argv:
        data_root = Path(os.environ.get("LIVERECORDER_DATA_ROOT", Path.cwd())).resolve()
        # Legacy recorder modules derive writable config/log paths from argv[0].
        # Point them at user data rather than the read-only application bundle.
        sys.argv = [str(data_root / "LiveRecorderEngine")]
        try:
            import main  # noqa: F401 - importing starts the legacy recorder loop
        except KeyboardInterrupt:
            return
    else:
        from desktop_app import main

        main()


if __name__ == "__main__":
    run()
