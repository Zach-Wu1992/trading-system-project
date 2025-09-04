# 證券自動交易模擬系統 (Automated Trading Simulation System)

# 這是一個基於 Python 的證券自動交易模擬系統，旨在展示一個完整後端應用程式的設計、開發與部署流程。系統包含歷史數據回測、即時模擬交易、以及一個用 Flask 建構的網頁儀表板，用於視覺化績效。

# 

# 主要功能

# 歷史回測 (main.py): 載入指定時間範圍的歷史股價，並根據預設的交易策略（均線交叉）進行完整的回測，計算最終報酬率。

# 

# 即時模擬交易 (realtime\_bot.py): 作為一個背景服務持續運行，使用 APScheduler 定時（例如每日收盤後）抓取最新股價，執行交易策略，並將交易與績效紀錄永久儲存於 SQLite 資料庫。

# 

# 視覺化儀表板 (dashboard.py): 一個基於 Flask 的 Web 應用程式，從資料庫讀取交易歷史和每日資產數據，並透過 Chart.js 將績效繪製成互動式曲線圖，同時以表格呈現詳細的交易紀錄。

# 

# 進階交易策略: 實現了順勢加碼（Pyramiding）與固定比例停損（Stop-loss）的風控機制。

# 

# 系統架構

# 本專案採用服務分離的架構，將「數據生產者」與「數據消費者」解耦，兩者透過共享的 SQLite 資料庫進行溝通。

# 

# +------------------------+        +--------------------------+

# |                        |        |                          |

# |  Realtime Bot          |        |  Web Dashboard (Flask)   |

# |  (realtime\_bot.py)     |        |  (dashboard.py)          |

# |  (APScheduler)         |        |                          |

# +------------------------+        +--------------------------+

# &nbsp;          |                                   ^

# &nbsp;          | Writes Trades \&                   | Reads Data

# &nbsp;          | Performance Data                  |

# &nbsp;          v                                   |

# +-------------------------------------------------------------+

# |                                                             |

# |                    SQLite Database                          |

# |                    (trading\_dashboard.db)                   |

# |                                                             |

# +-------------------------------------------------------------+

# 

# 技術棧 (Technology Stack)

# 後端: Python 3.9+

# 

# Web 框架: Flask

# 

# 數據獲取: yfinance

# 

# 數據分析: Pandas, Pandas-TA

# 

# 排程任務: APScheduler

# 

# 資料庫: SQLite3

# 

# 前端視覺化: Chart.js, Tailwind CSS

# 

# 安裝與設定

# 請依照以下步驟設定您的開發環境。

# 

# 1\. 前置需求

# 

# 已安裝 Python 3.8+ 或 Anaconda。

# 

# 已安裝 Git。

# 

# 2\. Clone 專案

# 

# git clone \[您的 GitHub Repository 網址]

# cd \[專案資料夾名稱]

# 

# 3\. 建立虛擬環境並安裝依賴

# 建議使用 Conda 建立獨立的虛擬環境：

# 

# \# 建立名為 trading\_env 的 conda 環境

# conda create --name trading\_env python=3.9

# 

# \# 啟動環境

# conda activate trading\_env

# 

# \# 使用 requirements.txt 安裝所有必要的套件

# pip install -r requirements.txt

# 

# 使用方式

# 請在不同的終端機視窗中啟動各個服務。

# 

# 1\. 產生測試數據 (可選)

# 若想快速查看儀表板效果，可以先執行測試數據生成器。

# 

# python test\_data\_generator.py

# 

# 2\. 啟動交易機器人 (背景服務)

# 此服務會定時執行並將數據寫入 trading\_dashboard.db。

# 

# python realtime\_bot.py

# 

# 3\. 啟動 Web 儀表板

# 此服務會啟動一個本地網站來顯示數據。

# 

# python dashboard.py

# 

# 啟動後，請在您的瀏覽器中開啟 http://127.0.0.1:5001 來查看儀表板。

# 

# 儀表板截圖

#<img width="2286" height="1611" alt="dashboard-screenshot" src="https://github.com/user-attachments/assets/5c03d1e3-0e94-438a-852e-074038fe5f6a" />

# 

# 未來可擴充方向

# 容器化: 使用 Docker 與 Docker Compose 將各個服務容器化，實現一鍵啟動與標準化部署。

# 

# 資料庫升級: 將資料庫從 SQLite 升級為 PostgreSQL，以支援更高的併發寫入和更複雜的查詢。

# 

# CI/CD: 建立 GitHub Actions workflow，在程式碼提交時自動執行測試。

# 

# 策略優化: 將交易策略參數化，並建立更複雜的回測分析工具。

