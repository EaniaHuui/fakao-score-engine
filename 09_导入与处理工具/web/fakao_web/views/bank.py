"""题库浏览：筛选、分页、题目详情。"""

from flask import Blueprint, jsonify, render_template, request

from .. import bridge

bp = Blueprint("bank", __name__)

PAGE_SIZE = 50


@bp.route("/bank")
def page():
    subject = request.args.get("subject", "")
    status = request.args.get("status", "")
    keyword = request.args.get("q", "").strip()
    try:
        page_no = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page_no = 1

    questions = bridge.cached_questions()
    if subject:
        questions = [q for q in questions if q.get("subject") == subject]
    if status:
        questions = [q for q in questions if q.get("status") == status]
    if keyword:
        questions = [q for q in questions if keyword in q.get("question", "") or keyword in q.get("title", "")]

    total = len(questions)
    start = (page_no - 1) * PAGE_SIZE
    rows = questions[start:start + PAGE_SIZE]
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return render_template(
        "bank.html",
        rows=rows, total=total, page_no=page_no, total_pages=total_pages,
        subject=subject, status=status, keyword=keyword,
        subjects=sorted(bridge.subjects().keys()),
        statuses=["unreviewed", "reviewing", "mastered", "correct_once"],
    )


@bp.route("/api/bank/question/<question_id>")
def detail(question_id):
    question = bridge.question_by_id(question_id)
    if not question:
        return jsonify({"ok": False, "error": "题目不存在"}), 404
    records = [r for r in (bridge.load("records") or []) if r.get("question_id") == question_id]
    return jsonify({"ok": True, "question": question, "records": records})
