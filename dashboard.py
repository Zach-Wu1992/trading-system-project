import flask
from flask import Flask, render_template_string
import sqlite3
import pandas as pd
import os
import json

# --- 設定 ---
DB_NAME = 'trading_dashboard.db'
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# --- HTML 模板 ---
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
        .chart-container { background-color: #1f2937; border-radius: 0.5rem; padding: 1.5rem; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #374151; }
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
            <section id="performance-chart" class="mb-8">
                <div class="chart-container h-72 md:h-[65vh]">
                    <canvas id="assetChart"></canvas>
                </div>
            </section>

            <section id="trade-history">
                <h2 class="text-2xl font-semibold mb-4 text-white">交易歷史紀錄</h2>
                <div class="overflow-x-auto bg-gray-800 rounded-lg">
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
                                <td>{{ "%.2f"|format(trade.price) }}</td>
                                <td>{{ "%.2f"|format(trade.total_value) }}</td>
                                <td>
                                    {% if trade.profit is not none and trade.profit == trade.profit %}
                                        <span class="{{ 'buy-action' if trade.profit > 0 else 'sell-action' }}">
                                            {{ "%.2f"|format(trade.profit) }}
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
        // --- ▼▼▼ 關鍵修正 ▼▼▼ ---
        // 直接將後端傳來的 chart_data，透過 tojson 過濾器轉換成 JavaScript 物件
        // 不再需要手動 JSON.parse()
        const chartData = {{ chart_data | tojson | safe }};
        // --- ▲▲▲ 關鍵修正 ▲▲▲ ---

        if (chartData.dates && chartData.dates.length > 0) {
            const ctx = document.getElementById('assetChart').getContext('2d');
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
                    maintainAspectRatio: false, // 讓圖表高度可以自由調整
                    scales: {
                        y: {
                            beginAtZero: false,
                            ticks: { color: '#9ca3af' },
                            grid: { color: '#374151' }
                        },
                        x: {
                            ticks: { color: '#9ca3af' },
                            grid: { color: '#374151' }
                        }
                    },
                    plugins: {
                        legend: {
                            labels: {
                                color: '#d1d5db'
                            }
                        }
                    }
                }
            });
        }
    </script>
</body>
</html>
"""

# --- 後端邏輯 ---
@app.route('/')
def index():
    if not os.path.exists(DB_NAME):
        return "<h1>資料庫檔案不存在</h1><p>請先執行 realtime_bot.py 或 test_data_generator.py 來產生交易數據。</p>", 404

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    
    trades_df = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp DESC", conn)
    performance_df = pd.read_sql_query("SELECT * FROM daily_performance ORDER BY date ASC", conn)
    
    conn.close()

    # --- ▼▼▼ 關鍵修正 ▼▼▼ ---
    # 1. 建立一個標準的 Python 字典
    chart_data_dict = {
        'dates': performance_df['date'].tolist(),
        'values': performance_df['asset_value'].tolist()
    }
    # 2. 不再手動轉換成 JSON 字串
    # chart_data_json_string = json.dumps(chart_data_dict)
    # --- ▲▲▲ 關鍵修正 ▲▲▲ ---
    
    trades_list = trades_df.to_dict('records')
    
    # 將原始的 Python 字典直接傳遞給模板
    return render_template_string(HTML_TEMPLATE, trades=trades_list, chart_data=chart_data_dict)

# --- 程式進入點 ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)

