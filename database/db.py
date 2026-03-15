# -*- coding: utf-8 -*-
# --- database/db.py：所有 PostgreSQL 資料庫操作 ---
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL


def get_db_connection():
    """建立並返回資料庫連線。"""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL 環境變數未設定！")
    return psycopg2.connect(DATABASE_URL)


def setup_database():
    """初始化資料庫，建立必要的資料表。"""
    logging.info("🚀 正在設定 PostgreSQL 資料庫...")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    price REAL NOT NULL,
                    total_value REAL NOT NULL,
                    profit REAL
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
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            ''')
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                ('live_stock_id', '2330.TW')
            )
        conn.commit()
        logging.info("✅ 資料庫設定完成。")
    except Exception as e:
        logging.error(f"❌ 資料庫設定失敗: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_setting(key):
    """從 settings 資料表讀取指定 key 的值。"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
            result = cur.fetchone()
            return result[0] if result else None
    finally:
        conn.close()


def update_setting(key, value):
    """新增或更新 settings 資料表中指定 key 的值。"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value)
            )
        conn.commit()
    finally:
        conn.close()


def log_trade(timestamp, stock_id, action, shares, price, profit=None):
    """將一筆交易紀錄寫入 trades 資料表。"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            py_shares = int(shares)
            py_price = float(price)
            py_total_value = py_shares * py_price
            py_profit = float(profit) if profit is not None else None
            formatted_timestamp = timestamp.strftime('%Y-%m-%d %H:%M')
            sql = '''
                INSERT INTO trades (timestamp, stock_id, action, shares, price, total_value, profit)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            '''
            cur.execute(sql, (formatted_timestamp, stock_id, action, py_shares, py_price, py_total_value, py_profit))
        conn.commit()
    finally:
        conn.close()


def log_performance(date, stock_id, asset_value):
    """記錄每日資產價值到 daily_performance 資料表。"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            sql = '''
                INSERT INTO daily_performance (date, stock_id, asset_value)
                VALUES (%s, %s, %s)
                ON CONFLICT (date, stock_id) DO UPDATE SET asset_value = EXCLUDED.asset_value
            '''
            cur.execute(sql, (str(date), stock_id, float(asset_value)))
        conn.commit()
    finally:
        conn.close()


def get_trades(stock_id):
    """取得指定股票的所有交易紀錄（依時間降冪排列）。"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM trades WHERE stock_id = %s ORDER BY timestamp DESC", (stock_id,))
            return cur.fetchall()
    finally:
        conn.close()


def get_performance(stock_id):
    """取得指定股票的每日績效資料（依日期升冪排列）。"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM daily_performance WHERE stock_id = %s ORDER BY date ASC", (stock_id,))
            return cur.fetchall()
    finally:
        conn.close()


def get_buy_sell_trades(stock_id):
    """取得指定股票的買賣交易紀錄，用於計算持倉（依時間升冪排列）。"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT action, shares, price FROM trades "
                "WHERE stock_id = %s AND (action = '執行買入' OR action LIKE '%%賣出') "
                "ORDER BY timestamp ASC",
                (stock_id,)
            )
            return cur.fetchall()
    finally:
        conn.close()
