import requests
import json

# --- 設定 ---
# 您的 Flask 應用程式執行的位址
API_URL = "http://localhost:5001/api/trigger-trade-check"

# 這個金鑰必須與您 app.py 中 API_SECRET_KEY 的值完全相同
API_KEY = "my_super_secret_key_123"

def call_trading_api():
    """
    發送一個 POST 請求來觸發交易檢查 API。
    """
    print("🚀 正在準備發送 API 請求...")
    
    # 設定請求標頭 (Header)，包含我們的授權金鑰
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # 發送 POST 請求
        response = requests.post(API_URL, headers=headers)
        
        # 檢查回應狀態碼
        if response.status_code == 200:
            print("✅ API 請求成功！")
            print("   伺服器回應:", response.json())
        elif response.status_code == 401:
            print("❌ API 請求失敗：未經授權 (401)")
            print("   請檢查 test_api_caller.py 和 app.py 中的 API_SECRET_KEY 是否完全相同。")
        else:
            print(f"❌ API 請求失敗，狀態碼: {response.status_code}")
            print("   伺服器錯誤訊息:", response.text)
            
    except requests.exceptions.ConnectionError as e:
        print("❌ 連線錯誤！")
        print("   請確認您的 Flask 應用程式 (app.py) 正在另一個終端機中正常運行。")
    except Exception as e:
        print(f"❌ 發生未知錯誤: {e}")

if __name__ == "__main__":
    call_trading_api()