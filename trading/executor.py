# -*- coding: utf-8 -*-
# --- trading/executor.py：交易執行、停損停利、持倉計算 ---
import logging
import pandas as pd
from config import CASH, STOP_LOSS_PCT, TAKE_PROFIT_PCT
from database import db
from trading.data_fetcher import get_latest_price_info
from trading.strategy import calculate_latest_signal


def get_current_portfolio(stock_id: str) -> dict:
    """
    根據歷史交易紀錄計算目前的持倉狀態。

    Returns:
        dict: {'cash': float, 'position': int, 'avg_cost': float}
    """
    stock_specific_cash_key = f"initial_cash_{stock_id}"
    initial_cash_str = db.get_setting(stock_specific_cash_key)
    initial_cash = int(initial_cash_str) if initial_cash_str else CASH

    trades = db.get_buy_sell_trades(stock_id)
    portfolio = {'cash': initial_cash, 'position': 0, 'avg_cost': 0}

    for trade in trades:
        if trade['action'] == "執行買入":
            trade_cost = float(trade['price']) * int(trade['shares'])
            old_total = portfolio['avg_cost'] * portfolio['position']
            new_total = old_total + trade_cost
            portfolio['position'] += int(trade['shares'])
            portfolio['cash'] -= trade_cost
            if portfolio['position'] > 0:
                portfolio['avg_cost'] = new_total / portfolio['position']
        elif "賣出" in trade['action']:
            portfolio['cash'] += float(trade['price']) * int(trade['shares'])
            portfolio['position'] = 0
            portfolio['avg_cost'] = 0

    return portfolio


def execute_trade(timestamp, signal: str, price: float, portfolio: dict, stock_id: str):
    """執行一般的買入/持有訊號，將結果記錄至資料庫。"""
    if signal == "買入":
        db.log_trade(timestamp, stock_id, "買入訊號", 0, price)
        shares_to_buy = int(portfolio['cash'] // price)
        if shares_to_buy > 0 and (portfolio['position'] == 0 or price > portfolio['avg_cost']):
            db.log_trade(timestamp, stock_id, "執行買入", shares_to_buy, price)
            logging.info(
                f"📈【執行買入(資金打滿)】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}，"
                f"股數 {shares_to_buy}，價格 {price:.2f}"
            )
    elif signal == "賣出":
        db.log_trade(timestamp, stock_id, "賣出訊號", 0, price)
        if portfolio['position'] > 0:
            profit = (price - portfolio['avg_cost']) * portfolio['position']
            db.log_trade(timestamp, stock_id, "執行賣出", portfolio['position'], price, profit)
            logging.info(
                f"📉【執行賣出】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}，損益：{profit:,.2f}"
            )
    elif signal == "持有":
        db.log_trade(timestamp, stock_id, "持有", 0, price)


def check_stop_loss(timestamp, price: float, portfolio: dict, stock_id: str) -> bool:
    """
    檢查是否觸發停損（跌破成本 15%）。

    Returns:
        bool: True 表示已停損賣出
    """
    if portfolio['position'] > 0:
        stop_loss_price = portfolio['avg_cost'] * (1 - STOP_LOSS_PCT)
        if price < stop_loss_price:
            profit = (price - portfolio['avg_cost']) * portfolio['position']
            db.log_trade(timestamp, stock_id, "停損賣出", portfolio['position'], price, profit)
            logging.warning(f"💥【強制停損】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}!")
            return True
    return False


def check_take_profit(timestamp, price: float, ma50, portfolio: dict, stock_id: str) -> bool:
    """
    檢查是否觸發停利。

    條件一：達到固定 30% 獲利目標
    條件二：跌破 MA50 且目前為帳面獲利（動態保本停利）

    Returns:
        bool: True 表示已停利賣出
    """
    if portfolio['position'] > 0:
        take_profit_price = portfolio['avg_cost'] * (1 + TAKE_PROFIT_PCT)
        if price > take_profit_price:
            profit = (price - portfolio['avg_cost']) * portfolio['position']
            db.log_trade(timestamp, stock_id, "獲利了結(滿足30%)", portfolio['position'], price, profit)
            logging.info(
                f"🎉【達成停利】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}! 滿足 30% 獲利目標。"
            )
            return True

        if ma50 is not None and price < ma50 and price > portfolio['avg_cost']:
            profit = (price - portfolio['avg_cost']) * portfolio['position']
            db.log_trade(timestamp, stock_id, "動態停利(跌破MA50)", portfolio['position'], price, profit)
            logging.info(
                f"🛡️【動態保本】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}! 跌破季線(MA50)，提前獲利了結。"
            )
            return True

    return False


def run_trading_job() -> dict:
    """
    完整交易排程任務（由 APScheduler 呼叫或手動觸發）。

    執行順序：
    1. 停損檢查（優先）
    2. 停利檢查
    3. 普通進出場訊號

    Returns:
        dict: {'status': 'success'|'error', 'message': str}
    """
    import traceback
    stock_id = db.get_setting('live_stock_id') or "2330.TW"
    try:
        check_timestamp = pd.Timestamp.now(tz='Asia/Taipei')
        logging.info(
            f"🤖 API被觸發，開始檢查 {stock_id} at {check_timestamp.strftime('%Y-%m-%d %H:%M:%S')}..."
        )

        latest_price, data_timestamp, ma50, df = get_latest_price_info(stock_id)
        if latest_price is None or data_timestamp is None or ma50 is None or df is None:
            return {"status": "error", "message": "無法獲取最新價格資料"}

        price_f: float = float(latest_price)
        ma50_f: float = float(ma50)

        signal = calculate_latest_signal(df)
        logging.info(
            f"   - 資料時間: {data_timestamp.strftime('%Y-%m-%d %H:%M')}, "
            f"最新價格: {price_f:.2f}, MA50: {ma50_f:.2f}, 日線訊號: {signal}"
        )

        portfolio = get_current_portfolio(stock_id)

        if not check_stop_loss(check_timestamp, price_f, portfolio, stock_id):
            if not check_take_profit(check_timestamp, price_f, ma50_f, portfolio, stock_id):
                execute_trade(check_timestamp, signal, price_f, portfolio, stock_id)

        final_portfolio = get_current_portfolio(stock_id)
        total_asset = final_portfolio['cash'] + (final_portfolio['position'] * price_f)
        db.log_performance(check_timestamp.date(), stock_id, total_asset)

        message = f"檢查完成。總資產: {total_asset:,.2f}"
        return {"status": "success", "message": message}

    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}
