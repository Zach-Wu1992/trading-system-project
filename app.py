# -*- coding: utf-8 -*-
# --- app.py：Flask 應用程式入口（組裝與啟動）---
import logging
from flask import Flask
from database.db import setup_database
from routes.dashboard import dashboard_bp
from routes.api import api_bp
from scheduler import start_scheduler
from trading.executor import run_trading_job


def create_app() -> Flask:
    """Flask 應用程式工廠函式（供 gunicorn / Railway 使用）。"""
    app = Flask(__name__)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)

    with app.app_context():
        setup_database()

    start_scheduler(run_trading_job)
    return app


if __name__ == '__main__':
    import os
    if not os.environ.get('DATABASE_URL'):
        logging.error("❌ 錯誤：未設定 DATABASE_URL 環境變數，無法啟動。")
    else:
        app = create_app()
        app.run(host='0.0.0.0', port=5001, debug=True)