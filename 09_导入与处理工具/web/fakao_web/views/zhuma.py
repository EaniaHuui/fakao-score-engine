"""竹马导入：两阶段引导 + 后台任务状态轮询。"""

from flask import Blueprint, jsonify, render_template, request

from .. import tasks

bp = Blueprint("zhuma", __name__)


@bp.route("/zhuma")
def page():
    return render_template("zhuma.html")


@bp.route("/api/zhuma/status")
def status():
    return jsonify(tasks.status())


@bp.route("/api/zhuma/<action>", methods=["POST"])
def run(action):
    if action not in ("open", "login", "auto", "close"):
        return jsonify({"ok": False, "error": "未知操作"}), 404
    data = request.get_json(silent=True) or {}
    # open/close 秒级完成;login/auto 起后台进程后立即返回
    outcome = tasks.start(action, chrome_path=str(data.get("chrome_path", "") or "") or None)
    return jsonify(outcome), (200 if outcome.get("ok") else 409)


@bp.route("/api/zhuma/cancel", methods=["POST"])
def cancel():
    return jsonify(tasks.cancel())


@bp.route("/api/zhuma/reset", methods=["POST"])
def reset():
    return jsonify(tasks.reset())
