#匯入需要工具庫
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import sqlite3
from datetime import datetime


#--- 1.全域參數設定 ---
#資料庫名稱
DB_NAME = 'trading_log_v2.db'

#設定Panda顯示選項，讓DataFram顯示所有欄位
pd.set_option('display.max_columns', None)

#初始資金
CASH=1000000

#股票代號和時間範圍
stock_id="2308.TW"
start_date="2024-01-01" #日期格式
end_date= None # 結束日期設為昨天，確保有完整的歷史資料

#策略與風控參數
ADD_ON_SHARES=1000
MAX_POSITION_SHARES=3000
STOP_LOSS_PCT=0.02

#模擬投資組合
portfolio={
    'cash':CASH,
    'position':0,
    'avg_cost':0,
    }

#--- 2.資料庫函式 ---
def setup_database(conn):
    """建立資料庫和trades資料表"""
    cursor=conn.cursor()
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS trades(
                       trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            action TEXT NOT NULL,
            shares INTEGER NOT NULL,
            price REAL NOT NULL,
            total_value REAL NOT NULL,
            profit REAL
            )
                   ''')
    conn.commit()
    print("資料庫設定完成，'trades' 資料表已確認存在")
    
    
def log_trade(conn,timestamp, stock_id, action, shares, price, profit=None):
    """將一筆交易紀錄寫入資料庫"""
    cursor = conn.cursor()
    total_value = shares * price
    sql = '''
        INSERT INTO trades (timestamp, stock_id, action, shares, price, total_value, profit)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    '''
    cursor.execute(sql, (str(timestamp.date()), stock_id, action, shares, price, total_value, profit))
    conn.commit()
    print(f" 資料庫紀錄: {action} {shares} 股 at {price:.2f}")
    

#--- 3.核心功能函式 ---
#訊號計算
def generate_signals(df):
    print("...正在計算技術指標與訊號...")
    
    #加入新欄位(取得技術指標)
    df.ta.sma(length=5,append=True)
    df.ta.sma(length=20,append=True)
    
    #產生交易訊號(策略)，新增欄位
    df['signal']="持有"
    
    #shift往下一列，做向量化計算
    yesterday_sma5=df['SMA_5'].shift(1)
    yesterday_sma20=df['SMA_20'].shift(1)
    
    #向量化計算
    #黃金交叉條件
    buy_conditions=(df['SMA_5']>df['SMA_20']) & (yesterday_sma5<yesterday_sma20)
    #死亡交叉條件
    sell_conditions=(df['SMA_5']<df['SMA_20']) & (yesterday_sma5>yesterday_sma20)
    
    #根據條件設定訊號
    df.loc[buy_conditions,'signal']="買入"
    df.loc[sell_conditions,'signal']="賣出"
    
    print("訊號計算完成")
    return df

#執行交易
def execute_trade(conn,timestamp,signal,price):
    if signal == "買入":
        if portfolio['position'] >= MAX_POSITION_SHARES:
            print(f"無法加碼，倉位已達上限{MAX_POSITION_SHARES}股")
            return
        if portfolio['position']>0 and price < portfolio['avg_cost']:
            print(f"無法加碼，股價未高於平均成本{portfolio['avg_cost']:.2f}元")
            return
        #執行加碼
        trade_cost=price*ADD_ON_SHARES
        if portfolio['cash']>=trade_cost:
            old_total=portfolio['avg_cost']*portfolio['position']
            new_cost=price*ADD_ON_SHARES
            new_total=old_total + new_cost
            
            #跟新倉位及現金
            portfolio['cash']-=trade_cost
            portfolio['position']+=ADD_ON_SHARES
            portfolio['avg_cost']=new_total/portfolio['position']
            print(f"日期{timestamp.date()}執行加碼，在價格{price:.2f}買入{ADD_ON_SHARES}股")
            print(f"新倉位{portfolio['position']}股，新平均成本{portfolio['avg_cost']:.2f}")
            
            #寫入資料庫
            log_trade(conn,timestamp,stock_id, "買入", ADD_ON_SHARES, price)
        else:
            print("資金不足，加碼失敗")
            
            
        #執行清倉
    elif signal == "賣出":
        if portfolio['position'] >0:
            shares_to_sell=portfolio['position']
            trade_revenue=price * shares_to_sell
            profit=(price-portfolio['avg_cost'])*shares_to_sell
            
            #更新倉位及現金
            portfolio['cash']+=trade_revenue
            portfolio['position']=0
            portfolio['avg_cost']=0
            
            print(f'日期 {timestamp.date()}執行清倉，在價格{price:.2f}清空所有持股{shares_to_sell}股，實現損益：{profit:.2f}')
            
            #寫入資料庫
            log_trade(conn,timestamp,stock_id, "訊號賣出", shares_to_sell, price,profit)
        else:
            print("無倉位，無法賣出")
    else:
        print("訊號為【持有】，不執行交易動作")
    
#每日檢查停損條件
def check_stop_loss(conn, timestamp, price):
    '''每天檢查是否觸發停損'''
    if  portfolio['position']>0:
        stop_loss_price=portfolio['avg_cost']*(1-STOP_LOSS_PCT)
        if price < stop_loss_price:
            print(f'停損觸發，目前價格 {price:.2f} 低於停損點 {stop_loss_price:.2f}!')
        
            #強制清倉
            shares_to_sell=portfolio['position']
            trade_revenue=price * shares_to_sell
            profit=(price-portfolio['avg_cost'])*shares_to_sell
            
            #更新倉位及現金
            portfolio['cash']+=trade_revenue
            portfolio['position']=0
            portfolio['avg_cost']=0
            print(f'日期 {timestamp.date()}執行清倉，在價格{price:.2f}清空所有持股{shares_to_sell}股，實現損益：{profit:.2f}')
            
            #寫入資料庫
            log_trade(conn,timestamp,stock_id, "停損賣出", shares_to_sell, price,profit)
            
            return True
    return False

#回測程式
def run_backtest():
    #資料庫連線
    conn = sqlite3.connect(DB_NAME)
    setup_database(conn)
    
    print("🚀 --- 開始執行回測 --- 🚀")
    #獲取歷史資料
    delta=yf.Ticker(stock_id)
    df=delta.history(start=start_date,end=end_date)
    if df.empty:
        print("無法下載資料，程式終止")
        conn.close()
        return
    
    #產生訊號
    df_signals=generate_signals(df)
    
    # 建立一個列表，用來紀錄每天的總資產
    daily_assets = []
    
    print("\n--- 開始模擬每日交易 ---")
    #建立回測迴圈
    for index,row in df_signals.iterrows():
        current_price=row['Close']
        signal=row['signal']
        
        #優先檢查停損
        stop_loss_triggered = check_stop_loss(conn,index,current_price)
        
        # 如果沒有觸發停損，才根據訊號交易
        if not stop_loss_triggered:
            execute_trade(conn, index, signal, current_price)
        
        #計算並記錄當日結束後的總資產
        market_value=portfolio['position']*current_price
        total_asset=portfolio['cash']+market_value
        daily_assets.append(total_asset)
    conn.close()
    print("---每日交易模擬結束---\n")
    
    #顯示最終績效
    final_asset=daily_assets[-1]
    total_return_pct=((final_asset-CASH)/CASH)*100
    
    print("---回測績效報告---")
    print(f"起始資金{CASH:,.2f}")
    print(f"最終資產{final_asset:,.2f}")
    print(f"總報酬率:{total_return_pct:,.2f}%")
    
    
#程式進入點
if __name__ == "__main__":
    run_backtest()


