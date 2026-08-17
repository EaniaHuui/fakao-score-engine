"""逐题训练：会话、判分、错因追问、提交记录。"""

from flask import Blueprint, jsonify, render_template, request

from .. import bridge, session as training

bp = Blueprint("train", __name__)

# 错因选项,与交互协议一致
REASONS = ["不会规则", "规则混淆", "漏条件", "审题/陷阱"]


@bp.route("/train")
def page():
    resumable = training.resume_or_prompt()
    return render_template("train.html", resumable=resumable, reasons=REASONS,
                           subjects=sorted(bridge.subjects().keys()))


@bp.route("/api/train/start", methods=["POST"])
def start():
    data = request.get_json(silent=True) or {}
    outcome = training.start(
        source=data.get("source", "today"),
        subject=str(data.get("subject", "") or ""),
        limit=int(data.get("limit", 8) or 8),
    )
    if not outcome.get("ok"):
        return jsonify(outcome), 400
    return jsonify(outcome)


@bp.route("/api/train/session")
def session_state():
    s = training.load_session()
    if not s:
        return jsonify({"active": False})
    return jsonify({
        "active": s.get("status") == "in_progress",
        "status": s.get("status"),
        "date": s.get("date"),
        "index": s.get("index"),
        "total": len(s.get("queue", [])),
        "pending_answer": s.get("pending_answer"),
    })


@bp.route("/api/train/current")
def current():
    s = training.resume_or_prompt()
    if not s:
        return jsonify({"ok": False, "error": "没有进行中的会话"}), 404
    qid = training.current_question_id(s)
    question = bridge.question_by_id(qid)
    if not question:
        return jsonify({"ok": False, "error": "题目不存在: {}".format(qid)}), 404
    payload = bridge.public_question(question)
    payload["index"] = s["index"] + 1
    payload["total"] = len(s["queue"])
    # 恢复“已判分未提交”的中间态(答错后正在填错因)
    if s.get("pending_answer"):
        payload["pending_answer"] = s["pending_answer"]
    return jsonify({"ok": True, "question": payload})


@bp.route("/api/train/answer", methods=["POST"])
def answer():
    s = training.resume_or_prompt()
    if not s:
        return jsonify({"ok": False, "error": "没有进行中的会话"}), 404
    data = request.get_json(silent=True) or {}
    qid = data.get("question_id")
    selected = sorted(set(data.get("selected", [])))
    confidence = data.get("confidence", "medium")
    seconds = int(data.get("seconds", 0) or 0)
    if confidence not in ("high", "medium", "low", "guess"):
        return jsonify({"ok": False, "error": "信心取值不合法"}), 400
    question = bridge.question_by_id(qid)
    if not question:
        return jsonify({"ok": False, "error": "题目不存在"}), 404
    correct_set = sorted(set(question.get("answers", [])))
    result = "correct" if selected and selected == correct_set else "wrong"
    need_followup = result == "wrong" or confidence in ("low", "guess")
    s["pending_answer"] = {
        "question_id": qid, "selected": selected, "result": result,
        "seconds": seconds, "confidence": confidence,
    }
    s["updated_at"] = training._now()
    training.save_session(s)
    return jsonify({
        "ok": True, "result": result, "answers": correct_set,
        "selected": selected, "need_followup": need_followup, "multi": len(correct_set) > 1,
    })


@bp.route("/api/train/submit", methods=["POST"])
def submit():
    s = training.resume_or_prompt()
    if not s:
        return jsonify({"ok": False, "error": "没有进行中的会话"}), 404
    data = request.get_json(silent=True) or {}
    pending = s.get("pending_answer")
    if not pending or pending.get("question_id") != data.get("question_id"):
        return jsonify({"ok": False, "error": "请先作答再提交"}), 400
    outcome = bridge.record_review(
        question_id=pending["question_id"],
        result=pending["result"],
        seconds=pending.get("seconds", 0),
        confidence=pending.get("confidence", "medium"),
        reason=str(data.get("reason", "") or ""),
        source_type="original",
        training_stage="original_review",
        independent=True,
    )
    if not outcome.get("ok"):
        return jsonify(outcome), 400
    entry = {"question_id": pending["question_id"], "result": pending["result"],
             "confidence": pending.get("confidence"), "seconds": pending.get("seconds", 0),
             "reason": data.get("reason", "")}
    s = training.advance(s, entry)
    finished = s["status"] == "finished"
    summary = None
    if finished:
        total = len(s["completed"])
        wrong = sum(1 for c in s["completed"] if c["result"] == "wrong")
        summary = {"total": total, "wrong": wrong, "correct": total - wrong}
    return jsonify({"ok": True, "next_review": outcome["next_review"], "status": outcome["status"],
                    "finished": finished, "summary": summary})


@bp.route("/api/train/skip", methods=["POST"])
def skip():
    s = training.resume_or_prompt()
    if not s:
        return jsonify({"ok": False, "error": "没有进行中的会话"}), 404
    training.skip(s)
    return jsonify({"ok": True})


@bp.route("/api/train/abort", methods=["POST"])
def abort():
    s = training.resume_or_prompt()
    if not s:
        return jsonify({"ok": True})
    training.abort(s)
    return jsonify({"ok": True})
