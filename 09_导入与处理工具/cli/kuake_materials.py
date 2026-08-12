#!/usr/bin/env python3
"""受限的 Quark/Kuake 资料入口，下载结果先进入待导入区。"""

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "01_待导入资料"


def safe_local_path(value):
    target = (ROOT / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        target.relative_to(INBOX.resolve())
    except ValueError:
        raise SystemExit("本地下载目标必须位于 01_待导入资料 内: {}".format(target))
    return target


def run_kuake(arguments):
    try:
        completed = subprocess.run(["kuake"] + arguments, cwd=str(ROOT), check=False, text=True)
    except FileNotFoundError:
        raise SystemExit("找不到 kuake，请先安装并确保它在 PATH 中。")
    raise SystemExit(completed.returncode)


def main():
    parser = argparse.ArgumentParser(description="通过 kuake 获取法考资料")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="列出夸克云盘目录")
    listing.add_argument("remote_path", nargs="?", default="/")
    download = sub.add_parser("download", help="下载资料到待导入区")
    download.add_argument("remote_path", help="夸克云盘文件路径")
    download.add_argument("local_path", help="相对项目路径，例如 01_待导入资料/题库/file.pdf")
    args = parser.parse_args()
    if args.command == "list":
        run_kuake(["list", args.remote_path])
    if args.command == "download":
        target = safe_local_path(args.local_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        run_kuake(["download", args.remote_path, str(target)])


if __name__ == "__main__":
    main()
