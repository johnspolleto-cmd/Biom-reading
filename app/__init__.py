from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from . import typography
from .config import Config
from .domain.errors import DomainError
from .extensions import db


def create_app(config_object: type[Config] | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__)
    app.config.from_object(config_object or Config)

    db.init_app(app)
    typography.register(app)

    from .auth import load_current_member

    app.before_request(load_current_member)

    from .api import api_bp
    from .views import views_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)

    from . import cli

    cli.register(app)

    @app.errorhandler(DomainError)
    def _domain_error(err: DomainError):
        if request.path.startswith("/api/"):
            return jsonify(err.to_dict()), err.status_code
        from flask import render_template

        return render_template("error.html", message=err.message), err.status_code

    @app.errorhandler(404)
    def _not_found(_err):
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": "not_found", "message": "Не найдено"}}), 404
        from flask import render_template

        return render_template("error.html", message="Такой страницы нет"), 404

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.context_processor
    def _globals():
        from .auth import current_member

        return {
            "app_name": app.config["APP_NAME"],
            "app_tagline": app.config["APP_TAGLINE"],
            "club_name": app.config["CLUB_NAME"],
            "me": current_member(),
        }

    return app


__all__ = ["create_app", "db", "os"]
