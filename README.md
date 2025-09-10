證券自動交易分析平台 (雲端部署版)
一個整合了即時模擬交易儀表板與互動式歷史回測功能的 Python Flask Web 應用，由 n8n.cloud 工作流引擎驅動，並部署在 Render 雲端平台上，使用 PostgreSQL 作為資料庫。

這是一個專為 IT 職位面試設計的完整專案，旨在展示一個現代化的、服務分離的後端系統設計與互動式前端的開發流程。

專案預覽
(請將此處的連結替換為您自己上傳到 GitHub 的最新儀表板截圖)

系統架構
本專案採用服務分離的現代雲端架構：

n8n.cloud (指揮官): 使用 n8n 官方的雲端服務，定時向部署在 Render 上的 Flask 應用發送 Webhook 請求。

Render Web Service (士兵 + 資訊官):

一個運行 gunicorn 的 Python 環境，託管我們的 app.py。

提供 API 端點接收 n8n 命令，並執行交易邏輯。

提供前端儀表板供使用者互動。

Render PostgreSQL (軍火庫):

一個由 Render 提供的全託管 PostgreSQL 資料庫，用於永久儲存所有交易、績效與設定數據。

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

📝 持久化設定: 所有使用者設定都會被儲存在雲端 PostgreSQL 資料庫中，重啟後依然保留。

技術棧 (Technology Stack)
後端: Python, Flask, Gunicorn

數據處理: Pandas, pandas-ta

資料獲取: yfinance

資料庫: PostgreSQL (on Render)

自動化: n8n.cloud

前端: HTML, Tailwind CSS, Chart.js, AJAX (fetch API)

版本控制: Git, GitHub

部署: Render

如何在雲端部署
第一部分：部署 Flask 應用到 Render
準備 GitHub: 將專案（包含最新的 app.py, requirements.txt, build.sh）推送到您的 GitHub 倉庫。

註冊 Render: 前往 Render.com 並用您的 GitHub 帳號註冊。

建立 PostgreSQL 資料庫:

在 Render 儀表板，點擊 New + -> PostgreSQL。

取一個名字（例如 trading-db），選擇離您最近的區域，點擊 Create Database。

建立後，往下滾動到 Connections 區塊，複製 Internal Database URL，我們稍後會用到。

建立 Web Service:

點擊 New + -> Web Service。

選擇您專案的 GitHub 倉庫並連接。

Name: trading-platform (或您喜歡的名字)

Runtime: Python 3

Build Command: pip install -r requirements.txt

Start Command: gunicorn "app:create_app()"

設定環境變數:

在 Environment 區塊新增兩個變數：

Key: DATABASE_URL, Value: (貼上您剛剛複製的 PostgreSQL 內部 URL)

Key: API_SECRET_KEY, Value: (設定一個您自己的、更複雜的密鑰，例如 strong_secret_from_render)

部署！: 點擊 Create Web Service。Render 會自動開始建立環境、安裝套件並啟動您的應用。完成後，您會得到一個 ...onrender.com 的公開網址。

第二部分：設定 n8n.cloud
註冊 n8n.cloud: 前往 n8n.cloud 並註冊一個免費帳號。

設定工作流:

登入後，像之前一樣匯入 trading_bot_workflow.json。

設定 HTTP Header Auth 憑證，這次的 Value 要使用您在 Render 環境變數中設定的那個更安全的 API_SECRET_KEY。

修改 HTTP Request 節點的 URL，將其改為您從 Render 拿到的公開網址，例如：https://trading-platform.onrender.com/api/trigger-trade-check

啟動工作流，大功告成！

現在，您的整個系統都運行在雲端，任何人都可以透過網址訪問您的儀表板，而 n8n.cloud 也會準時地在背景觸發您的交易機器人。