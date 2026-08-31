"""
app.py — Magnetar Sentinel v0.2
--------------------------------
Modular Flask Application Entry Point.
Blueprints:
  - dashboard: / and /dashboard
  - reports: /pages, /referrers, /countries, /visitors
  - analytics: /journey, /retention, /cohorts, /funnels, /events
  - settings: /settings
  - api: /api/* and /health
"""

from __future__ import annotations

import traceback
from flask import Flask, render_template

from magnetar.blueprints.analytics import analytics_bp
from magnetar.blueprints.api import api_bp
from magnetar.blueprints.dashboard import dashboard_bp
from magnetar.blueprints.reports import reports_bp
from magnetar.blueprints.security import security_bp
from magnetar.blueprints.settings import settings_bp
from magnetar.config import DATABASE_URL, DAYS, GEOIP_PATH, LOG_DIR, PORT, SSH_HOST, SSH_KEY, SSH_USER
from magnetar.context_processors import domain_context_processor, get_sync_info
from magnetar.db import get_db_session, get_engine, init_db
from magnetar.scheduler import init_scheduler
from magnetar.sync import run_sync


def create_app() -> Flask:
    app = Flask(__name__)

    # 1. Database Init
    engine = get_engine(DATABASE_URL)
    init_db(engine)

    # 2. Context Processors
    app.context_processor(domain_context_processor)

    # 3. Register Blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)

    # 4. Background Sync Scheduler
    def _do_sync():
        with get_db_session() as db:
            run_sync(
                ssh_host=SSH_HOST,
                ssh_user=SSH_USER,
                ssh_key=SSH_KEY,
                log_dir=LOG_DIR,
                db_session=db,
                geoip_db_path=GEOIP_PATH,
                days=DAYS,
            )

    scheduler = init_scheduler(app, _do_sync)
    app.config["SCHEDULER"] = scheduler

    # 5. Error Handlers
    @app.errorhandler(404)
    def not_found(e):
        return render_template(
            "error.html",
            error_title="Page Not Found",
            error_message="The page you requested does not exist.",
            error_detail=None,
            last_sync=get_sync_info(),
        ), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template(
            "error.html",
            error_title="Internal Server Error",
            error_message=str(e),
            error_detail=traceback.format_exc(),
            last_sync=get_sync_info(),
        ), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
