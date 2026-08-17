"""概览页：指标卡片、今日任务、分科统计。"""

from datetime import date

from flask import Blueprint, render_template

from .. import bridge

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    profile = bridge.load("profile") or {}
    metrics = bridge.load("metrics") or {}
    today_tasks = (bridge.load("today_tasks") or {}).get("tasks", [])
    subjects = bridge.subjects()
    total_questions = sum(subjects.values())
    due_count = len(bridge.today_due())
    days_left = None
    exam_date = profile.get("exam_date", "")
    if exam_date:
        try:
            days_left = (date.fromisoformat(exam_date) - date.today()).days
        except ValueError:
            days_left = None
    return render_template(
        "dashboard.html",
        profile=profile, metrics=metrics, today_tasks=today_tasks,
        subjects=subjects, total_questions=total_questions,
        due_count=due_count, days_left=days_left,
    )
