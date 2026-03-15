# -*- coding: utf-8 -*-
# --- APScheduler 排程任務 ---
import logging
import pytz
from apscheduler.schedulers.background import BackgroundScheduler


def start_scheduler(trading_job_func):
    """建立並啟動背景定時排程，每週一至週五 13:30 執行交易任務。"""
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Taipei'))
    scheduler.add_job(trading_job_func, 'cron', day_of_week='mon-fri', hour=13, minute=30)
    scheduler.start()
    logging.info("⏰ APScheduler 背景定時任務已啟動 (排程時間: 每週一至週五 13:30)")
