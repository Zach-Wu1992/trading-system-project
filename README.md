互動式證券自動交易分析平台
一個整合了即時模擬交易儀表板與互動式歷史回測功能的 Python Flask Web 應用，由 n8n 工作流引擎驅動。

這是一個專為 IT 職位面試設計的完整專案，旨在展示一個現代化的、服務分離的後端系統設計與互動式前端的開發流程。使用者不僅可以查看由 n8n 自動觸發的即時模擬交易績效，還可以自訂監控標的、初始資金，並在前端執行參數化的歷史回測。

專案預覽
(請將此處的連結替換為您自己上傳到 GitHub 的最新儀表板截圖，記得要展示出新的設定區塊！)

系統架構
本專案的核心是一個 Flask Web 應用，它同時扮演API 伺服器和前端渲染引擎的角色，並由 n8n 進行自動化觸發。

n8n 工作流 (指揮官): 定時（例如：交易日的 9-13 點，每小時一次）向 Flask 應用發送 POST 請求，觸發每日的交易檢查。

Flask 應用 (app.py):

API 端點:

/api/trigger-trade-check: 接收 n8n 命令，執行即時交易模擬，並將結果存入資料庫。

/api/run-backtest: 接收使用者從前端發來的請求，執行歷史回測運算，並將結果回傳給前端。

/api/settings: 接收前端請求，更新資料庫中的使用者設定（如監控標的、初始資金）。

前端介面 (/):

提供一個單頁應用介面，包含兩個模式：

即時儀表板: 顯示由 n8n 驅動的最新交易績效與紀錄，並提供可互動的設定面板。

歷史回測: 提供表單讓使用者自訂回測參數（標的、日期、資金），並動態顯示回測結果。

SQLite 資料庫: 作為永久儲存中心，記錄即時交易的歷史、績效數據以及使用者設定。

主要功能
📊 整合性前端介面:

頁籤式設計: 在單一頁面中無縫切換「即時儀表板」與「歷史回測」功能。

非同步請求 (AJAX): 執行回測或更新設定時頁面無需刷新，提供流暢的使用者體驗。

⚙️ 互動式即時監控:

使用者可自訂監控的股票標的。

可為每個標的設定獨立的初始資金。

提供「手動觸發」按鈕，可立即模擬 n8n 執行一次交易檢查。

🤖 可配置的歷史回測: 使用者可自訂回測的股票代號、時間區間與初始資金，即時獲得策略在不同情境下的表現。

🚀 n8n 工作流整合: 將排程功能外部化，由 n8n 負責觸發，使系統更具彈性與擴充性。

📝 持久化設定: 所有使用者設定都會被儲存在資料庫中，重啟後依然保留。

(交易策略、風控、分頁等功能與前一版相同)

技術棧 (Technology Stack)
後端: Python, Flask

數據處理: Pandas, pandas-ta

資料獲取: yfinance

資料庫: SQLite3

自動化: n8n (透過 Node.js/NPM 運行)

前端: HTML, Tailwind CSS, Chart.js, AJAX (fetch API)

版本控制: Git, GitHub

安裝與設定
1. 環境準備
Clone 專案:

git clone [https://github.com/](https://github.com/)[YourUsername]/[YourProjectName].git
cd [YourProjectName]

建立 Conda 虛擬環境:

conda create --name trading_env python=3.9
conda activate trading_env

2. 安裝 Python 依賴
使用專案提供的 requirements.txt 檔案進行安裝：

pip install -r requirements.txt

3. 安裝與設定 n8n (使用 Node.js/NPM)
安裝 Node.js: 前往 Node.js 官方網站 下載並安裝 LTS 版本。

安裝 n8n: 開啟一個新的終端機，執行以下指令進行全域安裝：

npm install n8n -g

如何運行與測試
測試模式 (建議初次使用)
產生測試數據: 在終端機中執行測試數據生成器，這會建立一個乾淨的資料庫並填入假資料。

python test_data_generator.py

啟動 Flask 應用:

python app.py

驗證: 打開瀏覽器訪問 http://localhost:5001，您應該能看到一個數據豐富的儀表板。

即時模擬模式
啟動 Flask API 伺服器:

在第一個終端機中：

conda activate trading_env
python app.py

讓此視窗保持開啟。

啟動 n8n 服務:

在第二個終端機中：

n8n

讓此視窗也保持開啟。

設定 n8n 工作流:

打開瀏覽器，訪問 http://localhost:5678。

依照之前的教學，匯入 trading_bot_workflow.json 並設定好 API 金鑰與 URL。

啟動 (Active) 工作流。

開始使用:

訪問 http://localhost:5001。

在「即時儀表板」中設定您想監控的標的和資金，n8n 將會根據排程自動更新數據。