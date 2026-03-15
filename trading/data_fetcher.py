# -*- coding: utf-8 -*-
# --- trading/data_fetcher.py：yfinance 資料獲取與技術指標計算 ---
import logging
import yfinance as yf


def _normalize_stock_id(stock_id: str) -> str:
    """若股票代號無後綴，預設補上 .TW（台股格式）。"""
    if not stock_id.endswith('.TW') and not stock_id.endswith('.TWO'):
        return f"{stock_id}.TW"
    return stock_id


def get_historical_data(stock_id: str):
    """
    下載近兩年股價資料並計算技術指標。

    計算指標：
    - SMA 50 / 150 / 200
    - 52 週高點 / 低點
    - SMA 200（20 個交易日前）

    Returns:
        DataFrame 或 None（無資料時）
    """
    ticker = yf.Ticker(stock_id)
    df = ticker.history(period="2y")
    if df.empty:
        return None

    df.index = df.index.tz_convert('Asia/Taipei')
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
    })

    df['sma_50'] = df['close'].rolling(window=50).mean()
    df['sma_150'] = df['close'].rolling(window=150).mean()
    df['sma_200'] = df['close'].rolling(window=200).mean()
    df['52w_high'] = df['high'].rolling(window=252).max()
    df['52w_low'] = df['low'].rolling(window=252).min()
    df['sma_200_20d_ago'] = df['sma_200'].shift(20)

    return df


def get_historical_data_range(stock_id: str, start_date: str, end_date: str):
    """
    下載指定日期範圍的股價資料並計算技術指標（用於回測）。
    自動往前多抓兩年資料確保指標計算正確，最後過濾回指定範圍。

    Returns:
        DataFrame 或 None（無資料或指標計算失敗時）
    """
    import pandas as pd

    ticker = yf.Ticker(stock_id)
    extended_start = (pd.to_datetime(start_date) - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
    df_raw = ticker.history(start=extended_start, end=end_date)

    if df_raw.empty:
        return None

    df = df_raw[['Open', 'High', 'Low', 'Close', 'Volume']].rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
    })

    if df.index.tz:
        df.index = df.index.tz_localize(None)

    df['sma_50'] = df['close'].rolling(window=50).mean()
    df['sma_150'] = df['close'].rolling(window=150).mean()
    df['sma_200'] = df['close'].rolling(window=200).mean()
    df['52w_high'] = df['high'].rolling(window=252).max()
    df['52w_low'] = df['low'].rolling(window=252).min()
    df['sma_200_20d_ago'] = df['sma_200'].shift(20)

    if df['sma_200'].isnull().all():
        return None

    # 過濾回真正要求的日期範圍
    df = df.loc[start_date:end_date]
    return df


def get_latest_price_info(stock_id: str):
    """
    取得股票最新價格、資料時間、MA50。

    Returns:
        tuple: (latest_price, latest_time, latest_ma50, df)
        失敗時返回 (None, None, None, None)
    """
    stock_id = _normalize_stock_id(stock_id)
    df = get_historical_data(stock_id)
    if df is None or df.empty:
        logging.warning(f"無法從 yfinance 獲取 {stock_id} 的資料")
        return None, None, None, None

    latest_price = df['close'].iloc[-1]
    latest_time = df.index[-1]
    latest_ma50 = df['sma_50'].iloc[-1]
    return latest_price, latest_time, latest_ma50, df
