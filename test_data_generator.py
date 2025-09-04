import sqlite3
import random
import pandas as pd

# --- 設定 ---
# 確保這個檔案名稱與您的 dashboard.py 和 realtime_bot.py 中使用的名稱一致
DB_NAME = 'trading_dashboard.db'
STOCK_ID = "2308.TW"
INITIAL_CASH = 1000000

def generate_test_data():
    """
    清除舊數據，生成全新的測試數據，並驗證寫入結果。
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- 1. 清除所有舊的數據，確保一個乾淨的開始 ---
    print("🧹 正在清除舊的測試數據...")
    cursor.execute("DROP TABLE IF EXISTS trades")
    cursor.execute("DROP TABLE IF EXISTS daily_performance")
    cursor.execute('''
        CREATE TABLE trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, stock_id TEXT NOT NULL,
            action TEXT NOT NULL, shares INTEGER NOT NULL, price REAL NOT NULL,
            total_value REAL NOT NULL, profit REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE daily_performance (
            date TEXT PRIMARY KEY,
            asset_value REAL NOT NULL
        )
    ''')
    conn.commit()
    print("✅ 舊數據已清除並重新建立表格。")

    # --- 2. 生成每日績效數據 (用於績效曲線圖) ---
    print("📈 正在生成 30 天的每日績效數據...")
    dates = pd.date_range(end=pd.Timestamp.today(), periods=30)
    asset_values = []
    current_asset = INITIAL_CASH
    for date in dates:
        current_asset += random.uniform(-15000, 20000)
        asset_values.append((date.strftime('%Y-%m-%d'), current_asset))
    
    cursor.executemany("INSERT INTO daily_performance (date, asset_value) VALUES (?, ?)", asset_values)
    conn.commit()
    print(f"✅ 已請求生成 {len(asset_values)} 筆績效紀錄。")

    # --- 3. 生成交易歷史數據 (用於交易列表) ---
    print("🧾 正在生成模擬交易歷史紀錄...")
    mock_trades = [
        ('2025-08-15', STOCK_ID, '買入', 1000, 350.50, 350500, None),
        ('2025-08-20', STOCK_ID, '買入', 1000, 355.00, 355000, None),
        ('2025-08-28', STOCK_ID, '訊號賣出', 2000, 365.75, 731500, 20500.00),
        ('2025-09-02', STOCK_ID, '買入', 1000, 360.00, 360000, None),
        ('2025-09-04', STOCK_ID, '停損賣出', 1000, 352.00, 352000, -8000.00)
    ]
    sql = 'INSERT INTO trades (timestamp, stock_id, action, shares, price, total_value, profit) VALUES (?, ?, ?, ?, ?, ?, ?)'
    cursor.executemany(sql, mock_trades)
    conn.commit()
    print(f"✅ 已請求生成 {len(mock_trades)} 筆交易紀錄。")

    # --- 4. 新增：驗證數據是否成功寫入 ---
    print("\n" + "="*30)
    print("🔍 正在驗證資料庫中的數據...")
    
    # 驗證 daily_performance
    cursor.execute("SELECT COUNT(*) FROM daily_performance")
    perf_count = cursor.fetchone()[0]
    if perf_count > 0:
        print(f"✔️  成功驗證：在 'daily_performance' 表中找到 {perf_count} 筆紀錄。")
    else:
        print(f"❌  驗證失敗：在 'daily_performance' 表中找不到任何紀錄！")

    # 驗證 trades
    cursor.execute("SELECT COUNT(*) FROM trades")
    trade_count = cursor.fetchone()[0]
    if trade_count > 0:
        print(f"✔️  成功驗證：在 'trades' 表中找到 {trade_count} 筆紀錄。")
    else:
        print(f"❌  驗證失敗：在 'trades' 表中找不到任何紀錄！")
    print("="*30)

    conn.close()
    
    if perf_count > 0 and trade_count > 0:
        print("\n🎉 測試數據生成並驗證完畢！現在您可以啟動 dashboard.py 來查看結果了。")
    else:
        print("\n⚠️ 數據生成似乎有問題，請檢查上面的驗證訊息。")

# --- 程式進入點 ---
if __name__ == '__main__':
    generate_test_data()

        

