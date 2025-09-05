# --- 匯入函式庫 ---
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import sqlite3
import os
import json
from flask import Flask, render_template_string, request, jsonify

# --- 1. 全域設定與參數 ---
os.chdir(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = 'trading_system.db'
API_SECRET_KEY = "my_super_secret_key_123"
pd.set_option('display.max_columns', None)
CASH = 1000000
STOCK_ID = "2308.TW"
ADD_ON_SHARES = 1000
MAX_POSITION_SHARES = 3000
STOP_LOSS_PCT = 0.02

# --- 2. 核心交易與資料庫函式 (與前一版相同，保持不變) ---
def setup_database(conn):
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, stock_id TEXT NOT NULL,
            action TEXT NOT NULL, shares INTEGER NOT NULL, price REAL NOT NULL,
            total_value REAL NOT NULL, profit REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_performance (
            date TEXT PRIMARY KEY,
            asset_value REAL NOT NULL
        )
    ''')
    conn.commit()

def log_trade(conn, timestamp, stock_id, action, shares, price, profit=None):
    cursor = conn.cursor()
    total_value = shares * price
    sql = 'INSERT INTO trades (timestamp, stock_id, action, shares, price, total_value, profit) VALUES (?, ?, ?, ?, ?, ?, ?)'
    cursor.execute(sql, (str(timestamp.date()), stock_id, action, shares, price, total_value, profit))
    conn.commit()

def log_performance(conn, date, asset_value):
    cursor = conn.cursor()
    sql = 'INSERT OR REPLACE INTO daily_performance (date, asset_value) VALUES (?, ?)'
    cursor.execute(sql, (str(date), asset_value))
    conn.commit()

def get_current_portfolio(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT action, shares, price FROM trades ORDER BY timestamp ASC")
    trades = cursor.fetchall()
    portfolio = {'cash': CASH, 'position': 0, 'avg_cost': 0}
    for trade in trades:
        action, shares, price = trade
        if action == "買入":
            trade_cost = price * shares
            old_total = portfolio['avg_cost'] * portfolio['position']
            new_total = old_total + trade_cost
            portfolio['position'] += shares
            portfolio['cash'] -= trade_cost
            if portfolio['position'] > 0:
                 portfolio['avg_cost'] = new_total / portfolio['position']
        elif "賣出" in action:
            portfolio['cash'] += price * shares
            portfolio['position'] = 0
            portfolio['avg_cost'] = 0
    return portfolio

def execute_trade(conn, timestamp, signal, price, portfolio):
    if signal == "買入":
        if portfolio['position'] >= MAX_POSITION_SHARES: return
        if portfolio['position'] > 0 and price <= portfolio['avg_cost']: return
        if portfolio['cash'] >= price * ADD_ON_SHARES:
            log_trade(conn, timestamp, STOCK_ID, "買入", ADD_ON_SHARES, price)
            print(f"📈【執行買入】時間 {timestamp.date()}，價格 {price:.2f}")
    elif signal == "賣出":
        if portfolio['position'] > 0:
            profit = (price - portfolio['avg_cost']) * portfolio['position']
            log_trade(conn, timestamp, STOCK_ID, "訊號賣出", portfolio['position'], price, profit)
            print(f'📉【訊號賣出】時間 {timestamp.date()}，價格 {price:.2f}，損益：{profit:,.2f}')

def check_stop_loss(conn, timestamp, price, portfolio):
    if portfolio['position'] > 0:
        stop_loss_price = portfolio['avg_cost'] * (1 - STOP_LOSS_PCT)
        if price < stop_loss_price:
            profit = (price - portfolio['avg_cost']) * portfolio['position']
            log_trade(conn, timestamp, STOCK_ID, "停損賣出", portfolio['position'], price, profit)
            print(f'💥【強制停損】時間 {timestamp.date()}，價格 {price:.2f}!')
            return True
    return False

def run_trading_job():
    print(f"\n🤖 [{pd.Timestamp.now(tz='Asia/Taipei').strftime('%Y-%m-%d %H:%M:%S')}] API被觸發...")
    conn = sqlite3.connect(DB_NAME)
    try:
        portfolio = get_current_portfolio(conn)
        df = yf.download(STOCK_ID, period="40d", interval="1d", progress=False)
        if df.empty: return {"status": "error", "message": "無法下載資料"}
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        df.columns = ['open', 'high', 'low', 'close', 'volume']
        df['sma_5'] = df.ta.sma(length=5, close='close')
        df['sma_20'] = df.ta.sma(length=20, close='close')
        if df['sma_20'].isnull().all(): return {"status": "error", "message": "指標計算失敗"}
        latest_data = df.iloc[-2:]
        signal = "持有"
        if latest_data['sma_5'].iloc[0] < latest_data['sma_20'].iloc[0] and latest_data['sma_5'].iloc[1] > latest_data['sma_20'].iloc[1]: signal = "買入"
        elif latest_data['sma_5'].iloc[0] > latest_data['sma_20'].iloc[0] and latest_data['sma_5'].iloc[1] < latest_data['sma_20'].iloc[1]: signal = "賣出"
        current_price = df['close'].iloc[-1]
        current_time = df.index[-1]
        print(f"   最新價格 ({current_time.date()}): {current_price:.2f}, 訊號: {signal}")
        if not check_stop_loss(conn, current_time, current_price, portfolio):
            execute_trade(conn, current_time, signal, current_price, portfolio)
        final_portfolio = get_current_portfolio(conn)
        total_asset = final_portfolio['cash'] + (final_portfolio['position'] * current_price)
        log_performance(conn, current_time.date(), total_asset)
        message = f"檢查完成。總資產: {total_asset:,.2f}"
        print(f"   {message}")
        return {"status": "success", "message": message}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()
        print(f"🤖 [{pd.Timestamp.now(tz='Asia/Taipei').strftime('%Y-%m-%d %H:%M:%S')}] 檢查結束。")

# --- 4. Flask Web 應用 ---
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>交易績效儀表板</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #111827; color: #d1d5db; }
        .chart-container { height: 50vh; min-height: 400px; background-color: #1f2937; border-radius: 0.5rem; padding: 1.5rem; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #374151; }
        th { background-color: #374151; }
        .buy-action { color: #22c55e; }
        .sell-action { color: #ef4444; }
    </style>
</head>
<body class="p-4 md:p-8">
    <div class="max-w-7xl mx-auto">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-white">自動交易系統儀表板</h1>
            <p class="text-gray-400">即時監控交易績效與歷史紀錄</p>
        </header>
        <main>
            <section id="performance-chart" class="mb-8"><div class="chart-container"><canvas id="assetChart"></canvas></div></section>
            <section id="trade-history">
                <h2 class="text-2xl font-semibold mb-4 text-white">交易歷史紀錄</h2>
                <div class="overflow-x-auto bg-gray-800 rounded-lg shadow-lg">
                    <table>
                        <thead>
                            <tr> <th>交易時間</th> <th>股票代號</th> <th>動作</th> <th>股數</th> <th>價格</th> <th>總金額</th> <th>損益</th> </tr>
                        </thead>
                        <tbody>
                            {% for trade in trades %}
                            <tr>
                                <td>{{ trade.timestamp }}</td>
                                <td>{{ trade.stock_id }}</td>
                                <td class="{{ 'buy-action' if '買入' in trade.action else 'sell-action' }}">{{ trade.action }}</td>
                                <td>{{ trade.shares }}</td>
                                <td>{{"%.2f"|format(trade.price)}}</td>
                                <td>{{"%.2f"|format(trade.total_value)}}</td>
                                <td>
                                    {% if trade.profit is not none %}
                                        <span class="{{ 'buy-action' if trade.profit > 0 else 'sell-action' }}">
                                            {{"%.2f"|format(trade.profit)}}
                                        </span>
                                    {% else %} - {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </section>
        </main>
    </div>
    <script>
        const chartData = {{ chart_data | tojson | safe }};
        if (chartData.dates && chartData.dates.length > 0) {
            // --- ▼▼▼ 這裡就是唯一的修正點 ▼▼▼ ---
            // 將 getContext('d') 修正為 getContext('2d')
            const ctx = document.getElementById('assetChart').getContext('2d');
            // --- ▲▲▲ 這裡就是唯一的修正點 ▲▲▲ ---
            const assetChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: chartData.dates,
                    datasets: [{
                        label: '總資產價值',
                        data: chartData.values,
                        borderColor: 'rgba(59, 130, 246, 1)',
                        backgroundColor: 'rgba(59, 130, 246, 0.2)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { beginAtZero: false, ticks: { color: '#9ca3af' }, grid: { color: '#374151' } }, x: { ticks: { color: '#9ca3af' }, grid: { color: '#374151' } } },
                    plugins: { legend: { labels: { color: '#d1d5db' } } }
                }
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    if not os.path.exists(DB_NAME):
        return "<h1>資料庫檔案不存在</h1><p>請先執行 test_data_generator.py 來產生交易數據。</p>", 404
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    trades_df = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp DESC", conn)
    performance_df = pd.read_sql_query("SELECT * FROM daily_performance ORDER BY date ASC", conn)
    conn.close()
    chart_data_dict = {'dates': performance_df['date'].tolist(),'values': performance_df['asset_value'].tolist()}
    trades_list = trades_df.to_dict('records')
    return render_template_string(HTML_TEMPLATE, trades=trades_list, chart_data=chart_data_dict)

@app.route('/api/trigger-trade-check', methods=['POST'])
def trigger_trade_check():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {API_SECRET_KEY}":
        return jsonify({"status": "error", "message": "未經授權"}), 401
    result = run_trading_job()
    if result['status'] == 'success':
        return jsonify(result), 200
    else:
        return jsonify(result), 500

# --- 5. 程式主進入點 ---
if __name__ == '__main__':
    conn = sqlite3.connect(DB_NAME)
    setup_database(conn)
    conn.close()
    app.run(host='0.0.0.0', port=5001)

