"""训练会话状态：落盘到 05_训练记录/训练会话状态.json，支持中断续做。"""

import threading
from datetime import date, datetime

from . import bridge

SESSION_FILE = bridge.fakao_cli.RECORD_DIR / "训练会话状态.json"

# 会话读写也走 bridge.LOCK，与作答记录写入串行化
LOCK = bridge.LOCK


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _today():
    return date.today().isoformat()


def load_session():
    return bridge.fakao_cli.load_json(SESSION_FILE, None)


def save_session(session):
    with LOCK:
        bridge.fakao_cli.write_json(SESSION_FILE, session)


def current_question_id(session):
    if session["index"] >= len(session["queue"]):
        return None
    return session["queue"][session["index"]]


def start(source="today", subject="", limit=8):
    """建立新会话。today=到期复测;wrong=全部导入错题;subject=按科目。"""
    questions = bridge.cached_questions()
    today = _today()
    if source == "today":
        picked = [q for q in questions if q.get("next_review") and q["next_review"] <= today]
    elif source == "wrong":
        picked = [q for q in questions if q.get("is_imported_mistake")]
    elif source == "subject":
        picked = [q for q in questions if subject and q.get("subject") == subject]
    else:
        picked = []
    picked = picked[:max(1, min(20, limit))]
    if not picked:
        return {"ok": False, "error": "没有可训练的题目。请先导入错题或等待复测到期。"}
    session = {
        "version": 1,
        "date": today,
        "started_at": _now(),
        "updated_at": _now(),
        "source": source,
        "subject": subject,
        "queue": [q["id"] for q in picked],
        "index": 0,
        "current": {"question_id": picked[0]["id"], "shown_at": _now()},
        "pending_answer": None,
        "completed": [],
        "status": "in_progress",
    }
    save_session(session)
    return {"ok": True, "total": len(session["queue"])}


def resume_or_prompt():
    """返回可恢复的会话,或 None。"""
    session = load_session()
    if not session or session.get("status") != "in_progress":
        return None
    if session.get("date") != _today():
        return None  # 隔天旧会话提示归档,不自动恢复
    return session


def advance(session, entry):
    """登记完成并推进到下一题;返回更新后的 session 与是否结束。"""
    session["completed"].append(entry)
    session["index"] += 1
    session["pending_answer"] = None
    if session["index"] >= len(session["queue"]):
        session["status"] = "finished"
        session["current"] = None
    else:
        next_id = session["queue"][session["index"]]
        session["current"] = {"question_id": next_id, "shown_at": _now()}
    session["updated_at"] = _now()
    save_session(session)
    return session


def skip(session):
    """当前题移到队尾。"""
    qid = current_question_id(session)
    if qid is None:
        return session
    session["queue"].append(session["queue"].pop(session["index"]))
    session["current"] = {"question_id": current_question_id(session), "shown_at": _now()}
    session["pending_answer"] = None
    session["updated_at"] = _now()
    save_session(session)
    return session


def abort(session):
    session["status"] = "aborted"
    session["updated_at"] = _now()
    save_session(session)
    return session
