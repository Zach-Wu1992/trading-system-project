# -*- coding: utf-8 -*-
# --- 匯入函式庫 ---
import pandas as pd
import os
import json
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template_string, request, jsonify
import logging
from datetime import datetime
import yfinance as yf
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# --- 1. 全域設定與參數 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATABASE_URL = os.environ.get('DATABASE_URL')
API_SECRET_KEY = os.environ.get('API_SECRET_KEY')
FINMIND_API_TOKEN = os.environ.get('FINMIND_API_TOKEN')

pd.set_option('display.max_columns', None)
CASH = 1000000
ADD_ON_SHARES = 1000
MAX_POSITION_SHARES = 3000
STOP_LOSS_PCT = 0.15 # 15% 停損
TAKE_PROFIT_PCT = 0.30 # 30% 基本停利滿足點

# --- 2. 核心資料庫函式 (PostgreSQL 版) ---
def get_db_connection():
    if not DATABASE_URL: raise ValueError("DATABASE_URL 環境變數未設定！")
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def setup_database():
    logging.info("🚀 正在設定 PostgreSQL 資料庫...")
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
            cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", ('live_stock_id', '2330.TW'))
        conn.commit()
        logging.info("✅ 資料庫設定完成。")
    except Exception as e:
        logging.error(f"❌ 資料庫設定失敗: {e}")
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
            py_shares = int(shares)
            py_price = float(price)
            py_total_value = py_shares * py_price
            py_profit = float(profit) if profit is not None else None
            
            formatted_timestamp = timestamp.strftime('%Y-%m-%d %H:%M')
            sql = 'INSERT INTO trades (timestamp, stock_id, action, shares, price, total_value, profit) VALUES (%s, %s, %s, %s, %s, %s, %s)'
            cur.execute(sql, (formatted_timestamp, stock_id, action, py_shares, py_price, py_total_value, py_profit))
        conn.commit()
    finally:
        conn.close()
        
def log_performance(date, stock_id, asset_value):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            py_asset_value = float(asset_value)
            sql = 'INSERT INTO daily_performance (date, stock_id, asset_value) VALUES (%s, %s, %s) ON CONFLICT (date, stock_id) DO UPDATE SET asset_value = EXCLUDED.asset_value'
            cur.execute(sql, (str(date), stock_id, py_asset_value))
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
                trade_cost = float(trade['price']) * int(trade['shares'])
                old_total = portfolio['avg_cost'] * portfolio['position']
                new_total = old_total + trade_cost
                portfolio['position'] += int(trade['shares'])
                portfolio['cash'] -= trade_cost
                if portfolio['position'] > 0: portfolio['avg_cost'] = new_total / portfolio['position']
            elif "賣出" in trade['action']:
                portfolio['cash'] += float(trade['price']) * int(trade['shares'])
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
            logging.info(f"📈【執行買入】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}，價格 {price:.2f}")
    elif signal == "賣出":
        log_trade(timestamp, stock_id, "賣出訊號", 0, price)
        if portfolio['position'] > 0:
            shares_to_sell = portfolio['position']
            profit = (price - portfolio['avg_cost']) * shares_to_sell
            log_trade(timestamp, stock_id, "執行賣出", shares_to_sell, price, profit)
            logging.info(f"📉【執行賣出】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}，損益：{profit:,.2f}")
    elif signal == "持有":
        log_trade(timestamp, stock_id, "持有", 0, price)

def check_stop_loss(timestamp, price, portfolio, stock_id):
    if portfolio['position'] > 0:
        stop_loss_price = portfolio['avg_cost'] * (1 - STOP_LOSS_PCT)
        if price < stop_loss_price:
            shares_to_sell = portfolio['position']
            profit = (price - portfolio['avg_cost']) * shares_to_sell
            log_trade(timestamp, stock_id, "停損賣出", shares_to_sell, price, profit)
            logging.warning(f"💥【強制停損】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}!")
            return True
    return False

def check_take_profit(timestamp, price, ma50, portfolio, stock_id):
    if portfolio['position'] > 0:
        # 條件 1: 到達固定風險報酬比的停利點 (30%)
        take_profit_price = portfolio['avg_cost'] * (1 + TAKE_PROFIT_PCT)
        if price > take_profit_price:
            shares_to_sell = portfolio['position']
            profit = (price - portfolio['avg_cost']) * shares_to_sell
            log_trade(timestamp, stock_id, "獲利了結(滿足30%)", shares_to_sell, price, profit)
            logging.info(f"🎉【達成停利】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}! 滿足 30% 獲利目標。")
            return True
            
        # 條件 2: 波段跌破 MA50 且目前為帳面獲利狀態 (動態停利保本)
        if ma50 is not None and price < ma50 and price > portfolio['avg_cost']:
            shares_to_sell = portfolio['position']
            profit = (price - portfolio['avg_cost']) * shares_to_sell
            log_trade(timestamp, stock_id, "動態停利(跌破MA50)", shares_to_sell, price, profit)
            logging.info(f"🛡️【動態保本】時間 {timestamp.strftime('%Y-%m-%d %H:%M')}! 價格跌破季線(MA50)提前獲利了結。")
            return True
            
    return False

# --- ▼▼▼ 關鍵修改：獲取資料的邏輯升級與交易邏輯修改 ▼▼▼ ---
def get_historical_data(stock_id):
    # 下載近兩年(約 500 天)的資料以確保 MA200(20天前) 與 52-Week 高低點計算無誤
    ticker = yf.Ticker(stock_id)
    df = ticker.history(period="2y")
    if df.empty:
        return None
    
    # 統一小寫並整理欄位
    df.index = df.index.tz_convert('Asia/Taipei')
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
    })
    
    # 計算指標
    df['sma_50'] = df['close'].rolling(window=50).mean()
    df['sma_150'] = df['close'].rolling(window=150).mean()
    df['sma_200'] = df['close'].rolling(window=200).mean()
    
    # 計算 52-week(252交易日)高點與低點
    df['52w_high'] = df['high'].rolling(window=252).max()
    df['52w_low'] = df['low'].rolling(window=252).min()
    
    # 為了比較 MA200 是否斜率向上，取 20 天前的 MA200
    df['sma_200_20d_ago'] = df['sma_200'].shift(20)
    
    return df

def calculate_latest_signal(df):
    if df is None or len(df) < 5: 
        return "資料不足"
    
    # 取得最新與昨日資料
    today = df.iloc[-1]
    yesterday_signal = "持有"
    
    # 定義買入條件的函式，方便應用於整個 df 或單筆資料
    def is_buy_condition_met(row):
        try:
            cond1 = row['close'] > row['sma_150'] and row['close'] > row['sma_200']
            cond2 = row['sma_150'] > row['sma_200']
            cond3 = row['sma_200'] > row['sma_200_20d_ago']
            cond4 = row['sma_50'] > row['sma_150']
            cond5 = row['close'] > 1.25 * row['52w_low']
            cond6 = row['close'] > 0.75 * row['52w_high']
            return all([cond1, cond2, cond3, cond4, cond5, cond6])
        except Exception:
            return False

    # 必須是 "新突破" (昨日未滿足，今日滿足)
    yesterday_met = is_buy_condition_met(df.iloc[-2]) if len(df) >= 2 else False
    today_met = is_buy_condition_met(today)
    
    if today_met and not yesterday_met:
        return "買入"
    
    # 賣出邏輯已由 check_stop_loss (15%) 統一處理，不再這裡產生賣出訊號
    return "持有"

def get_latest_price_and_signal(stock_id):
    # 如果代號沒有後綴，預設加上 .TW 以符合台股 yfinance 格式
    if not stock_id.endswith('.TW') and not stock_id.endswith('.TWO'):
        stock_id = f"{stock_id}.TW"

    df = get_historical_data(stock_id)
    if df is None or df.empty:
        return None, None, "無法從 yfinance 獲取資料", None

    latest_price = df['close'].iloc[-1]
    latest_time = df.index[-1]
    latest_ma50 = df['sma_50'].iloc[-1]
    
    signal = calculate_latest_signal(df)
    return latest_price, latest_time, signal, latest_ma50
# --- ▲▲▲ 關鍵修改 ▲▲▲ ---

def run_trading_job():
    stock_id = get_setting('live_stock_id') or "2330.TW"
    try:
        # --- ▼▼▼ 關鍵修改：使用 check_timestamp 確保時間一致性 ▼▼▼ ---
        check_timestamp = pd.Timestamp.now(tz='Asia/Taipei')
        logging.info(f"🤖 API被觸發，開始檢查 {stock_id} at {check_timestamp.strftime('%Y-%m-%d %H:%M:%S')}...")
        
        latest_price, data_timestamp, signal, ma50 = get_latest_price_and_signal(stock_id)

        if latest_price is None: return {"status": "error", "message": "無法獲取最新價格資料"}
        if "失敗" in signal or "異常" in signal: return {"status": "error", "message": signal}
        
        logging.info(f"   - 資料時間: {data_timestamp.strftime('%Y-%m-%d %H:%M')}, 最新價格: {latest_price:.2f}, MA50: {ma50:.2f}, 日線訊號: {signal}")
        
        portfolio = get_current_portfolio(stock_id)
        
        # 1. 優先檢查停損
        stop_loss_triggered = check_stop_loss(check_timestamp, latest_price, portfolio, stock_id)
        if not stop_loss_triggered:
            # 2. 如果沒有停損，則檢查是否達到獲利了結點
            take_profit_triggered = check_take_profit(check_timestamp, latest_price, ma50, portfolio, stock_id)
            if not take_profit_triggered:
                # 3. 既沒停損也沒停利，才執行普通的進出場交易訊號
                execute_trade(check_timestamp, signal, latest_price, portfolio, stock_id)
        
        final_portfolio = get_current_portfolio(stock_id)
        total_asset = final_portfolio['cash'] + (final_portfolio['position'] * float(latest_price))
        log_performance(check_timestamp.date(), stock_id, total_asset)
        
        message = f"檢查完成。總資產: {total_asset:,.2f}"
        return {"status": "success", "message": message}
        # --- ▲▲▲ 關鍵修改 ▲▲▲ ---
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

# --- 4. Flask Web 應用 ---
app = Flask(__name__)
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
                    <div><label for="cron_time" class="block text-sm font-medium text-gray-300">自動執行時間</label><input type="text" id="cron_time" value="交易日 13:30 收盤後每天一次 (背景排程)" readonly class="mt-1 block w-full bg-gray-900 border-gray-600 rounded-md text-gray-400"></div>
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
                <div id="loading-spinner" class="hidden text-center py-10"><svg class="animate-spin h-8 w-8 text-white mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg><p class="mt-2 text-lg">回測執行中...</p></div>
            </section>
        </main>
    </div>
    <script>
        const tabButtons = { live: document.getElementById('tab-live'), backtest: document.getElementById('tab-backtest') };
        const contentSections = { live: document.getElementById('content-live'), backtest: document.getElementById('content-backtest') };
        let liveChart, backtestChart;
        const ITEMS_PER_PAGE = 5;
        let fullData = { live: { trades: [], currentPage: 1 }, backtest: { trades: [], currentPage: 1 } };

        Object.keys(tabButtons).forEach(tabId => {
            tabButtons[tabId].addEventListener('click', () => {
                Object.keys(tabButtons).forEach(innerId => {
                    tabButtons[innerId].classList.remove('active');
                    contentSections[innerId].classList.remove('active');
                });
                tabButtons[tabId].classList.add('active');
                contentSections[tabId].classList.add('active');
            });
        });

        function renderTablePage(type) {const tableId = `${type}-trades-table`;const tableBody = document.querySelector(`#${tableId} tbody`);tableBody.innerHTML = '';const data = fullData[type];const start = (data.currentPage - 1) * ITEMS_PER_PAGE;const end = start + ITEMS_PER_PAGE;const paginatedTrades = data.trades.slice(start, end);paginatedTrades.forEach(trade => {const isSignal = trade.action.includes('訊號') || trade.action === '持有';const rowClass = isSignal ? 'signal-row' : '';let actionClass = 'hold-action';if (trade.action.includes('買入')) { actionClass = 'buy-action'; } else if (trade.action.includes('賣出')) { actionClass = 'sell-action'; }const sharesText = (trade.action.includes('執行') || trade.action.includes('停損')) ? trade.shares : '-';const totalValueText = (trade.action.includes('執行') || trade.action.includes('停損')) ? parseFloat(trade.total_value).toFixed(2) : '-';const profitText = trade.profit !== null ? `<span class="${trade.profit > 0 ? 'buy-action' : 'sell-action'}">${parseFloat(trade.profit).toFixed(2)}</span>` : '-';const row = `<tr><td>${trade.timestamp}</td><td>${trade.stock_id}</td><td class="${actionClass}">${trade.action}</td><td>${sharesText}</td><td>${parseFloat(trade.price).toFixed(2)}</td><td>${totalValueText}</td><td>${profitText}</td></tr>`;tableBody.innerHTML += row;});renderPagination(type);}
        function renderPagination(type) {const container = document.getElementById(`${type}-pagination`);container.innerHTML = '';const data = fullData[type];const totalPages = Math.ceil(data.trades.length / ITEMS_PER_PAGE);if (totalPages <= 1) return;const prevButton = document.createElement('button');prevButton.innerText = '‹ 上一頁';prevButton.className = 'pagination-btn';prevButton.disabled = data.currentPage === 1;prevButton.onclick = () => {if (data.currentPage > 1) {data.currentPage--;renderTablePage(type);}};container.appendChild(prevButton);const pageInfo = document.createElement('span');pageInfo.className = 'text-gray-400';pageInfo.innerText = `第 ${data.currentPage} / ${totalPages} 頁`;container.appendChild(pageInfo);const nextButton = document.createElement('button');nextButton.innerText = '下一頁 ›';nextButton.className = 'pagination-btn';nextButton.disabled = data.currentPage === totalPages;nextButton.onclick = () => {if (data.currentPage < totalPages) {data.currentPage++;renderTablePage(type);}};container.appendChild(nextButton);}
        function drawChart(canvasId, chartData) {const chartCanvas = document.getElementById(canvasId);let chartInstance = canvasId === 'liveAssetChart' ? liveChart : backtestChart;if (chartInstance) { chartInstance.destroy(); }if (chartData.dates && chartData.dates.length > 0) {chartInstance = new Chart(chartCanvas.getContext('2d'), {type: 'line',data: {labels: chartData.dates,datasets: [{label: '總資產價值',data: chartData.values,borderColor: 'rgba(59, 130, 246, 1)',backgroundColor: 'rgba(59, 130, 246, 0.2)',borderWidth: 2, fill: true, tension: 0.1}]},options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: false, ticks: { color: '#9ca3af' } }, x: { ticks: { color: '#9ca3af' } } } }});if (canvasId === 'liveAssetChart') liveChart = chartInstance;else backtestChart = chartInstance;}}

        const liveData = {{ live_data | tojson | safe }};
        fullData.live.trades = liveData.trades;
        renderTablePage('live');
        drawChart('liveAssetChart', liveData.chart_data);
        
        const settingsStatusEl = document.getElementById('settings-status');
        
        document.getElementById('update-stock-btn').addEventListener('click', async () => {
            const newStockId = document.getElementById('live_stock_id').value.trim().toUpperCase();
            if (!newStockId) { alert('股票代號不能為空'); return; }
            settingsStatusEl.textContent = '更新標的中...';
            const settingsResponse = await fetch('/api/settings', {method: 'POST',headers: {'Content-Type': 'application/json'},body: JSON.stringify({ key: 'live_stock_id', value: newStockId })});
            if (settingsResponse.ok) {
                settingsStatusEl.textContent = '標的更新成功！正在獲取初始數據...';
                const triggerResponse = await fetch('/api/trigger-trade-check', {method: 'POST',headers: { 'Authorization': 'Bearer {{ api_secret_key }}' }});
                if (triggerResponse.ok) {
                    settingsStatusEl.textContent = '初始數據獲取成功！頁面將在 3 秒後刷新。';
                    setTimeout(() => window.location.reload(), 3000);
                } else { const errorResult = await triggerResponse.json(); settingsStatusEl.textContent = `設定已更新，但獲取數據失敗: ${errorResult.message}`;}
            } else { settingsStatusEl.textContent = '標的更新失敗！'; }
        });
        
        document.getElementById('update-cash-btn').addEventListener('click', async () => {
            const currentStockId = document.getElementById('live_stock_id').value;
            const newInitialCash = document.getElementById('live_initial_cash').value;
            if (!newInitialCash || parseInt(newInitialCash) <= 0) { alert('初始資金必須是正數'); return; }
            settingsStatusEl.textContent = '更新資金中...';
            const response = await fetch('/api/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ key: 'initial_cash', value: newInitialCash, stock_id: currentStockId })
            });
            if(response.ok) {
                settingsStatusEl.textContent = '初始資金更新成功！';
                setTimeout(() => settingsStatusEl.textContent = '', 3000);
            } else {
                settingsStatusEl.textContent = '資金更新失敗！';
            }
        });
        
        document.getElementById('manual-trigger-btn').addEventListener('click', async () => {settingsStatusEl.textContent = '手動觸發中...';const response = await fetch('/api/trigger-trade-check', {method: 'POST',headers: { 'Authorization': 'Bearer {{ api_secret_key }}' }});const result = await response.json();if(response.ok) {settingsStatusEl.textContent = `觸發成功！${result.message} 頁面將在 5 秒後刷新。`;setTimeout(() => window.location.reload(), 5000);} else {settingsStatusEl.textContent = `觸發失敗！${result.message}`;}});
        
        document.getElementById('backtest-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            document.getElementById('loading-spinner').classList.remove('hidden');
            document.getElementById('backtest-results').classList.add('hidden');
            const stockId = document.getElementById('stock_id').value;
            const startDate = document.getElementById('start_date').value;
            const endDate = document.getElementById('end_date').value;
            const initialCash = document.getElementById('backtest_initial_cash').value;

            const response = await fetch('/api/run-backtest', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    stock_id: stockId,
                    start_date: startDate,
                    end_date: endDate,
                    initial_cash: initialCash
                })
            });

            document.getElementById('loading-spinner').classList.add('hidden');
            if(response.ok) {
                const results = await response.json();
                drawChart('backtestAssetChart', results.chart_data);
                fullData.backtest.trades = results.trades;
                fullData.backtest.currentPage = 1;
                renderTablePage('backtest');
                document.getElementById('backtest-results').classList.remove('hidden');
            } else {
                try {
                    const errResult = await response.json();
                    alert('注意: ' + (errResult.error || errResult.message || '執行失敗'));
                } catch(err) {
                    alert('回測執行失敗，請檢查終端機日誌。');
                }
            }
        });
    </script>
</body>
</html>
"""

# --- 5. Flask 路由與邏輯 ---
def get_live_dashboard_data():
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            stock_id = get_setting('live_stock_id')
            stock_specific_cash_key = f"initial_cash_{stock_id}"
            initial_cash = get_setting(stock_specific_cash_key) or CASH
            cur.execute("SELECT * FROM trades WHERE stock_id = %s ORDER BY timestamp DESC", (stock_id,))
            trades = cur.fetchall()
            cur.execute("SELECT * FROM daily_performance WHERE stock_id = %s ORDER BY date ASC", (stock_id,))
            performance = cur.fetchall()
            latest_price, latest_signal = "N/A", "N/A"
            try:
                result = get_latest_price_and_signal(stock_id)
                if result[0] is not None: latest_price = result[0]
                if result[2] is not None: latest_signal = result[2]
            except Exception as e:
                logging.error(f"❌ 獲取儀表板即時數據時發生錯誤: {e}")
        if performance:
            total_asset = performance[-1]['asset_value']
        else:
            current_portfolio = get_current_portfolio(stock_id)
            total_asset = current_portfolio['cash']
        return {"chart_data": {'dates': [p['date'] for p in performance], 'values': [p['asset_value'] for p in performance]},"trades": [dict(row) for row in trades],"latest_price": latest_price,"latest_signal": latest_signal,"total_asset": total_asset,"stock_id": stock_id, "initial_cash": initial_cash}
    finally:
        conn.close()

@app.route('/')
def dashboard():
    live_data = get_live_dashboard_data()
    return render_template_string(HTML_TEMPLATE, live_data=live_data, api_secret_key=API_SECRET_KEY)

@app.route('/api/trigger-trade-check', methods=['POST'])
def trigger_trade_check():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {API_SECRET_KEY}": return jsonify({"status": "error", "message": "未經授權"}), 401
    result = run_trading_job()
    if result.get('status') == 'success': return jsonify(result), 200
    else: return jsonify(result), 500

@app.route('/api/run-backtest', methods=['POST'])
def handle_backtest():
    try:
        params = request.get_json()
        stock_id, start_date = params.get('stock_id', '2330.TW'), params.get('start_date', '2024-01-01')
        end_date = params.get('end_date') or pd.Timestamp.now().strftime('%Y-%m-%d')
        initial_cash = int(params.get('initial_cash', CASH))
        if not stock_id.endswith('.TW') and not stock_id.endswith('.TWO'):
            stock_id_query = f"{stock_id}.TW"
        else:
            stock_id_query = stock_id
            
        ticker = yf.Ticker(stock_id_query)
        # 多抓兩年的資料來計算指標，之後再過濾出 start_date 與 end_date
        extended_start = (pd.to_datetime(start_date) - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
        df_raw = ticker.history(start=extended_start, end=end_date)
        
        if df_raw.empty: return jsonify({"error": "無法從 yfinance 下載資料"}), 400
        
        df = df_raw[['Open', 'High', 'Low', 'Close', 'Volume']].rename(columns={
            'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
        })
        # 移掉時區以便比較日期
        if df.index.tz: df.index = df.index.tz_localize(None)
        
        df['sma_50'] = df['close'].rolling(window=50).mean()
        df['sma_150'] = df['close'].rolling(window=150).mean()
        df['sma_200'] = df['close'].rolling(window=200).mean()
        df['52w_high'] = df['high'].rolling(window=252).max()
        df['52w_low'] = df['low'].rolling(window=252).min()
        df['sma_200_20d_ago'] = df['sma_200'].shift(20)
        
        if df['sma_200'].isnull().all(): return jsonify({"error": "指標計算失敗（資料不足長度）"}), 400
        
        df['signal'] = "持有"
        df['is_buy'] = False
        
        def is_buy_condition(row):
            try:
                c1 = row['close'] > row['sma_150'] and row['close'] > row['sma_200']
                c2 = row['sma_150'] > row['sma_200']
                c3 = row['sma_200'] > row['sma_200_20d_ago']
                c4 = row['sma_50'] > row['sma_150']
                c5 = row['close'] > 1.25 * row['52w_low']
                c6 = row['close'] > 0.75 * row['52w_high']
                return all([c1, c2, c3, c4, c5, c6])
            except Exception:
                return False

        # Apply the buy condition row by row
        buy_mask = df.apply(is_buy_condition, axis=1)
        # Shift to find where it wasn't a buy yesterday but is today (new breakthrough)
        new_buy_mask = buy_mask & (~buy_mask.shift(1).fillna(False))
        df.loc[new_buy_mask, 'signal'] = "買入"
        
        # 過濾回真正要求的 start_date 到 end_date
        df = df.loc[start_date:end_date]
        
        backtest_portfolio = {'cash': initial_cash, 'position': 0, 'avg_cost': 0}
        daily_assets, trade_log = [], []
        insufficient_funds = False
        last_insufficient_price = 0
        
        for index, row in df.iterrows():
            price, signal, ma50 = row['close'], row['signal'], row['sma_50']
            action_taken = False
            
            # 優先檢查停損
            if backtest_portfolio['position'] > 0:
                stop_loss_price = backtest_portfolio['avg_cost'] * (1 - STOP_LOSS_PCT)
                take_profit_price = backtest_portfolio['avg_cost'] * (1 + TAKE_PROFIT_PCT)
                
                if price < stop_loss_price:
                    profit = (price - backtest_portfolio['avg_cost']) * backtest_portfolio['position']
                    trade_log.append({'timestamp': str(index.date()), 'stock_id': stock_id, 'action': '停損賣出', 'shares': backtest_portfolio['position'], 'price': price, 'total_value': price * backtest_portfolio['position'], 'profit': profit})
                    backtest_portfolio['cash'] += price * backtest_portfolio['position']
                    backtest_portfolio['position'], backtest_portfolio['avg_cost'] = 0, 0
                    action_taken = True
                elif price > take_profit_price:
                    profit = (price - backtest_portfolio['avg_cost']) * backtest_portfolio['position']
                    trade_log.append({'timestamp': str(index.date()), 'stock_id': stock_id, 'action': '獲利了結(滿足30%)', 'shares': backtest_portfolio['position'], 'price': price, 'total_value': price * backtest_portfolio['position'], 'profit': profit})
                    backtest_portfolio['cash'] += price * backtest_portfolio['position']
                    backtest_portfolio['position'], backtest_portfolio['avg_cost'] = 0, 0
                    action_taken = True
                elif price < ma50 and price > backtest_portfolio['avg_cost']:
                    profit = (price - backtest_portfolio['avg_cost']) * backtest_portfolio['position']
                    trade_log.append({'timestamp': str(index.date()), 'stock_id': stock_id, 'action': '動態停利(跌破MA50)', 'shares': backtest_portfolio['position'], 'price': price, 'total_value': price * backtest_portfolio['position'], 'profit': profit})
                    backtest_portfolio['cash'] += price * backtest_portfolio['position']
                    backtest_portfolio['position'], backtest_portfolio['avg_cost'] = 0, 0
                    action_taken = True
                    
            # 處理買進 (如果今天沒有停利/停損賣出才能買進，避免同一天買又賣)
            if not action_taken and signal == "買入" and backtest_portfolio['position'] < MAX_POSITION_SHARES:
                if backtest_portfolio['position'] == 0 or price > backtest_portfolio['avg_cost']:
                    if backtest_portfolio['cash'] >= price * ADD_ON_SHARES:
                        old_total = backtest_portfolio['avg_cost'] * backtest_portfolio['position']
                        new_total = old_total + (price * ADD_ON_SHARES)
                        backtest_portfolio['position'] += ADD_ON_SHARES
                        backtest_portfolio['cash'] -= price * ADD_ON_SHARES
                        backtest_portfolio['avg_cost'] = new_total / backtest_portfolio['position']
                        trade_log.append({'timestamp': str(index.date()), 'stock_id': stock_id, 'action': '執行買入', 'shares': ADD_ON_SHARES, 'price': price, 'total_value': price * ADD_ON_SHARES, 'profit': None})
                    else:
                        insufficient_funds = True
                        last_insufficient_price = price
            
            daily_assets.append(backtest_portfolio['cash'] + (backtest_portfolio['position'] * price))

        if len(trade_log) == 0 and insufficient_funds:
            return jsonify({"error": f"回測期間出現買入訊號，但初始資金 ({initial_cash:,.0f}) 不足買進基本單位 (需約 {last_insufficient_price*ADD_ON_SHARES:,.0f} 元)。請手動調高初始資金！"}), 400

        results = {"chart_data": {"dates": [d.strftime('%Y-%m-%d') for d in df.index],"values": daily_assets},"trades": trade_log}
        return jsonify(results)
    except Exception as e:
        logging.error(f"回測 API 發生錯誤: {e}")
        logging.error(traceback.format_exc())
        return jsonify({"error": "回測時發生內部錯誤"}), 500

@app.route('/api/settings', methods=['POST'])
def update_settings_api():
    data = request.get_json()
    key, value = data.get('key'), data.get('value')
    if not key or not value: return jsonify({"status": "error", "message": "缺少 key 或 value"}), 400
    if key == 'initial_cash':
        stock_id = data.get('stock_id')
        if not stock_id:
            return jsonify({"status": "error", "message": "更新初始資金時必須提供 stock_id"}), 400
        db_key = f"initial_cash_{stock_id}"
    else:
        db_key = key
    try:
        update_setting(db_key, value)
        return jsonify({"status": "success", "message": f"設定 {db_key} 已更新為 {value}"}), 200
    except Exception as e:
        logging.error(f"更新設定 API 發生錯誤: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Taipei'))
    # 設定週一到週五的 13:30 觸發
    scheduler.add_job(run_trading_job, 'cron', day_of_week='mon-fri', hour=13, minute=30)
    scheduler.start()
    logging.info("⏰ APScheduler 背景定時任務已啟動 (排程時間: 每週一至週五 13:30)")

def create_app():
    with app.app_context():
        setup_database()
        start_scheduler() # 啟動排程
    return app

if __name__ == '__main__':
    if not DATABASE_URL:
        logging.error("❌ 錯誤：未設定 DATABASE_URL 環境變數，無法啟動。")
    else:
        setup_database()
        start_scheduler()
        app.run(host='0.0.0.0', port=5001, debug=True)