# -*- coding: utf-8 -*-
# --- trading/strategy.py：買入訊號計算策略（Minervini 趨勢模板）---


def is_buy_condition_met(row) -> bool:
    """
    判斷單筆資料是否滿足所有買入條件（Minervini 六大趨勢過濾）。

    條件：
    1. 收盤價 > SMA150 且 > SMA200
    2. SMA150 > SMA200
    3. SMA200 斜率向上（現值 > 20 天前）
    4. SMA50 > SMA150
    5. 收盤價 > 52週低點 * 1.25
    6. 收盤價 > 52週高點 * 0.75
    """
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


def calculate_latest_signal(df) -> str:
    """
    根據最新兩筆資料計算即時交易訊號。

    邏輯：只有在「昨日不滿足、今日滿足」時才發出買入訊號（新突破）。
    賣出邏輯由 executor.py 的停損/停利機制統一負責。

    Returns:
        str: "買入", "持有", 或 "資料不足"
    """
    if df is None or len(df) < 2:
        return "資料不足"

    today = df.iloc[-1]
    yesterday_met = is_buy_condition_met(df.iloc[-2])
    today_met = is_buy_condition_met(today)

    if today_met and not yesterday_met:
        return "買入"

    return "持有"


def apply_signals_to_dataframe(df):
    """
    對整個 DataFrame 應用買入訊號標記（用於回測）。

    Returns:
        DataFrame：新增 'signal' 欄位（"買入" / "持有"）
    """
    buy_mask = df.apply(is_buy_condition_met, axis=1)
    # 只有昨日未滿足、今日滿足才是「新突破」
    new_buy_mask = buy_mask & (~buy_mask.shift(1).fillna(False))
    df['signal'] = '持有'
    df.loc[new_buy_mask, 'signal'] = '買入'
    return df
