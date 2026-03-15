# -*- coding: utf-8 -*-
# --- routes/dashboard.py：首頁路由與儀表板資料組裝 ---
import logging
from flask import Blueprint, render_template
from config import CASH, API_SECRET_KEY
from database import db
from trading.data_fetcher import get_latest_price_info
from trading.strategy import calculate_latest_signal

dashboard_bp = Blueprint('dashboard', __name__)


def get_live_dashboard_data() -> dict:
    """組裝即時儀表板所需的所有資料。"""
    # 延遲匯入以避免循環依賴（executor → db → dashboard 可能的循環）
    from trading.executor import get_current_portfolio

    stock_id = db.get_setting('live_stock_id') or '2330.TW'
    stock_specific_cash_key = f"initial_cash_{stock_id}"
    initial_cash = db.get_setting(stock_specific_cash_key) or CASH

    trades = db.get_trades(stock_id)
    performance = db.get_performance(stock_id)

    latest_price, latest_signal = "N/A", "N/A"
    try:
        price, _, _, df = get_latest_price_info(stock_id)
        if price is not None:
            latest_price = price
            latest_signal = calculate_latest_signal(df)
    except Exception as e:
        logging.error(f"❌ 獲取儀表板即時數據時發生錯誤: {e}")

    if performance:
        total_asset = performance[-1]['asset_value']
    else:
        current_portfolio = get_current_portfolio(stock_id)
        total_asset = current_portfolio['cash']

    return {
        "chart_data": {
            'dates': [p['date'] for p in performance],
            'values': [p['asset_value'] for p in performance]
        },
        "trades": [dict(row) for row in trades],
        "latest_price": latest_price,
        "latest_signal": latest_signal,
        "total_asset": total_asset,
        "stock_id": stock_id,
        "initial_cash": initial_cash
    }


@dashboard_bp.route('/')
def dashboard():
    live_data = get_live_dashboard_data()
    return render_template('index.html', live_data=live_data, api_secret_key=API_SECRET_KEY)
