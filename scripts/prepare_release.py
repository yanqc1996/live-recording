#!/usr/bin/env python3
"""Prepare release artifacts for GitHub Releases and Xianyu delivery.

This script does not upload anything. It only organizes local files so the
seller can drag them into a GitHub Release and copy the generated update.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
RELEASE = ROOT / "release"


def read_package() -> dict:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))


def safe_copy(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit(f"缺少文件：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def make_zip(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    if shutil.which("ditto"):
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(source_dir), str(zip_path)], check=True)
        return
    archive_base = zip_path.with_suffix("")
    created = shutil.make_archive(str(archive_base), "zip", source_dir.parent, source_dir.name)
    created_path = Path(created)
    if created_path != zip_path:
        if zip_path.exists():
            zip_path.unlink()
        created_path.replace(zip_path)


def github_release_url(repo: str, tag: str, filename: str) -> str:
    encoded_name = quote(filename, safe="")
    return f"https://github.com/{repo}/releases/download/{tag}/{encoded_name}"


def main() -> None:
    package = read_package()
    version = str(package.get("version") or "0.0.0")
    product_name = str(package.get("build", {}).get("productName") or "播录助手")

    parser = argparse.ArgumentParser(description="整理播录助手 GitHub Release 发版文件")
    parser.add_argument("--version", default=version, help="版本号，默认读取 package.json")
    parser.add_argument("--repo", default="", help="GitHub 仓库，例如 yanqc1996/live-recording")
    parser.add_argument("--tag", default="", help="GitHub Release tag，默认 v{version}")
    parser.add_argument("--notes", default="修复已知问题并优化稳定性。", help="更新说明，会写入 update.json")
    parser.add_argument("--title", default="", help="Release 标题，默认 播录助手 v{version}")
    parser.add_argument("--download-url", default="", help="自定义 DMG 下载地址；设置后优先于 --repo")
    parser.add_argument("--asset-prefix", default="BoluAssistant", help="GitHub Release 资产英文前缀，默认 BoluAssistant")
    parser.add_argument("--published-at", default=date.today().isoformat(), help="发布日期，默认今天")
    parser.add_argument("--include-xianyu-assets", action="store_true", help="同时把咸鱼上架素材包 zip 复制到发版目录")
    args = parser.parse_args()

    version = args.version
    tag = args.tag or f"v{version}"
    title = args.title or f"{product_name} v{version}"

    dmg_name = f"{product_name}-{version}-arm64.dmg"
    app_zip_name = f"{product_name}-{version}-arm64-mac.zip"
    delivery_dir_name = f"{product_name}-v{version}-mac-arm64-用户交付包"
    delivery_zip_name = f"{delivery_dir_name}.zip"
    asset_prefix = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(args.asset_prefix or "BoluAssistant")).strip("-") or "BoluAssistant"
    github_dmg_name = f"{asset_prefix}-{version}-arm64.dmg"
    github_app_zip_name = f"{asset_prefix}-{version}-arm64-mac.zip"
    github_delivery_zip_name = f"{asset_prefix}-v{version}-mac-arm64-delivery.zip"

    dmg = DIST / dmg_name
    app_zip = DIST / app_zip_name
    guide = ROOT / "首次启动引导.txt"
    icon_preview = ROOT / "assets" / "app-icon.png"
    delivery_dir = RELEASE / delivery_dir_name
    delivery_zip = RELEASE / delivery_zip_name
    github_assets_dir = RELEASE / "github-release" / tag

    if not dmg.exists():
        raise SystemExit(f"缺少 DMG：{dmg}\n请先执行：npm run desktop:dist")

    if delivery_dir.exists():
        shutil.rmtree(delivery_dir)
    delivery_dir.mkdir(parents=True, exist_ok=True)
    safe_copy(dmg, delivery_dir / dmg.name)
    if app_zip.exists():
        safe_copy(app_zip, delivery_dir / app_zip.name)
    safe_copy(guide, delivery_dir / guide.name)
    if icon_preview.exists():
        safe_copy(icon_preview, delivery_dir / f"{product_name}图标预览.png")
    make_zip(delivery_dir, delivery_zip)

    if github_assets_dir.exists():
        shutil.rmtree(github_assets_dir)
    github_assets_dir.mkdir(parents=True, exist_ok=True)
    safe_copy(dmg, github_assets_dir / github_dmg_name)
    if app_zip.exists():
        safe_copy(app_zip, github_assets_dir / github_app_zip_name)
    safe_copy(delivery_zip, github_assets_dir / github_delivery_zip_name)
    xianyu_zip = RELEASE / "咸鱼上架素材包.zip"
    if args.include_xianyu_assets and xianyu_zip.exists():
        safe_copy(xianyu_zip, github_assets_dir / xianyu_zip.name)

    if args.download_url:
        download_url = args.download_url
    elif args.repo:
        download_url = github_release_url(args.repo, tag, github_dmg_name)
    else:
        download_url = f"请替换为 {dmg.name} 的 GitHub Release 下载地址"

    update_manifest = {
        "version": version,
        "title": title,
        "notes": args.notes,
        "download_url": download_url,
        "published_at": args.published_at,
    }
    update_json = RELEASE / "update.json"
    update_json.write_text(json.dumps(update_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    safe_copy(update_json, github_assets_dir / "update.json")

    print("发版文件已准备完成：")
    print(f"- 用户交付包目录：{delivery_dir}")
    print(f"- 用户交付包 ZIP：{delivery_zip}")
    print(f"- GitHub Release 文件目录：{github_assets_dir}")
    print(f"- 更新 JSON：{update_json}")
    print()
    print("GitHub Release 建议上传这些文件：")
    for item in sorted(github_assets_dir.iterdir()):
        if item.is_file():
            print(f"- {item.name}")
    print()
    print("软件内更新地址可以填：")
    if args.repo:
        print(f"https://raw.githubusercontent.com/{args.repo}/main/release/update.json")
        print("或开启 GitHub Pages 后填写 Pages 中 update.json 的地址。")
    else:
        print("请先把 release/update.json 放到 GitHub / GitHub Pages / OSS 后，填写对应公网地址。")


if __name__ == "__main__":
    main()
