證券自動交易分析平台 (雲端部署版)
一個整合了即時模擬交易儀表板與互動式歷史回測功能的 Python Flask Web 應用，由 n8n.cloud 工作流引擎驅動，並部署在 Render 雲端平台上，使用 PostgreSQL 作為資料庫。

專案預覽
(請將此處的連結替換為您自己上傳到 GitHub 的儀表板截圖)

系統架構
本專案採用服務分離的現代雲端架構：

n8n.cloud (指揮官): 使用 n8n 官方的雲端服務，定時向部署在 Render 上的 Flask 應用發送 Webhook 請求。

Render Web Service (士兵 + 資訊官):

一個運行 gunicorn 的 Python 環境，託管我們的 app.py。

提供 API 端點接收 n8n 命令，並執行交易邏輯。

提供前端儀表板供使用者互動。

Render PostgreSQL (軍火庫):

一個由 Render 提供的全託管 PostgreSQL 資料庫，用於永久儲存所有交易、績效與設定數據。

如何在雲端部署
第一部分：部署 Flask 應用到 Render
準備 GitHub: 將專案（包含最新的 app.py, requirements.txt, build.sh）推送到您的 GitHub 倉庫。

註冊 Render: 前往 Render.com 並用您的 GitHub 帳號註冊。

建立 PostgreSQL 資料庫:

在 Render 儀表板，點擊 New + -> PostgreSQL。

取一個名字（例如 trading-db），選擇 Singapore 區域，點擊 Create Database。

建立後，往下滾動到 Connections 區塊，複製 Internal Database URL，我們稍後會用到。

建立 Web Service:

點擊 New + -> Web Service。

選擇您專案的 GitHub 倉庫並連接。

Name: trading-platform (或您喜歡的名字)

Branch: main (確保您已經將 cloud-deployment 分支合併進 main)

Build Command: pip install -r requirements.txt

Start Command: gunicorn "app:create_app()"

設定環境變數:

點擊 Advanced，在 Environment 區塊新增三個變數：

Key: PYTHON_VERSION, Value: 3.9.18

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

此專案為面試作品，旨在展示後端系統設計與雲端部署能力。