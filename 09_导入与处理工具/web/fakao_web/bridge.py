"""对 fakao_cli 的全部封装。Web 层唯一 import fakao_cli 的地方。"""

import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

# bridge.py 位于 <根>/09_导入与处理工具/web/fakao_web/,parents[2] 即 09_导入与处理工具
CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
sys.path.insert(0, str(CLI_DIR))

import fakao_cli  # noqa: E402

# 写操作互斥：CLI 的“读-改-写”非事务，Flask 多线程下必须串行化
LOCK = threading.RLock()

_cache = {"key": None, "questions": None, "ts": 0.0}


def invalidate_cache():
    _cache["key"] = None
    _cache["questions"] = None


def _cache_key():
    files = list(fakao_cli.question_files()) + list(fakao_cli.WRONG_DIR.glob("*.md"))
    latest = max((f.stat().st_mtime for f in files), default=0.0)
    return (len(files), latest)


def cached_questions(max_age=5.0):
    """带 TTL 的题目汇总缓存；写操作后主动失效。"""
    key = _cache_key()
    now = time.time()
    if _cache["key"] == key and _cache["questions"] is not None and now - _cache["ts"] < max_age:
        return _cache["questions"]
    questions = fakao_cli.all_questions()
    _cache.update({"key": key, "questions": questions, "ts": now})
    return questions


def question_by_id(question_id):
    for question in cached_questions():
        if question["id"] == question_id:
            return question
    return None


def public_question(question):
    """训练场景的字段投影：剥离答案相关字段，防止前端源码剧透。"""
    return {
        "id": question["id"],
        "subject": question.get("subject", ""),
        "knowledge_points": question.get("knowledge_points", []),
        "question_type": question.get("question_type", ""),
        "title": question.get("title", ""),
        "question": question.get("question", ""),
        "options": [{"id": o["id"], "text": o["text"]} for o in question.get("options", [])],
        "multi": len(question.get("answers", [])) > 1,
    }


def record_review(**kwargs):
    with LOCK:
        outcome = fakao_cli.record_review(**kwargs)
    if outcome.get("ok"):
        invalidate_cache()
    return outcome


def run_generator(name, **kwargs):
    """直调 CLI 生成器（cmd_today/cmd_metrics 等），随后读输出文件由调用方处理。"""
    defaults = {"analyze": {"years": 10}, "build_bank": {"limit": 30}, "plan": {"limit": 6}, "today": {"limit": 8}}
    with LOCK:
        getattr(fakao_cli, "cmd_{}".format(name))(Namespace(**dict(defaults.get(name, {}), **kwargs)))


def load(path_key):
    """按语义名读取运行时 JSON。"""
    mapping = {
        "profile": fakao_cli.PROFILE,
        "records": fakao_cli.RECORD_DIR / "作答记录.json",
        "metrics": fakao_cli.RECORD_DIR / "提分指标.json",
        "error_analysis": fakao_cli.RECORD_DIR / "错误分析.json",
        "diagnosis": fakao_cli.RECORD_DIR / "诊断结果.json",
        "today_tasks": fakao_cli.TASK_DIR / "今日任务" / (fakao_cli.date.today().isoformat() + ".json"),
        "mocks": fakao_cli.MOCK_DIR / "模拟记录.json",
    }
    return fakao_cli.load_json(mapping[path_key], None)


def subjects():
    counts = {}
    for question in cached_questions():
        counts[question.get("subject", "未分类")] = counts.get(question.get("subject", "未分类"), 0) + 1
    return counts


def today_due(limit=8):
    today = fakao_cli.date.today().isoformat()
    due = [q for q in cached_questions() if q.get("next_review") and q["next_review"] <= today]
    return due[:limit]


def save_profile(exam_date, target_score, daily_minutes):
    with LOCK:
        fakao_cli.cmd_init(Namespace(exam_date=exam_date, target_score=target_score,
                                     daily_minutes=daily_minutes))


def add_mock(score, total_questions, seconds, date_str="", source="", notes=""):
    with LOCK:
        fakao_cli.cmd_mock_record(Namespace(score=score, total_questions=total_questions,
                                            seconds=seconds, date=date_str or None,
                                            source=source, notes=notes))
