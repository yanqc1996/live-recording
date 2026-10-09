#!/usr/bin/env python3
"""Create a device-bound activation record for an owner/test build."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop_license import LicenseManager, make_license_code  # noqa: E402


def prepare_owner_license(output: Path | None = None) -> tuple[Path, str]:
    target = output or ROOT / "build" / "owner-license" / "license.json"
    manager = LicenseManager(target)
    code = make_license_code(
        manager.device_id,
        customer="Owner Build",
        order_id="owner-device-build",
    )
    manager.activate(code)
    return target, manager.device_id


def main() -> None:
    target, device_id = prepare_owner_license()
    print(f"Owner 预激活授权已生成：{target}")
    print(f"绑定设备码：{device_id}")
    print("此安装包只会在当前打包设备上自动激活。")


if __name__ == "__main__":
    main()
