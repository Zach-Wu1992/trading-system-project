# -*- coding: utf-8 -*-
# --- 匯入函式庫 ---
import pandas_datareader.data as web
import pandas as pd
import pandas_ta as ta
import os
import json
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template_string, request, jsonify
import requests # <--- 新增 requests

# --- 1. 全域設定與參數 ---
DATABASE_URL = os.environ.get('DATABASE_URL')
API_SECRET_KEY = os.environ.get('API_SECRET_KEY', "my_super_secret_key_123_for_local_dev")
TIINGO_API_KEY = os.environ.get('326146dea48b84b15273e001ad341085f4aa02ca')

pd.set_option('display.max_columns', None)
CASH = 1000000
ADD_ON_SHARES = 1000
MAX_POSITION_SHARES = 3000
STOP_LOSS_PCT = 0.02

# --- ▼▼▼ 關鍵修正：建立帶有偽裝標頭的 Session ▼▼▼ ---
session = requests.Session()
session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
# --- ▲▲▲ 關鍵修正 ▲▲▲ ---


# --- 2. 核心資料庫函式 (保持不變) ---
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
                    date TEXT NOT NULL, stock_id TEXT NOT NULL,
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

def clean_df(df_raw):
    if df_raw is None or df_raw.empty: return None
    df = df_raw.copy()
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    rename_map = {}
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in df.columns:
        if str(col).capitalize() in required_cols: rename_map[col] = str(col).lower()
    if len(rename_map) < len(required_cols): return None
    df.rename(columns=rename_map, inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']]
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
    if not TIINGO_API_KEY:
        return None, None, "Tiingo API 金鑰未設定"
    
    latest_price, latest_time = None, None
    signal = "未知錯誤"

    try:
        # Tiingo 的即時資料有 15 分鐘延遲，所以直接下載日線資料
        # 下載最近 40 天的資料來計算 SMA
        df_daily_raw = web.DataReader(stock_id, 'tiingo', start='2024-01-01', api_key=TIINGO_API_KEY)
        
        # 由於 Tiingo 回傳的資料可能不是最新的，這裡需要額外判斷
        # Tiingo 回傳的 DataFrame 索引是日期，且資料是最新到最舊
        df_daily = clean_df(df_daily_raw.sort_index()) # 確保資料由舊到新
        
        if df_daily is None or df_daily.empty:
            print(f"❌ 無法獲取或清理 {stock_id} 的日線歷史資料。")
            signal = "日線資料異常"
        else:
            latest_price = df_daily['close'].iloc[-1]
            latest_time = df_daily.index[-1]
            
            # 計算 SMA 指標
            df_daily['sma_5'] = df_daily.ta.sma(length=5, close='close')
            df_daily['sma_20'] = df_daily.ta.sma(length=20, close='close')
            
            if df_daily['sma_20'].isnull().all():
                print(f"❌ {stock_id} 的 SMA 指標計算失敗。")
                signal = "指標計算失敗"
            else:
                signal = calculate_latest_signal(df_daily)

    except Exception as e:
        print(f"❌ 在下載或處理 {stock_id} 的資料時發生意外錯誤: {e}")
        traceback.print_exc()
        signal = "下載發生錯誤"
    
    return latest_price, latest_time, signal

def run_trading_job():
    stock_id = get_setting('live_stock_id') or "2308.TW"
    try:
        # 使用更新後的函式
        latest_price, latest_time, signal = get_latest_price_and_signal(stock_id)
        
        if latest_price is None:
            # 在這裡直接處理無法獲取價格的錯誤
            message = f"❌ 無法獲取 {stock_id} 的最新價格資料。交易檢查已跳過。原因: {signal}"
            print(message)
            return {"status": "error", "message": message}
            
        if "錯誤" in signal or "異常" in signal:
            # 在這裡處理訊號計算的錯誤
            message = f"❌ {stock_id} 的訊號計算失敗。原因: {signal}"
            print(message)
            return {"status": "error", "message": message}

        portfolio = get_current_portfolio(stock_id)
        stop_loss_triggered = check_stop_loss(latest_time, latest_price, portfolio, stock_id)
        
        if not stop_loss_triggered:
            execute_trade(latest_time, signal, latest_price, portfolio, stock_id)
            
        final_portfolio = get_current_portfolio(stock_id)
        total_asset = final_portfolio['cash'] + (final_portfolio['position'] * latest_price)
        log_performance(latest_time.date(), stock_id, total_asset)
        
        message = f"✅ {stock_id} 交易檢查完成。總資產: {total_asset:,.2f}"
        print(message)
        return {"status": "success", "message": message}
        
    except Exception as e:
        message = f"❌ 運行交易任務時發生意外錯誤: {e}"
        print(message)
        traceback.print_exc()
        return {"status": "error", "message": message}

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
                alert('回測執行失敗，請檢查終端機日誌。');
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
            cur.execute("SELECT value FROM settings WHERE key = %s", ('live_stock_id',))
            stock_id_result = cur.fetchone()
            stock_id = stock_id_result['value'] if stock_id_result else '2308.TW'

            stock_specific_cash_key = f"initial_cash_{stock_id}"
            cur.execute("SELECT value FROM settings WHERE key = %s", (stock_specific_cash_key,))
            initial_cash_result = cur.fetchone()
            initial_cash = initial_cash_result['value'] if initial_cash_result else CASH

            cur.execute("SELECT * FROM trades WHERE stock_id = %s ORDER BY timestamp DESC", (stock_id,))
            trades = cur.fetchall()
            cur.execute("SELECT * FROM daily_performance WHERE stock_id = %s ORDER BY date ASC", (stock_id,))
            performance = cur.fetchall()

            latest_price, latest_signal = "N/A", "N/A"
            try:
                latest_price, _, latest_signal = get_latest_price_and_signal(stock_id)
                if latest_price is None: latest_price = "N/A"
                if latest_signal is None: latest_signal = "N/A"
            except Exception as e:
                print(f"❌ 獲取儀表板即時數據時發生錯誤: {e}")

            if performance:
                total_asset = performance[-1]['asset_value']
            else:
                current_portfolio = get_current_portfolio(stock_id)
                total_asset = current_portfolio['cash']
            
            return {
                "chart_data": {'dates': [p['date'] for p in performance], 'values': [p['asset_value'] for p in performance]},
                "trades": [dict(row) for row in trades],
                "latest_price": latest_price,
                "latest_signal": latest_signal,
                "total_asset": total_asset,
                "stock_id": stock_id, 
                "initial_cash": initial_cash
            }
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
    params = request.get_json()
    stock_id, start_date = params.get('stock_id', '2330.TW'), params.get('start_date', '2024-01-01')
    end_date = params.get('end_date') or pd.Timestamp.now().strftime('%Y-%m-%d')
    initial_cash = int(params.get('initial_cash', CASH))
    if not end_date: end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
    
    try:
        df_raw = web.DataReader(stock_id, 'tiingo', start=start_date, end=end_date, api_key=TIINGO_API_KEY)
        df = clean_df(df_raw.sort_index()) # 確保資料由舊到新
        if df is None or df.empty:
            return jsonify({"error": "無法下載或清理資料"}), 400
    except Exception as e:
        return jsonify({"error": f"資料下載失敗: {e}"}), 400
    
    df['signal'] = "持有"
    yesterday_sma5, yesterday_sma20 = df['sma_5'].shift(1), df['sma_20'].shift(1)
    buy_conditions = (df['sma_5'] > df['sma_20']) & (yesterday_sma5 < yesterday_sma20)
    sell_conditions = (df['sma_5'] < df['sma_20']) & (yesterday_sma5 > yesterday_sma20)
    df.loc[buy_conditions, 'signal'] = "買入"
    df.loc[sell_conditions, 'signal'] = "賣出"
    
    backtest_portfolio = {'cash': initial_cash, 'position': 0, 'avg_cost': 0}
    daily_assets, trade_log = [], []
    for index, row in df.iterrows():
        price, signal = row['close'], row['signal']
        if backtest_portfolio['position'] > 0:
            stop_loss_price = backtest_portfolio['avg_cost'] * (1 - STOP_LOSS_PCT)
            if price < stop_loss_price:
                profit = (price - backtest_portfolio['avg_cost']) * backtest_portfolio['position']
                trade_log.append({'timestamp': str(index.date()), 'stock_id': stock_id, 'action': '停損賣出', 'shares': backtest_portfolio['position'], 'price': price, 'total_value': price * backtest_portfolio['position'], 'profit': profit})
                backtest_portfolio['cash'] += price * backtest_portfolio['position']
                backtest_portfolio['position'], backtest_portfolio['avg_cost'] = 0, 0
        if signal == "買入" and backtest_portfolio['position'] < MAX_POSITION_SHARES:
            if backtest_portfolio['position'] == 0 or price > backtest_portfolio['avg_cost']:
                if backtest_portfolio['cash'] >= price * ADD_ON_SHARES:
                    old_total = backtest_portfolio['avg_cost'] * backtest_portfolio['position']
                    new_total = old_total + (price * ADD_ON_SHARES)
                    backtest_portfolio['position'] += ADD_ON_SHARES
                    backtest_portfolio['cash'] -= price * ADD_ON_SHARES
                    backtest_portfolio['avg_cost'] = new_total / backtest_portfolio['position']
                    trade_log.append({'timestamp': str(index.date()), 'stock_id': stock_id, 'action': '買入', 'shares': ADD_ON_SHARES, 'price': price, 'total_value': price * ADD_ON_SHARES, 'profit': None})
        elif signal == "賣出" and backtest_portfolio['position'] > 0:
            profit = (price - backtest_portfolio['avg_cost']) * backtest_portfolio['position']
            trade_log.append({'timestamp': str(index.date()), 'stock_id': stock_id, 'action': '訊號賣出', 'shares': backtest_portfolio['position'], 'price': price, 'total_value': price * backtest_portfolio['position'], 'profit': profit})
            backtest_portfolio['cash'] += price * backtest_portfolio['position']
            backtest_portfolio['position'], backtest_portfolio['avg_cost'] = 0, 0
        daily_assets.append(backtest_portfolio['cash'] + (backtest_portfolio['position'] * price))
    results = {"chart_data": {"dates": [d.strftime('%Y-%m-%d') for d in df.index],"values": daily_assets},"trades": trade_log}
    return jsonify(results)

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
        return jsonify({"status": "error", "message": str(e)}), 500

def create_app():
    # 這個函式是給 Gunicorn 用的
    with app.app_context():
        setup_database()
    return app

# --- 6. 程式主進入點 (僅供本地開發使用) ---
if __name__ == '__main__':
    setup_database()
    app.run(host='0.0.0.0', port=5001, debug=True)

