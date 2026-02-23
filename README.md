# **互動式證券自動交易分析平台**

一個整合了**即時模擬交易儀表板**與**互動式歷史回測**功能的 Python Flask Web 應用，由內建的 **APScheduler** 背景排程驅動，使用 **yfinance** 作為穩定資料源，並部署在 **Railway** 雲端平台上，使用 **PostgreSQL** 作為資料庫。

## **專案預覽**

*(請將此處的連結替換為您自己上傳到 GitHub 的最新儀表板截圖，記得要展示出新的設定區塊！)*

## **系統架構**

本專案採用服務分離的現代雲端架構，確保各元件的穩定性與擴充性：

1. **APScheduler (指揮官)**: 使用 Python 內建的排程套件，定時（台灣時間每個交易日週一至週五 13:30 收盤時）觸發交易檢查。  
2. **yfinance API (情報中心)**: 作為穩定、免費的金融數據來源，為系統提供所有歷史與即時的價量資料。  
3. **Railway App (士兵 \+ 資訊官)**:  
   * 一個運行 gunicorn 的 Python 環境，託管我們的 app.py。  
   * 提供 API 端點接收手動命令或由背景排程自動呼叫 yfinance API 獲取資料來執行交易邏輯（包含 VCP 突破與 15% 停損）。  
   * 提供前端儀表板供使用者互動。  
4. **Railway PostgreSQL (軍火庫)**:  
   * 一個由 Railway 提供的全託管 PostgreSQL 資料庫，用於永久儲存所有交易、績效與設定數據。

## **主要功能**

* **📊 整合性前端介面**:  
  * **頁籤式設計**: 在單一頁面中無縫切換「即時儀表板」與「歷史回測」功能。  
  * **非同步請求 (AJAX)**: 執行回測或更新設定時頁面無需刷新，提供流暢的使用者體驗。  
* **⚙️ 互動式即時監控**:  
  * 使用者可**自訂監控的股票標的**。  
  * 可為**每個標的設定獨立的初始資金**。  
  * 提供「手動觸發」按鈕，可立即模擬執行一次交易檢查。  
* **🤖 可配置的歷史回測**: 使用者可自訂回測的股票代號、時間區間與初始資金，即時獲得策略在不同情境下的表現。  
* **🚀 內建定時排程**: 無需依賴外部的 webhook 短期排程，由系統內建 APScheduler 自動於收盤後化勤。  
* **📝 持久化設定**: 所有使用者設定與交易紀錄都會被儲存在雲端的 PostgreSQL 資料庫中。

## **技術棧 (Technology Stack)**

* **後端**: Python, Flask, Gunicorn  
* **數據處理**: Pandas  
* **資料獲取**: **yfinance**  
* **資料庫**: **PostgreSQL** (on Railway)  
* **自動化**: **APScheduler**  
* **前端**: HTML, Tailwind CSS, Chart.js, AJAX (fetch API)  
* **雲端平台**: Railway  
* **版本控制**: Git, GitHub

## **如何在雲端部署**

### **部署 Flask 應用到 Railway**

1. **準備 GitHub**: 將專案（包含最新的 `app.py`, `requirements.txt` 及 `Procfile`）推送到您的 GitHub 倉庫。  
2. **註冊 Railway**: 前往 [Railway.app](https://railway.app/) 並建立/登入您的帳號。  
3. **建立 PostgreSQL 資料庫**:  
   * 在 Railway 儀表板點擊 New Project，選擇 Provision PostgreSQL。  
   * Railway 會在幾秒內幫您開好獨立的資料庫服務。
4. **連接 Web Service**:  
   * 在同一個 Project 內，點選右上角 + Create 或點選空白處。
   * 選擇 GitHub Repo，並選取您的專案來部署。
5. **設定環境變數**:  
   * 點進建立好的 Web 服務卡片，切換到 Variables 頁籤並新增變數： 
     * **Key**: DATABASE\_URL, **Value**: ${{PostgreSQL.DATABASE_URL}} (或者點選 Reference 讓系統自動帶入剛開好的 PostgreSQL URL) 
     * **Key**: API\_SECRET\_KEY, **Value**: (設定一個您自己的、複雜的密鑰，用於保護自訂觸發端點)  
6. **部署！**: Railway 會自動偵測到 `Procfile` 開始建置並啟動您的應用。一旦啟動成功，每日的背景排程便會自動生效。