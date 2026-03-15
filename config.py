# -*- coding: utf-8 -*-
# --- 全域設定與環境變數 ---
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 環境變數 ---
DATABASE_URL = os.environ.get('DATABASE_URL')
API_SECRET_KEY = os.environ.get('API_SECRET_KEY')
FINMIND_API_TOKEN = os.environ.get('FINMIND_API_TOKEN')

# --- 交易策略常數 ---
CASH = 1_000_000          # 預設初始資金
STOP_LOSS_PCT = 0.15      # 停損點：15%
TAKE_PROFIT_PCT = 0.30    # 停利點：30%
