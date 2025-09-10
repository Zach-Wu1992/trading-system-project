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
from FinMind.data import FinMindApi # <--- 使用 FinMind

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
            cur.execute(''' CREATE TABLE IF NOT EXISTS trades ( trade_id SERIAL PRIMARY KEY, timestamp TEXT NOT NULL, stock_id TEXT NOT NULL, action TEXT NOT NULL, shares INTEGER NOT NULL, price REAL NOT NULL, total_value REAL NOT NULL, profit REAL ) ''')
            cur.execute(''' CREATE TABLE IF NOT EXISTS daily_performance ( date TEXT NOT NULL, stock_id TEXT NOT NULL, asset_value REAL NOT NULL, PRIMARY KEY (date, stock_id) ) ''')
            cur.execute(''' CREATE TABLE IF NOT EXISTS settings ( key TEXT PRIMARY KEY, value TEXT NOT NULL ) ''')
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
    if not all(col in df.columns for col in required_cols): return None
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
HTML_TEMPLATE = """ ... """ # (HTML 模板不變，此處省略)

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
    
    if not fm: return jsonify({"error": "FinMind 未初始化，請檢查 API Token"}), 500
    
    df_raw = fm.get_data(dataset="TaiwanStockPrice", data_id=stock_id.replace('.TW', ''), start_date=start_date, end_date=end_date)
    df = clean_df_finmind(df_raw)
    if df is None: return jsonify({"error": "無法下載或清理資料"}), 400
    
    df['sma_5'] = df.ta.sma(length=5, close='close')
    df['sma_20'] = df.ta.sma(length=20, close='close')
    if df['sma_20'].isnull().all(): return jsonify({"error": "指標計算失敗"}), 400
    
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
    if not DATABASE_URL:
        print("❌ 錯誤：未設定 DATABASE_URL 環境變數，無法在本地啟動。")
    else:
        setup_database()
        app.run(host='0.0.0.0', port=5001, debug=True)

