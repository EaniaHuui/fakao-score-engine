"""法考工作台 Flask 应用工厂。"""

from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False

    from .views.dashboard import bp as dashboard_bp
    from .views.train import bp as train_bp
    from .views.reports import bp as reports_bp
    from .views.bank import bp as bank_bp
    from .views.profile import bp as profile_bp
    from .views.zhuma import bp as zhuma_bp

    for bp in (dashboard_bp, train_bp, reports_bp, bank_bp, profile_bp, zhuma_bp):
        app.register_blueprint(bp)
    return app
