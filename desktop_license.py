"""Local buyout license management for the desktop app.

This is intentionally lightweight: it is meant to discourage casual sharing
without introducing a payment server for the first sellable build.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


PRODUCT_ID = "LiveRecorder"
LICENSE_VERSION = 1

# Keep this stable once real customers exist. If it changes, old activation codes
# will no longer validate. This is not a high-security secret because it ships in
# the local app, but it is enough for first-pass buyout delivery.
LICENSE_SIGNING_SECRET = b"LiveRecorder.Local.Buyout.2026.v1::change-before-public-sale"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def normalize_license_code(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip()


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict[str, Any]) -> str:
    return _b64url_encode(hmac.new(LICENSE_SIGNING_SECRET, _canonical_payload(payload), hashlib.sha256).digest())


def make_license_code(device_id: str, customer: str = "", order_id: str = "", issued_at: int | None = None) -> str:
    payload = {
        "v": LICENSE_VERSION,
        "product": PRODUCT_ID,
        "type": "lifetime",
        "device_id": normalize_device_id(device_id),
        "customer": customer.strip(),
        "order_id": order_id.strip(),
        "issued_at": int(issued_at or time.time()),
    }
    token = _b64url_encode(_canonical_payload(payload))
    signature = sign_payload(payload)
    return f"LR1-{token}.{signature}"


def parse_license_code(code: str) -> tuple[dict[str, Any], str]:
    code = normalize_license_code(code)
    if code.startswith("LR1-"):
        code = code[4:]
    if "." not in code:
        raise ValueError("授权码格式不正确")
    payload_token, signature = code.split(".", 1)
    try:
        payload = json.loads(_b64url_decode(payload_token))
    except Exception as exc:
        raise ValueError("授权码内容无法解析") from exc
    if not isinstance(payload, dict):
        raise ValueError("授权码内容无效")
    expected = sign_payload(payload)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("授权码签名无效")
    return payload, signature


def normalize_device_id(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    if not compact:
        raise ValueError("设备码不能为空")
    return "-".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def legacy_machine_material() -> str:
    """The v1 fingerprint kept for validating already-issued licenses."""
    parts = [platform.system(), platform.machine(), platform.node(), str(uuid.getnode())]
    if sys_uuid := _mac_hardware_uuid():
        parts.append(sys_uuid)
    return "|".join(part for part in parts if part)


def _mac_hardware_uuid() -> str:
    if sys.platform != "darwin":  # type: ignore[name-defined]
        return ""
    try:
        output = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        return ""
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output)
    return match.group(1) if match else ""


def _windows_machine_guid() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        access = winreg.KEY_READ
        if hasattr(winreg, "KEY_WOW64_64KEY"):
            access |= winreg.KEY_WOW64_64KEY
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            access,
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip()
    except (OSError, ImportError):
        return ""


def _linux_machine_id() -> str:
    if not sys.platform.startswith("linux"):
        return ""
    for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def stable_machine_material() -> str:
    """Return a fingerprint source that survives app upgrades and renames."""
    if hardware_uuid := _mac_hardware_uuid():
        return f"mac:{hardware_uuid.upper()}"
    if machine_guid := _windows_machine_guid():
        return f"windows:{machine_guid.upper()}"
    if machine_id := _linux_machine_id():
        return f"linux:{machine_id.upper()}"
    # Last-resort fallback excludes the user-editable hostname.
    return f"fallback:{platform.system()}|{platform.machine()}|{uuid.getnode()}"


def machine_material() -> str:
    """Backward-compatible alias returning the stable v2 material."""
    return stable_machine_material()


def _device_id_from_material(material: str) -> str:
    digest = hashlib.sha256(material.encode("utf-8", "ignore")).hexdigest().upper()
    return "-".join(digest[i : i + 4] for i in range(0, 16, 4))


class LicenseManager:
    def __init__(self, path: Path):
        self.path = path
        self.device_id = _device_id_from_material(stable_machine_material())
        self.legacy_device_id = _device_id_from_material(legacy_machine_material())
        self.accepted_device_ids = {self.device_id, self.legacy_device_id}

    def _device_id(self) -> str:
        return self.device_id

    def _matches_device(self, value: str) -> bool:
        return normalize_device_id(value) in self.accepted_device_ids

    def _load_record(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_record(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def status(self) -> dict[str, Any]:
        record = self._load_record()
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        active = False
        message = "未激活"
        if record.get("code"):
            try:
                parsed, _signature = parse_license_code(str(record.get("code") or ""))
                if parsed.get("product") != PRODUCT_ID:
                    raise ValueError("授权码不属于当前产品")
                if not self._matches_device(str(parsed.get("device_id") or "")):
                    raise ValueError("授权码绑定的设备不匹配")
                if parsed.get("type") != "lifetime":
                    raise ValueError("授权类型不支持")
                active = True
                payload = parsed
                message = "买断授权已激活"
            except Exception as exc:
                message = str(exc)
        return {
            "active": active,
            "message": message,
            "device_id": self.device_id,
            "device_id_version": 2,
            "type": payload.get("type", ""),
            "customer": payload.get("customer", ""),
            "order_id": payload.get("order_id", ""),
            "issued_at": payload.get("issued_at", 0),
        }

    def activate(self, code: str) -> dict[str, Any]:
        payload, _signature = parse_license_code(code)
        if payload.get("product") != PRODUCT_ID:
            raise ValueError("授权码不属于当前产品")
        if payload.get("v") != LICENSE_VERSION:
            raise ValueError("授权码版本不支持")
        if payload.get("type") != "lifetime":
            raise ValueError("授权类型不支持")
        license_device = normalize_device_id(str(payload.get("device_id") or ""))
        if license_device not in self.accepted_device_ids:
            raise ValueError(f"授权码绑定设备不匹配：当前设备码 {self.device_id}")
        self._save_record({"code": normalize_license_code(code), "payload": payload, "activated_at": int(time.time())})
        return self.status()

    def deactivate(self) -> dict[str, Any]:
        if self.path.exists():
            self.path.unlink()
        return self.status()

    def assert_active(self) -> None:
        if not self.status().get("active"):
            raise PermissionError("请先激活软件授权")
