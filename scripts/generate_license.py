#!/usr/bin/env python3
"""Generate a LiveRecorder lifetime activation code for a customer device.

Usage:
  python3 scripts/generate_license.py --device XXXX-XXXX-XXXX-XXXX --customer "张三" --order "闲鱼订单号"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop_license import make_license_code, normalize_device_id  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 LiveRecorder 买断授权码")
    parser.add_argument("--device", required=True, help="用户软件里显示的设备码")
    parser.add_argument("--customer", default="", help="客户备注，可填闲鱼昵称")
    parser.add_argument("--order", default="", help="订单号或售后备注")
    args = parser.parse_args()

    device_id = normalize_device_id(args.device)
    code = make_license_code(device_id, customer=args.customer, order_id=args.order)
    print("设备码：", device_id)
    print("授权码：")
    print(code)


if __name__ == "__main__":
    main()
