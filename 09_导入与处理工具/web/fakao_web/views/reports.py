"""分析报告：指标、错误分析、诊断、今日任务，支持一键重新生成。"""

from flask import Blueprint, jsonify, render_template, request

from .. import bridge

bp = Blueprint("reports", __name__)

GENERATORS = {
    "metrics": "metrics",
    "error_analysis": "error_analysis",
    "diagnose": "diagnose",
    "today": "today",
}


@bp.route("/reports")
def page():
    return render_template(
        "reports.html",
        metrics=bridge.load("metrics"),
        error_analysis=bridge.load("error_analysis"),
        diagnosis=bridge.load("diagnosis"),
        today_tasks=(bridge.load("today_tasks") or {}).get("tasks", []),
        mocks=bridge.load("mocks") or [],
    )


@bp.route("/api/reports/<kind>")
def get_report(kind):
    data = bridge.load(kind)
    if data is None:
        return jsonify({"ok": False, "error": "尚未生成"}), 404
    return jsonify({"ok": True, "data": data})


@bp.route("/api/reports/regenerate", methods=["POST"])
def regenerate():
    data = request.get_json(silent=True) or {}
    kind = data.get("kind", "all")
    kinds = list(GENERATORS) if kind == "all" else [kind]
    for name in kinds:
        if name not in GENERATORS:
            return jsonify({"ok": False, "error": "未知报告类型: {}".format(name)}), 400
    done = []
    for name in kinds:
        bridge.run_generator(GENERATORS[name])
        done.append(name)
    return jsonify({"ok": True, "regenerated": done})
