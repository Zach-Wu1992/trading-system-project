# --- 匯入函式庫 ---
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import sqlite3
import time
from apscheduler.schedulers.blocking import BlockingScheduler

# --- 1. 全域設定與參數 ---
DB_NAME = 'trading_dashboard.db' # 為了乾淨，我們用一個全新的資料庫
pd.set_option('display.max_columns', None)
CASH = 1000000
STOCK_ID = "2308.TW"
ADD_ON_SHARES = 1000
MAX_POSITION_SHARES = 3000
STOP_LOSS_PCT = 0.02

portfolio = {
    'cash': CASH,
    'position': 0,
    'avg_cost': 0,
}

# --- 2. 核心函式 ---
def setup_database(conn):
    cursor = conn.cursor()
    # 建立 trades 資料表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, stock_id TEXT NOT NULL,
            action TEXT NOT NULL, shares INTEGER NOT NULL, price REAL NOT NULL,
            total_value REAL NOT NULL, profit REAL
        )
    ''')
    # <--- 新增：建立每日績效資料表 ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_performance (
            date TEXT PRIMARY KEY,
            asset_value REAL NOT NULL
        )
    ''')
    conn.commit()
    print("✅ 即時交易資料庫設定完成。")

def log_trade(conn, timestamp, stock_id, action, shares, price, profit=None):
    # (此函式不變)
    cursor = conn.cursor()
    total_value = shares * price
    sql = 'INSERT INTO trades (timestamp, stock_id, action, shares, price, total_value, profit) VALUES (?, ?, ?, ?, ?, ?, ?)'
    cursor.execute(sql, (str(timestamp.date()), stock_id, action, shares, price, total_value, profit))
    conn.commit()

# <--- 新增：記錄每日績效的函式 ---
def log_performance(conn, date, asset_value):
    cursor = conn.cursor()
    # 使用 INSERT OR REPLACE，如果同一天有多筆紀錄，會用最新的覆蓋
    sql = 'INSERT OR REPLACE INTO daily_performance (date, asset_value) VALUES (?, ?)'
    cursor.execute(sql, (str(date), asset_value))
    conn.commit()

def execute_trade(conn, timestamp, signal, price):
    # (此函式不變)
    if signal == "買入":
        if portfolio['position'] >= MAX_POSITION_SHARES: return
        if portfolio['position'] > 0 and price <= portfolio['avg_cost']: return
        trade_cost = price * ADD_ON_SHARES
        if portfolio['cash'] >= trade_cost:
            old_total = portfolio['avg_cost'] * portfolio['position']
            new_total = old_total + trade_cost
            portfolio['position'] += ADD_ON_SHARES
            portfolio['cash'] -= trade_cost
            portfolio['avg_cost'] = new_total / portfolio['position']
            print(f"📈【執行買入】時間 {timestamp.date()}，價格 {price:.2f}")
            log_trade(conn, timestamp, STOCK_ID, "買入", ADD_ON_SHARES, price)
    elif signal == "賣出":
        if portfolio['position'] > 0:
            shares_to_sell = portfolio['position']
            profit = (price - portfolio['avg_cost']) * shares_to_sell
            portfolio['cash'] += price * shares_to_sell
            portfolio['position'] = 0
            portfolio['avg_cost'] = 0
            print(f'📉【訊號賣出】時間 {timestamp.date()}，價格 {price:.2f}，損益：{profit:,.2f}')
            log_trade(conn, timestamp, STOCK_ID, "訊號賣出", shares_to_sell, price, profit)

def check_stop_loss(conn, timestamp, price):
    # (此函式不變)
    if portfolio['position'] > 0:
        stop_loss_price = portfolio['avg_cost'] * (1 - STOP_LOSS_PCT)
        if price < stop_loss_price:
            shares_to_sell = portfolio['position']
            profit = (price - portfolio['avg_cost']) * shares_to_sell
            portfolio['cash'] += price * shares_to_sell
            portfolio['position'] = 0
            portfolio['avg_cost'] = 0
            print(f'💥【強制停損】時間 {timestamp.date()}，價格 {price:.2f}!')
            log_trade(conn, timestamp, STOCK_ID, "停損賣出", shares_to_sell, price, profit)
            return True
    return False

def load_portfolio_state(conn):
    # (此函式不變)
    global portfolio
    cursor = conn.cursor()
    cursor.execute("SELECT action, shares, price FROM trades ORDER BY timestamp ASC")
    trades = cursor.fetchall()
    temp_portfolio = {'cash': CASH, 'position': 0, 'avg_cost': 0}
    for trade in trades:
        action, shares, price = trade
        if action == "買入":
            trade_cost = price * shares
            old_total = temp_portfolio['avg_cost'] * temp_portfolio['position']
            new_total = old_total + trade_cost
            temp_portfolio['position'] += shares
            temp_portfolio['cash'] -= trade_cost
            if temp_portfolio['position'] > 0:
                 temp_portfolio['avg_cost'] = new_total / temp_portfolio['position']
        elif "賣出" in action:
            trade_revenue = price * shares
            temp_portfolio['cash'] += trade_revenue
            temp_portfolio['position'] = 0
            temp_portfolio['avg_cost'] = 0
    portfolio = temp_portfolio
    print("✅ 已從資料庫還原倉位狀態。")
    print(f"   目前狀態: 現金 {portfolio['cash']:,.2f}, 持股 {portfolio['position']} 股, 均價 {portfolio['avg_cost']:.2f}")

# --- 3. 機器人主任務函式 ---
def run_trading_job():
    print("\n" + "="*50)
    print(f"🤖 [{pd.Timestamp.now(tz='Asia/Taipei').strftime('%Y-%m-%d %H:%M:%S')}] 開始執行交易檢查...")
    
    conn = sqlite3.connect(DB_NAME)
    try:
        df = yf.download(STOCK_ID, period="40d", interval="1d", progress=False)
        if df.empty: return

        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        df.columns = ['open', 'high', 'low', 'close', 'volume']
        
        df['sma_5'] = df.ta.sma(length=5, close='close')
        df['sma_20'] = df.ta.sma(length=20, close='close')

        if 'sma_20' not in df.columns or df['sma_20'].isnull().all(): return

        latest_data = df.iloc[-2:]
        yesterday_sma5 = latest_data['sma_5'].iloc[0]
        yesterday_sma20 = latest_data['sma_20'].iloc[0]
        today_sma5 = latest_data['sma_5'].iloc[1]
        today_sma20 = latest_data['sma_20'].iloc[1]
        
        signal = "持有"
        if yesterday_sma5 < yesterday_sma20 and today_sma5 > today_sma20:
            signal = "買入"
        elif yesterday_sma5 > yesterday_sma20 and today_sma5 < today_sma20:
            signal = "賣出"

        current_price = df['close'].iloc[-1]
        current_time = df.index[-1]
        
        print(f"   最新價格 ({current_time.date()}): {current_price:.2f}, 訊號: {signal}")

        stop_loss_triggered = check_stop_loss(conn, current_time, current_price)
        if not stop_loss_triggered:
            execute_trade(conn, current_time, signal, current_price)

        # <--- 新增：在每日檢查結束後，計算並記錄總資產 ---
        market_value = portfolio['position'] * current_price
        total_asset = portfolio['cash'] + market_value
        log_performance(conn, current_time.date(), total_asset)
        
        print(f"   執行後狀態: 現金 {portfolio['cash']:,.2f}, 持股 {portfolio['position']} 股, 總資產 {total_asset:,.2f}")

    except Exception as e:
        print(f"❌ 執行時發生錯誤: {e}")
    finally:
        conn.close()
        print(f"🤖 [{pd.Timestamp.now(tz='Asia/Taipei').strftime('%Y-%m-%d %H:%M:%S')}] 本次檢查結束。")

# --- 4. 程式主進入點 ---
if __name__ == "__main__":
    conn = sqlite3.connect(DB_NAME)
    setup_database(conn)
    load_portfolio_state(conn)
    conn.close()

    scheduler = BlockingScheduler(timezone='Asia/Taipei')
    # 台灣股市收盤後執行，例如每天下午 2:00
    scheduler.add_job(run_trading_job, 'cron', hour=14, minute=0)
    
    print("🚀 交易機器人已啟動，等待每日排程觸發 (下午 2:00)...")
    print("💡 您可以按下 Ctrl+C 來停止程式。")
    
    try:
        # run_trading_job() # 啟動時不再立刻執行，等待排程
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("🛑 交易機器人已停止。")

