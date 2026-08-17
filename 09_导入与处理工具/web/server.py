#!/usr/bin/env python3
"""法考工作台入口：python3 server.py --host 127.0.0.1 --port 7800"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakao_web import create_app


def main():
    parser = argparse.ArgumentParser(description="法考提分工作台（本地）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7800)
    args = parser.parse_args()
    app = create_app()
    print("法考工作台已启动：http://{}:{}".format(args.host, args.port))
    # 本地单用户运行，不开 debug（Flask debugger PIN 有 RCE 风险）
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
