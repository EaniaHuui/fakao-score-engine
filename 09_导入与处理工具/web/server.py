#!/usr/bin/env python3
"""法考工作台入口：python3 server.py [--host 127.0.0.1] [--port 7800] [--no-browser]"""

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakao_web import create_app


def port_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex((host, port)) != 0


def pick_port(host, wanted, attempts=20):
    """7800 被占用时自动向后尝试,避免双击启动直接失败。"""
    for candidate in range(wanted, wanted + attempts):
        if port_free(host, candidate):
            return candidate
    raise SystemExit("端口 {} 起的 {} 个端口都被占用，请手工指定：--port 端口号".format(wanted, attempts))


def open_browser_when_ready(host, port):
    """服务就绪后自动打开浏览器(给非技术用户:不需要知道网址是什么)。"""
    url = "http://{}:{}/".format("127.0.0.1" if host == "0.0.0.0" else host, port)
    deadline = time.time() + 15
    while time.time() < deadline:
        if not port_free(host, port):
            try:
                webbrowser.open(url)
            except Exception:
                pass
            return
        time.sleep(0.3)
    print("（浏览器未能自动打开，请手动访问 {}）".format(url))


def main():
    parser = argparse.ArgumentParser(description="法考提分工作台（本地）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7800)
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    port = pick_port(args.host, args.port)
    if port != args.port:
        print("端口 {} 已被占用，自动改用 {}".format(args.port, port))

    app = create_app()
    print("法考工作台已启动：http://{}:{}".format("127.0.0.1" if args.host == "0.0.0.0" else args.host, port))
    print("关闭方法：回到终端窗口按 Ctrl+C（或直接关闭该终端窗口）")
    if not args.no_browser:
        threading.Thread(target=open_browser_when_ready, args=(args.host, port), daemon=True).start()
    # 本地单用户运行，不开 debug（Flask debugger PIN 有 RCE 风险）
    try:
        app.run(host=args.host, port=port, debug=False)
    except KeyboardInterrupt:
        print("\n工作台已停止。学习数据都已保存在本地文件里，下次双击启动器即可继续。")


if __name__ == "__main__":
    main()
