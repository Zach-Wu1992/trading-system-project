# -*- coding: utf-8 -*-
# --- 匯入函式庫 ---
import pandas as pd
import pandas_ta as ta
import os
import json
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template_string, request, jsonify
from FinMind.data import FinMindApi

# --- 1. 全域設定與參數 ---
DATABASE_URL = os.environ.get('DATABASE_URL')
API_SECRET_KEY = os.environ.get('API_SECRET_KEY')
FINMIND_API_TOKEN = os.environ.get('FINMIND_API_TOKEN')

pd.set_option('display.max_columns', None)
CASH = 1000000
ADD_ON_SHARES = 1000
MAX_POSITION_SHARES = 3000
STOP_LOSS_PCT = 0.02

# --- 初始化 FinMind API 客戶端 ---
fm = None
if FINMIND_API_TOKEN:
    try:
        fm = FinMindApi()
        # 使用 'api_token' 而不是 'token'
        fm.login(api_token=FINMIND_API_TOKEN)
        print("✅ FinMind API 客戶端初始化成功。")
    except Exception as e:
        print(f"❌ FinMind 登入失敗: {e}")
else:
    print("⚠️ 警告：未設定 FINMIND_API_TOKEN 環境變數。")

# --- 2. 核心資料庫函式 (PostgreSQL 版) ---
def get_db_connection():
    if not DATABASE_URL: raise ValueError("DATABASE_URL 環境變數未設定！")
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def setup_database():
    print("🚀 正在設定 PostgreSQL 資料庫...")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id SERIAL PRIMARY KEY, timestamp TEXT NOT NULL, stock_id TEXT NOT NULL,
                    action TEXT NOT NULL, shares INTEGER NOT NULL, price REAL NOT NULL,
                    total_value REAL NOT NULL, profit REAL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS daily_performance (
                    date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    asset_value REAL NOT NULL,
                    PRIMARY KEY (date, stock_id)
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                )
            ''')
            cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", ('live_stock_id', '2308.TW'))
        conn.commit()
        print("✅ 資料庫設定完成。")
    except Exception as e:
        print(f"❌ 資料庫設定失敗: {e}")
        conn.rollback()
    finally:
        conn.close()

def get_setting(key):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
            result = cur.fetchone()
            return result[0] if result else None
    finally:
        conn.close()

def update_setting(key, value):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))
        conn.commit()
    finally:
        conn.close()

def log_trade(timestamp, stock_id, action, shares, price, profit=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            total_value = shares * price
            formatted_timestamp = timestamp.strftime('%Y-%m-%d %H:%M')
            sql = 'INSERT INTO trades (timestamp, stock_id, action, shares, price, total_value, profit) VALUES (%s, %s, %s, %s, %s, %s, %s)'
            cur.execute(sql, (formatted_timestamp, stock_id, action, shares, price, total_value, profit))
        conn.commit()
    finally:
        conn.close()
        
def log_performance(date, stock_id, asset_value):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            sql = 'INSERT INTO daily_performance (date, stock_id, asset_value) VALUES (%s, %s, %s) ON CONFLICT (date, stock_id) DO UPDATE SET asset_value = EXCLUDED.asset_value'
            cur.execute(sql, (str(date), stock_id, asset_value))
        conn.commit()
    finally:
        conn.close()

# --- 3. 交易邏輯函式 ---
def get_current_portfolio(stock_id):
    stock_specific_cash_key = f"initial_cash_{stock_id}"
    initial_cash_str = get_setting(stock_specific_cash_key)
    initial_cash = int(initial_cash_str) if initial_cash_str else CASH
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT action, shares, price FROM trades WHERE stock_id = %s AND (action = '執行買入' OR action LIKE '%%賣出') ORDER BY timestamp ASC", (stock_id,))
            trades = cur.fetchall()
        portfolio = {'cash': initial_cash, 'position': 0, 'avg_cost': 0}
        for trade in trades:
            if trade['action'] == "執行買入":
                trade_cost = trade['price'] * trade['shares']
                old_total = portfolio['avg_cost'] * portfolio['position']
                new_total = old_total + trade_cost
                portfolio['position'] += trade['shares']
                portfolio['cash'] -= trade_cost
                if portfolio['position'] > 0: portfolio['avg_cost'] = new_total / portfolio['position']
            elif "賣出" in trade['action']:
                portfolio['cash'] += trade['price'] * trade['shares']
                portfolio['position'] = 0
                portfolio['avg_cost'] = 0
        return portfolio
    finally:
        conn.close()

def execute_trade(timestamp, signal, price, portfolio, stock_id):
    if signal == "買入":
        log_trade(timestamp, stock_id, "買入訊號", 0, price)
        if portfolio['position'] < MAX_POSITION_SHARES and (portfolio['position'] == 0 or price > portfolio['avg_cost']) and portfolio['cash'] >= price * ADD_ON_SHARES:
            log_trade(timestamp, stock_id, "執行買入", ADD_ON_SHARES, price)
    elif signal == "賣出":
        log_trade(timestamp, stock_id, "賣出訊號", 0, price)
        if portfolio['position'] > 0:
            shares_to_sell = portfolio['position']
            profit = (price - portfolio['avg_cost']) * shares_to_sell
            log_trade(timestamp, stock_id, "執行賣出", shares_to_sell, price, profit)
    elif signal == "持有":
        log_trade(timestamp, stock_id, "持有", 0, price)

def check_stop_loss(timestamp, price, portfolio, stock_id):
    if portfolio['position'] > 0:
        stop_loss_price = portfolio['avg_cost'] * (1 - STOP_LOSS_PCT)
        if price < stop_loss_price:
            shares_to_sell = portfolio['position']
            profit = (price - portfolio['avg_cost']) * shares_to_sell
            log_trade(timestamp, stock_id, "停損賣出", shares_to_sell, price, profit)
            return True
    return False

def clean_df_finmind(df_raw):
    if df_raw is None or df_raw.empty: return None
    df = df_raw.copy()
    df.rename(columns={'max': 'high', 'min': 'low', 'Trading_Volume': 'volume'}, inplace=True)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    if not all(col in df.columns for col in required_cols):
        print(f"❌ FinMind 資料清理失敗：缺少必要欄位. 現有: {df.columns.tolist()}")
        return None
    return df

def calculate_latest_signal(df):
    latest_data = df.iloc[-2:]
    if len(latest_data) < 2: return "資料不足"
    yesterday_sma5, yesterday_sma20 = latest_data[['sma_5', 'sma_20']].iloc[0]
    today_sma5, today_sma20 = latest_data[['sma_5', 'sma_20']].iloc[1]
    signal = "持有"
    if yesterday_sma5 < yesterday_sma20 and today_sma5 > today_sma20: signal = "買入"
    elif yesterday_sma5 > yesterday_sma20 and today_sma5 < today_sma20: signal = "賣出"
    return signal

def get_latest_price_and_signal(stock_id):
    if not fm: return None, None, "FinMind 未初始化"
    end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
    start_date = (pd.Timestamp.now() - pd.DateOffset(days=60)).strftime('%Y-%m-%d')
    df_daily_raw = fm.get_data(dataset="TaiwanStockPrice", data_id=stock_id.replace('.TW', ''), start_date=start_date, end_date=end_date)
    df_daily = clean_df_finmind(df_daily_raw)
    if df_daily is None: return None, None, "日線資料獲取或清理失敗"
    latest_price = df_daily['close'].iloc[-1]
    latest_time = df_daily.index[-1]
    df_daily['sma_5'] = df_daily.ta.sma(length=5, close='close')
    df_daily['sma_20'] = df_daily.ta.sma(length=20, close='close')
    if df_daily['sma_20'].isnull().all(): return latest_price, latest_time, "指標計算失敗"
    signal = calculate_latest_signal(df_daily)
    return latest_price, latest_time, signal

def run_trading_job():
    stock_id = get_setting('live_stock_id') or "2308.TW"
    try:
        latest_price, latest_time, signal = get_latest_price_and_signal(stock_id)
        if latest_price is None: return {"status": "error", "message": "無法獲取最新價格資料"}
        if "失敗" in signal or "異常" in signal: return {"status": "error", "message": signal}
        portfolio = get_current_portfolio(stock_id)
        stop_loss_triggered = check_stop_loss(latest_time, latest_price, portfolio, stock_id)
        if not stop_loss_triggered:
            execute_trade(latest_time, signal, latest_price, portfolio, stock_id)
        final_portfolio = get_current_portfolio(stock_id)
        total_asset = final_portfolio['cash'] + (final_portfolio['position'] * latest_price)
        log_performance(latest_time.date(), stock_id, total_asset)
        message = f"檢查完成。總資產: {total_asset:,.2f}"
        return {"status": "success", "message": message}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

# --- 4. Flask Web 應用 ---
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>交易分析平台</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #111827; color: #d1d5db; }
        .tab-button { padding: 0.5rem 1rem; border-radius: 0.375rem; transition: background-color 0.2s; cursor: pointer; }
        .tab-button.active { background-color: #3b82f6; color: white; }
        .tab-button:not(.active) { background-color: #374151; }
        .content-section { display: none; }
        .content-section.active { display: block; }
        .chart-container { height: 50vh; min-height: 400px; background-color: #1f2937; border-radius: 0.5rem; padding: 1.5rem; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #374151; }
        th { background-color: #374151; }
        .buy-action { color: #22c55e; } 
        .sell-action { color: #ef4444; }
        .hold-action { color: #9ca3af; }
        .pagination-btn { background-color: #374151; padding: 0.5rem 1rem; border-radius: 0.375rem; transition: background-color 0.2s; }
        .pagination-btn:hover:not(:disabled) { background-color: #4b5563; }
        .pagination-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .signal-row { background-color: rgba(31, 41, 55, 0.5); }
    </style>
</head>
<body class="p-4 md:p-8">
    <div class="max-w-7xl mx-auto">
        <header class="mb-8"><h1 class="text-3xl font-bold text-white">自動交易分析平台</h1><p class="text-gray-400">整合即時監控與歷史回測功能</p></header>
        <div class="flex space-x-4 mb-8 border-b border-gray-700"><button id="tab-live" class="tab-button active">即時儀表板</button><button id="tab-backtest" class="tab-button">歷史回測</button></div>
        <main>
            <section id="content-live" class="content-section active">
                <section class="bg-gray-800 p-6 rounded-lg mb-8"><div class="grid grid-cols-1 md:grid-cols-3 gap-6"><div class="md:col-span-2"><h3 class="text-xl font-semibold mb-4 text-white">即時監控設定</h3>
                <div class="space-y-4">
                    <div class="flex items-end space-x-2">
                        <div class="flex-grow"><label for="live_stock_id" class="block text-sm font-medium text-gray-300">監控股票代號</label><input type="text" id="live_stock_id" value="{{ live_data.stock_id }}" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm text-white"></div>
                        <button type="button" id="update-stock-btn" class="bg-green-600 text-white font-semibold py-2 px-4 rounded-md hover:bg-green-700 h-10">更新標的</button>
                    </div>
                     <div class="flex items-end space-x-2">
                        <div class="flex-grow"><label for="live_initial_cash" class="block text-sm font-medium text-gray-300">初始資金 (針對 {{ live_data.stock_id }})</label><input type="number" id="live_initial_cash" value="{{ live_data.initial_cash }}" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm text-white"></div>
                        <button type="button" id="update-cash-btn" class="bg-yellow-600 text-white font-semibold py-2 px-4 rounded-md hover:bg-yellow-700 h-10">修改資金</button>
                    </div>
                    <div><label for="cron_time" class="block text-sm font-medium text-gray-300">自動執行時間</label><input type="text" id="cron_time" value="交易日 09-13點，每小時一次" readonly class="mt-1 block w-full bg-gray-900 border-gray-600 rounded-md text-gray-400"></div>
                </div>
                <div id="settings-status" class="mt-2 text-sm h-5"></div></div><div><h3 class="text-xl font-semibold mb-4 text-white">手動操作</h3><button type="button" id="manual-trigger-btn" class="w-full bg-indigo-600 text-white font-semibold py-2 px-4 rounded-md hover:bg-indigo-700 h-10">手動觸發檢查</button></div></div></section>
                <section class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8"><div class="bg-gray-800 p-6 rounded-lg"><h3 class="text-gray-400 text-sm font-medium">最新股價</h3><p id="live-latest-price" class="text-white text-3xl font-semibold">{{ "%.2f"|format(live_data.latest_price) if live_data.latest_price != "N/A" else "N/A" }}</p></div><div class="bg-gray-800 p-6 rounded-lg"><h3 class="text-gray-400 text-sm font-medium">當前訊號</h3><p id="live-latest-signal" class="text-3xl font-semibold {{ 'buy-action' if live_data.latest_signal == '買入' else 'sell-action' if live_data.latest_signal == '賣出' else 'hold-action' }}">{{ live_data.latest_signal }}</p></div><div class="bg-gray-800 p-6 rounded-lg"><h3 class="text-gray-400 text-sm font-medium">總資產</h3><p id="live-total-asset" class="text-white text-3xl font-semibold">{{ "%.2f"|format(live_data.total_asset) if live_data.total_asset != "N/A" else "N/A" }}</p></div></section>
                <div class="chart-container mb-8"><canvas id="liveAssetChart"></canvas></div>
                <h2 class="text-2xl font-semibold mb-4 text-white">每日檢查紀錄</h2>
                <div class="overflow-x-auto bg-gray-800 rounded-lg shadow-lg"><table id="live-trades-table"><thead><tr><th>檢查時間</th><th>股票代號</th><th>事件/動作</th><th>執行股數</th><th>執行價格</th><th>總金額</th><th>實現損益</th></tr></thead><tbody></tbody></table></div>
                <div id="live-pagination" class="mt-4 flex justify-center items-center space-x-4"></div>
            </section>
            <section id="content-backtest" class="content-section">
                <div class="bg-gray-800 p-6 rounded-lg mb-8"><form id="backtest-form" class="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
                    <div><label for="stock_id" class="block text-sm font-medium text-gray-300">股票代號</label><input type="text" id="stock_id" value="2330.TW" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm text-white"></div>
                    <div><label for="start_date" class="block text-sm font-medium text-gray-300">開始日期</label><input type="date" id="start_date" value="2024-01-01" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm text-white"></div>
                    <div><label for="end_date" class="block text-sm font-medium text-gray-300">結束日期</label><input type="date" id="end_date" value="" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm text-white"></div>
                    <div><label for="backtest_initial_cash" class="block text-sm font-medium text-gray-300">初始資金</label><input type="number" id="backtest_initial_cash" value="1000000" class="mt-1 block w-full bg-gray-700 border-gray-600 rounded-md shadow-sm text-white"></div>
                    <button type="submit" class="w-full bg-blue-600 text-white font-semibold py-2 px-4 rounded-md hover:bg-blue-700">執行回測</button>
                </form></div>
                <div id="backtest-results" class="hidden"><div class="chart-container mb-8"><canvas id="backtestAssetChart"></canvas></div><h2 class="text-2xl font-semibold mb-4 text-white">回測交易紀錄</h2><div class="overflow-x-auto bg-gray-800 rounded-lg shadow-lg"><table id="backtest-trades-table"><thead><tr><th>交易時間</th><th>股票代號</th><th>動作</th><th>股數</th><th>價格</th><th>總金額</th><th>損益</th></tr></thead><tbody></tbody></table></div><div id="backtest-pagination" class="mt-4 flex justify-center items-center space-x-4"></div></div>
                <div id="loading-spinner" class="hidden text-center py-10"><svg class="animate-spin h-8 w-8 text-white mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0

