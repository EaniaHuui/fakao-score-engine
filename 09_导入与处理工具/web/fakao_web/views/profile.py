"""档案与模考：用户档案表单、模拟成绩录入。"""

from flask import Blueprint, jsonify, render_template, request

from .. import bridge

bp = Blueprint("profile", __name__)


@bp.route("/profile")
def page():
    return render_template(
        "profile.html",
        profile=bridge.load("profile") or {},
        mocks=bridge.load("mocks") or [],
    )


def _int_field(data, name, default=None):
    try:
        return int(data.get(name, ""))
    except (TypeError, ValueError):
        return default


@bp.route("/api/profile", methods=["POST"])
def save_profile():
    data = request.get_json(silent=True) or request.form
    bridge.save_profile(
        exam_date=str(data.get("exam_date", "") or ""),
        target_score=_int_field(data, "target_score"),
        daily_minutes=_int_field(data, "daily_minutes"),
    )
    return jsonify({"ok": True, "profile": bridge.load("profile")})


@bp.route("/api/mock", methods=["POST"])
def add_mock():
    data = request.get_json(silent=True) or request.form
    score = _int_field(data, "score")
    if score is None:
        return jsonify({"ok": False, "error": "分数不能为空"}), 400
    bridge.add_mock(
        score=score,
        total_questions=_int_field(data, "total_questions", 0) or 0,
        seconds=_int_field(data, "seconds", 0) or 0,
        date_str=str(data.get("date", "") or ""),
        source=str(data.get("source", "") or ""),
        notes=str(data.get("notes", "") or ""),
    )
    return jsonify({"ok": True, "mocks": bridge.load("mocks")})
