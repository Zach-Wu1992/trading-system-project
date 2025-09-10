import sqlite3
import random
import pandas as pd
import os

# --- 設定 ---
# 確保這個檔案名稱與您的 app.py 中使用的名稱一致
DB_NAME = 'trading_system_final.db' 
STOCK_ID_1 = "2308.TW" # 預設監控標的
STOCK_ID_2 = "2317.TW" # 另一個測試標的
INITIAL_CASH_1 = 1000000
INITIAL_CASH_2 = 1500000

def generate_test_data():
    """
    清除舊數據，並生成全新的、用於測試的假數據。
    """
    # 如果資料庫存在，先刪除，確保完全乾淨
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print(f"🧹 舊資料庫 '{DB_NAME}' 已刪除。")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- 1. 重新建立所有表格 ---
    print("再建立所有表格...")
    # 建立 trades 資料表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, stock_id TEXT NOT NULL,
            action TEXT NOT NULL, shares INTEGER NOT NULL, price REAL NOT NULL,
            total_value REAL NOT NULL, profit REAL
        )
    ''')
    # 建立每日績效資料表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_performance (
            date TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            asset_value REAL NOT NULL,
            PRIMARY KEY (date, stock_id)
        )
    ''')
    # 建立設定資料表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    conn.commit()
    print("✅ 表格建立完成。")

    # --- 2. 寫入設定數據 ---
    print("📝 正在寫入設定數據...")
    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ('live_stock_id', STOCK_ID_1))
    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (f'initial_cash_{STOCK_ID_1}', str(INITIAL_CASH_1)))
    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (f'initial_cash_{STOCK_ID_2}', str(INITIAL_CASH_2)))
    conn.commit()
    print("✅ 設定數據已寫入。")

    # --- 3. 生成每日績效數據 ---
    print(f"📈 正在為 {STOCK_ID_1} 生成績效數據...")
    dates = pd.date_range(end=pd.Timestamp.now(), periods=30)
    asset_values = []
    current_asset = INITIAL_CASH_1
    for date in dates:
        current_asset += random.uniform(-15000, 20000)
        asset_values.append((date.strftime('%Y-%m-%d'), STOCK_ID_1, current_asset))
    
    cursor.executemany("INSERT INTO daily_performance (date, stock_id, asset_value) VALUES (?, ?, ?)", asset_values)
    conn.commit()
    print(f"✅ 已為 {STOCK_ID_1} 生成 {len(asset_values)} 筆績效紀錄。")

    # --- 4. 生成交易歷史數據 ---
    print(f"🧾 正在為 {STOCK_ID_1} 生成交易歷史紀錄...")
    mock_trades = [
        # (timestamp, stock_id, action, shares, price, total_value, profit)
        ('2025-08-15 10:00', STOCK_ID_1, '買入訊號', 0, 350.50, 0, None),
        ('2025-08-15 10:00', STOCK_ID_1, '執行買入', 1000, 350.50, 350500, None),
        ('2025-08-28 11:00', STOCK_ID_1, '賣出訊號', 0, 365.75, 0, None),
        ('2025-08-28 11:00', STOCK_ID_1, '執行賣出', 1000, 365.75, 365750, 15250.00),
        ('2025-09-02 09:00', STOCK_ID_1, '持有', 0, 360.00, 0, None)
    ]
    
    sql = 'INSERT INTO trades (timestamp, stock_id, action, shares, price, total_value, profit) VALUES (?, ?, ?, ?, ?, ?, ?)'
    cursor.executemany(sql, mock_trades)
    conn.commit()
    print(f"✅ 已為 {STOCK_ID_1} 生成 {len(mock_trades)} 筆交易紀錄。")

    conn.close()
    print("\n🎉 測試數據生成完畢！現在您可以啟動 app.py 來查看結果了。")

# --- 程式進入點 ---
if __name__ == '__main__':
    generate_test_data()

