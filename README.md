# **互動式證券自動交易分析平台 (FinMind 雲端部署版)**

一個整合了**即時模擬交易儀表板**與**互動式歷史回測**功能的 Python Flask Web 應用，由 **n8n.cloud** 工作流引擎驅動，使用 **FinMind API** 作為穩定資料源，並部署在 **Render** 雲端平台上，使用 **PostgreSQL** 作為資料庫。

## **專案預覽**

<img width="1760" height="3090" alt="screen" src="https://github.com/user-attachments/assets/acd3d29f-4158-4e2f-a01f-787fdd0f1ea5" />

## **系統架構**

本專案採用服務分離的現代雲端架構，確保各元件的穩定性與擴充性：

1. **n8n.cloud (指揮官)**: 使用 n8n 官方的雲端服務，定時（例如：交易日的 9-13 點，每小時一次）向部署在 Render 上的 Flask 應用發送 Webhook 請求。  
2. **FinMind API (情報中心)**: 作為穩定、可靠的金融數據來源，取代 yfinance，為系統提供所有價量資料。  
3. **Render Web Service (士兵 \+ 資訊官)**:  
   * 一個運行 gunicorn 的 Python 環境，託管我們的 app.py。  
   * 提供 API 端點接收 n8n 命令，並呼叫 FinMind API 獲取資料來執行交易邏輯。  
   * 提供前端儀表板供使用者互動。  
4. **Render PostgreSQL (軍火庫)**:  
   * 一個由 Render 提供的全託管 PostgreSQL 資料庫，用於永久儲存所有交易、績效與設定數據。

## **主要功能**

* **📊 整合性前端介面**:  
  * **頁籤式設計**: 在單一頁面中無縫切換「即時儀表板」與「歷史回測」功能。  
  * **非同步請求 (AJAX)**: 執行回測或更新設定時頁面無需刷新，提供流暢的使用者體驗。  
* **⚙️ 互動式即時監控**:  
  * 使用者可**自訂監控的股票標的**。  
  * 可為**每個標的設定獨立的初始資金**。  
  * 提供「手動觸發」按鈕，可立即模擬 n8n 執行一次交易檢查。  
* **🤖 可配置的歷史回測**: 使用者可自訂回測的股票代號、時間區間與初始資金，即時獲得策略在不同情境下的表現。  
* **🚀 n8n 工作流整合**: 將排程功能外部化，由 n8n 負責觸發，使系統更具彈性。  
* **📝 持久化設定**: 所有使用者設定都會被儲存在雲端的 PostgreSQL 資料庫中。

## **技術棧 (Technology Stack)**

* **後端**: Python, Flask, Gunicorn  
* **數據處理**: Pandas, pandas-ta  
* **資料獲取**: **FinMind API**  
* **資料庫**: **PostgreSQL** (on Render)  
* **自動化**: n8n.cloud  
* **前端**: HTML, Tailwind CSS, Chart.js, AJAX (fetch API)  
* **雲端平台**: Render  
* **版本控制**: Git, GitHub

## **如何在雲端部署**

### **第一部分：取得 FinMind API Token**

1. **註冊 FinMind**: 前往 [FinMind 官方網站](https://finmindtrade.com/) 註冊一個免費帳號。  
2. **取得 API Token**: 登入後，在您的個人資料頁面可以找到您的 token，請將它複製下來，稍後會用到。

### **第二部分：部署 Flask 應用到 Render**

1. **準備 GitHub**: 將專案（包含最新的 app.py 和 requirements.txt）推送到您的 GitHub 倉庫。  
2. **註冊 Render**: 前往 [Render.com](https://render.com/) 並用您的 GitHub 帳號註冊。  
3. **建立 PostgreSQL 資料庫**:  
   * 在 Render 儀表板，點擊 New \+ \-\> PostgreSQL。  
   * 取一個名字（例如 trading-db），選擇 Singapore 區域，點擊 Create Database。  
   * 建立後，往下滾動到 Connections 區塊，複製 **Internal Database URL**。  
4. **建立 Web Service**:  
   * 點擊 New \+ \-\> Web Service。  
   * 選擇您專案的 GitHub 倉庫並連接。  
   * **Name**: trading-platform-finmind (或您喜歡的名字)  
   * **Branch**: main (或您存放最終版的程式碼分支)  
   * **Build Command**: pip install \-r requirements.txt  
   * **Start Command**: gunicorn \--timeout 120 "app:create\_app()"  
5. **設定環境變數 (最關鍵的一步)**:  
   * 在建立服務的頁面往下滾動到 Advanced。  
   * 在 Environment 區塊點擊 Add Environment Variable，新增**四個**變數：  
     * **Key**: PYTHON\_VERSION, **Value**: 3.12.4  
     * **Key**: DATABASE\_URL, **Value**: (貼上您剛剛複製的 PostgreSQL 內部 URL)  
     * **Key**: API\_SECRET\_KEY, **Value**: (設定一個您自己的、更複雜的密鑰，例如 strong\_secret\_from\_render)  
     * **Key**: FINMIND\_API\_TOKEN, **Value**: (貼上您從 FinMind 網站複製的 API Token)  
6. **部署！**: 點擊 Create Web Service。Render 會自動開始建置並啟動您的應用。完成後，您會得到一個 ...onrender.com 的公開網址。

### **第三部分：設定 n8n.cloud**

1. **註冊 n8n.cloud**: 前往 [n8n.cloud](https://n8n.cloud/) 並註冊一個免費帳號。  
2. **設定工作流**:  
   * 登入後，匯入 trading\_bot\_workflow.json。  
   * 設定 HTTP Header Auth 憑證，Value 要使用您在 Render 環境變數中設定的 API\_SECRET\_KEY。  
   * 修改 HTTP Request 節點的 **URL**，改為您從 Render 拿到的公開網址，並在後面加上 /api/trigger-trade-check。  
3. **啟動工作流**
