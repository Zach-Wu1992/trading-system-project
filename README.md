# 券自動交易模擬系統 (n8n 整合版)

# 一個結合了 Python Flask 後端、n8n 自動化工作流與 SQLite 資料庫的動態交易績效儀表板。

# 

# 這是一個專為 IT 職位面試設計的作品，旨在展示一個完整的後端系統設計與開發流程。系統透過預設的交易策略（均線交叉）進行模擬交易，並整合了加碼與停損的風險控管機制。所有交易與每日績效都會被永久記錄在 SQLite 資料庫中，並透過 Flask 打造的 Web 儀表板進行視覺化呈現。

# 

# 整個系統的交易檢查流程，由 n8n 工作流引擎進行排程與自動化觸發。

# 

# 專案預覽

# (請將此處的連結替換為您自己上傳到 GitHub 的儀表板截圖)

# 

# 系統架構

# 本專案採用服務分離的現代後端架構：

# 

# n8n 工作流 (指揮官): 作為系統的觸發器，使用 Cron 節點定時（例如：每個交易日下午 2:00）啟動。

# 

# HTTP Request: n8n 透過安全的 API 金鑰，向 Flask 應用發送一個 POST 請求。

# 

# Flask API (app.py) (士兵 + 資訊官):

# 

# 提供一個受保護的 API 端點 (/api/trigger-trade-check) 接收 n8n 的命令。

# 

# 執行核心交易邏輯：抓取最新股價、計算指標、判斷訊號、執行交易與風控。

# 

# 將所有交易與每日績效紀錄寫入 SQLite 資料庫。

# 

# 提供一個儀表板網頁 (/)，從資料庫讀取數據並呈現給使用者。

# 

# SQLite 資料庫 (軍火庫): 作為系統的永久儲存中心，記錄所有交易歷史與績效數據。

# 

# 主要功能

# 📈 動態視覺化儀表板: 使用 Flask、Chart.js 和 Tailwind CSS 打造，即時顯示總資產的淨值曲線與詳細的交易歷史紀錄。

# 

# 🤖 自動化交易策略:

# 

# 訊號產生: 基於 5 日與 20 日移動平均線 (SMA) 的黃金交叉與死亡交叉。

# 

# 加碼機制: 順勢而為，僅在倉位處於獲利狀態時才進行加碼。

# 

# 🛡️ 風險控管機制:

# 

# 倉位上限: 限制最大持股數量，避免單一標的風險過高。

# 

# 停損機制: 當價格跌破平均成本的一定百分比時，自動清倉以保護本金。

# 

# 🚀 n8n 工作流整合: 將排程功能外部化，由 n8n 負責觸發，使系統更具彈性與擴充性（例如，未來可輕易加入 Email/Discord 交易通知）。

# 

# 技術棧 (Technology Stack)

# 後端: Python, Flask

# 

# 數據處理: Pandas, pandas-ta

# 

# 資料獲取: yfinance

# 

# 資料庫: SQLite3

# 

# 自動化: n8n (透過 Node.js/NPM 運行)

# 

# 前端: HTML, Tailwind CSS, Chart.js

# 

# 版本控制: Git, GitHub

# 

# 安裝與設定

# 1\. 環境準備

# Clone 專案:

# 

# git clone \[https://github.com/Zach-Wu1992/trading-system-project.git](https://github.com/Zach-Wu1992/trading-system-project.git)

# cd trading-system-project

# 

# 建立 Conda 虛擬環境:

# 

# conda create --name trading\_env python=3.9

# conda activate trading\_env

# 

# 2\. 安裝 Python 依賴

# 使用專案提供的 requirements.txt 檔案進行安裝：

# 

# pip install -r requirements.txt

# 

# 3\. 安裝與設定 n8n (使用 Node.js/NPM)

# 安裝 Node.js: 前往 Node.js 官方網站 下載並安裝 LTS 版本。

# 

# 安裝 n8n: 開啟一個新的終端機，執行以下指令進行全域安裝：

# 

# npm install n8n -g

# 

# 如何運行

# 您需要開啟兩個終端機來分別啟動後端 API 和 n8n 服務。

# 

# 第一步：啟動 Flask API 伺服器

# 在第一個終端機中：

# 

# \# 啟動 Python 環境

# conda activate trading\_env

# \# 啟動 Flask 應用

# python app.py

# 

# 伺服器將會運行在 http://localhost:5001。請讓此視窗保持開啟。

# 

# 第二步：啟動 n8n 服務

# 在第二個終端機中：

# 

# \# 直接啟動 n8n

# n8n

