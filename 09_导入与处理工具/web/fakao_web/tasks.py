"""竹马导入后台任务：模块级单例，同一时刻只允许一个任务。

竹马脚本翻页有随机 sleep（1.5-300s），导出可达数分钟，
因此不设超时；取消 = terminate 子进程。
"""

import subprocess
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

from . import bridge

ZHEMA_SCRIPT = Path(bridge.fakao_cli.__file__).with_name("竹马全自动导出神器.py")

_state = {
    "state": "idle",  # idle | running | done | error
    "action": "",
    "started_at": "",
    "finished_at": "",
    "exported": False,
    "log_tail": "",
    "error": "",
    "returncode": None,
}
_guard = threading.Lock()
_proc = {"popen": None}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def status():
    with _guard:
        snap = dict(_state)
    if snap["state"] == "running" and _proc["popen"] is not None:
        # 顺带收割已退出的子进程，读取剩余输出
        rc = _proc["popen"].poll()
        if rc is not None:
            _finish(rc)
            snap = dict(_state)
    snap["has_session"] = bridge.fakao_cli.load_json(
        bridge.fakao_cli.ROOT / "00_系统与用户" / "zhuma_session.json", None) is not None
    return snap


def _finish(returncode):
    p = _proc["popen"]
    try:
        stdout, stderr = p.communicate(timeout=5)
    except Exception:
        stdout, stderr = "", ""
    _proc["popen"] = None
    exported = "错题导出完成" in (stdout or "")
    _state.update({
        "state": "error" if returncode else ("done" if exported else "done"),
        "finished_at": _now(),
        "exported": exported,
        "returncode": returncode,
        "log_tail": ((stdout or "") + (("\n" + stderr) if stderr else ""))[-2000:],
        "error": "" if returncode == 0 else "导入脚本退出码 {}，详见日志".format(returncode),
    })
    if exported:
        # 与 CLI 行为一致：导出成功后串错误分析与今日任务
        try:
            with bridge.LOCK:
                bridge.fakao_cli.cmd_error_analysis(Namespace())
                bridge.fakao_cli.cmd_today(Namespace(limit=8))
            bridge.invalidate_cache()
        except Exception as exc:  # 分析失败不影响导入结果
            _state["log_tail"] += "\n(自动分析失败: {})".format(exc)


def start(action, chrome_path=None):
    """启动任务；已有任务在运行时拒绝。open/close 秒级，也统一走此通道。"""
    with _guard:
        if _state["state"] == "running":
            return {"ok": False, "error": "已有导入任务在运行，请等待完成或取消。"}
        _state.update({
            "state": "running", "action": action, "started_at": _now(),
            "finished_at": "", "exported": False, "log_tail": "", "error": "", "returncode": None,
        })
    command = [sys.executable, str(ZHEMA_SCRIPT), action]
    if chrome_path:
        command.extend(["--chrome-path", chrome_path])
    try:
        _proc["popen"] = subprocess.Popen(
            command, cwd=str(bridge.fakao_cli.ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except Exception as exc:
        _state.update({"state": "error", "error": str(exc), "finished_at": _now()})
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


def cancel():
    with _guard:
        if _state["state"] != "running" or _proc["popen"] is None:
            return {"ok": False, "error": "没有运行中的任务。"}
        _proc["popen"].terminate()
    return {"ok": True}


def reset():
    """任务结束后允许清屏重来。"""
    with _guard:
        if _state["state"] == "running":
            return {"ok": False, "error": "任务仍在运行。"}
        _state.update({"state": "idle", "action": "", "exported": False, "log_tail": "", "error": ""})
    return {"ok": True}
