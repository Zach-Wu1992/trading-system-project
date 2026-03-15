# -*- coding: utf-8 -*-
# --- routes/api.py：所有 API 端點（觸發交易、回測、設定） ---
import logging
import traceback
import pandas as pd
from flask import Blueprint, request, jsonify
from config import API_SECRET_KEY, CASH, STOP_LOSS_PCT, TAKE_PROFIT_PCT
from database import db
from trading.data_fetcher import get_historical_data_range, _normalize_stock_id
from trading.strategy import apply_signals_to_dataframe
from trading.executor import run_trading_job

api_bp = Blueprint('api', __name__)


@api_bp.route('/api/trigger-trade-check', methods=['POST'])
def trigger_trade_check():
    """手動觸發或排程呼叫的交易檢查端點（需 Bearer Token 授權）。"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {API_SECRET_KEY}":
        return jsonify({"status": "error", "message": "未經授權"}), 401
    result = run_trading_job()
    status_code = 200 if result.get('status') == 'success' else 500
    return jsonify(result), status_code


@api_bp.route('/api/settings', methods=['POST'])
def update_settings_api():
    """更新系統設定（監控標的 or 初始資金）。"""
    data = request.get_json()
    key, value = data.get('key'), data.get('value')
    if not key or not value:
        return jsonify({"status": "error", "message": "缺少 key 或 value"}), 400

    if key == 'initial_cash':
        stock_id = data.get('stock_id')
        if not stock_id:
            return jsonify({"status": "error", "message": "更新初始資金時必須提供 stock_id"}), 400
        db_key = f"initial_cash_{stock_id}"
    else:
        db_key = key

    try:
        db.update_setting(db_key, value)
        return jsonify({"status": "success", "message": f"設定 {db_key} 已更新為 {value}"}), 200
    except Exception as e:
        logging.error(f"更新設定 API 發生錯誤: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/api/run-backtest', methods=['POST'])
def handle_backtest():
    """執行歷史回測並返回每日資產曲線與交易紀錄。"""
    try:
        params = request.get_json()
        stock_id = params.get('stock_id', '2330.TW')
        start_date = params.get('start_date', '2024-01-01')
        end_date = params.get('end_date') or pd.Timestamp.now().strftime('%Y-%m-%d')
        initial_cash = int(params.get('initial_cash', CASH))

        stock_id_query = _normalize_stock_id(stock_id)
        df = get_historical_data_range(stock_id_query, start_date, end_date)

        if df is None:
            return jsonify({"error": "無法從 yfinance 下載資料或指標計算失敗（資料不足）"}), 400

        df = apply_signals_to_dataframe(df)

        backtest_portfolio = {'cash': initial_cash, 'position': 0, 'avg_cost': 0}
        daily_assets, trade_log = [], []
        insufficient_funds = False
        last_insufficient_price = 0

        for index, row in df.iterrows():
            price = row['close']
            signal = row['signal']
            ma50 = row['sma_50']
            action_taken = False

            # 1. 停損 / 停利 檢查
            if backtest_portfolio['position'] > 0:
                stop_loss_price = backtest_portfolio['avg_cost'] * (1 - STOP_LOSS_PCT)
                take_profit_price = backtest_portfolio['avg_cost'] * (1 + TAKE_PROFIT_PCT)

                if price < stop_loss_price:
                    profit = (price - backtest_portfolio['avg_cost']) * backtest_portfolio['position']
                    trade_log.append({
                        'timestamp': str(index.date()), 'stock_id': stock_id,
                        'action': '停損賣出', 'shares': backtest_portfolio['position'],
                        'price': price, 'total_value': price * backtest_portfolio['position'],
                        'profit': profit
                    })
                    backtest_portfolio['cash'] += price * backtest_portfolio['position']
                    backtest_portfolio['position'] = 0
                    backtest_portfolio['avg_cost'] = 0
                    action_taken = True

                elif price > take_profit_price:
                    profit = (price - backtest_portfolio['avg_cost']) * backtest_portfolio['position']
                    trade_log.append({
                        'timestamp': str(index.date()), 'stock_id': stock_id,
                        'action': '獲利了結(滿足30%)', 'shares': backtest_portfolio['position'],
                        'price': price, 'total_value': price * backtest_portfolio['position'],
                        'profit': profit
                    })
                    backtest_portfolio['cash'] += price * backtest_portfolio['position']
                    backtest_portfolio['position'] = 0
                    backtest_portfolio['avg_cost'] = 0
                    action_taken = True

                elif price < ma50 and price > backtest_portfolio['avg_cost']:
                    profit = (price - backtest_portfolio['avg_cost']) * backtest_portfolio['position']
                    trade_log.append({
                        'timestamp': str(index.date()), 'stock_id': stock_id,
                        'action': '動態停利(跌破MA50)', 'shares': backtest_portfolio['position'],
                        'price': price, 'total_value': price * backtest_portfolio['position'],
                        'profit': profit
                    })
                    backtest_portfolio['cash'] += price * backtest_portfolio['position']
                    backtest_portfolio['position'] = 0
                    backtest_portfolio['avg_cost'] = 0
                    action_taken = True

            # 2. 買入訊號處理
            if not action_taken and signal == "買入":
                if backtest_portfolio['position'] == 0 or price > backtest_portfolio['avg_cost']:
                    shares_to_buy = int(backtest_portfolio['cash'] // price)
                    if shares_to_buy > 0:
                        old_total = backtest_portfolio['avg_cost'] * backtest_portfolio['position']
                        new_total = old_total + (price * shares_to_buy)
                        backtest_portfolio['position'] += shares_to_buy
                        backtest_portfolio['cash'] -= price * shares_to_buy
                        backtest_portfolio['avg_cost'] = new_total / backtest_portfolio['position']
                        trade_log.append({
                            'timestamp': str(index.date()), 'stock_id': stock_id,
                            'action': '執行買入', 'shares': shares_to_buy,
                            'price': price, 'total_value': price * shares_to_buy,
                            'profit': None
                        })
                    elif backtest_portfolio['position'] == 0:
                        insufficient_funds = True
                        last_insufficient_price = price

            daily_assets.append(backtest_portfolio['cash'] + (backtest_portfolio['position'] * price))

        if len(trade_log) == 0 and insufficient_funds:
            return jsonify({
                "error": (
                    f"回測期間出現買入訊號，但初始資金 ({initial_cash:,.0f}) "
                    f"不足買進基本單位（至少需約 {last_insufficient_price:,.0f} 元買進1股）。"
                    f"請手動調高初始資金！"
                )
            }), 400

        results = {
            "chart_data": {
                "dates": [d.strftime('%Y-%m-%d') for d in df.index],
                "values": daily_assets
            },
            "trades": trade_log
        }
        return jsonify(results)

    except Exception as e:
        logging.error(f"回測 API 發生錯誤: {e}")
        logging.error(traceback.format_exc())
        return jsonify({"error": "回測時發生內部錯誤"}), 500
