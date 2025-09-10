import sys
import subprocess

print("="*50)
print("🐍 Python 環境檢查報告 🐍")
print("="*50)

# 1. 顯示目前正在執行此腳本的 Python 直譯器路徑
print(f"🔄 當前 Python 直譯器路徑:\n   {sys.executable}\n")

# 2. 顯示目前環境中已安裝的套件列表
print("📦 正在檢查已安裝的套件...")
try:
    # 使用 subprocess 來執行 pip list，結果更可靠
    installed_packages = subprocess.check_output([sys.executable, '-m', 'pip', 'list']).decode('utf-8')
    print(installed_packages)
    
    # 3. 明確檢查 yfinance 是否存在
    if 'yfinance' in installed_packages.lower():
        print("✅ --- 檢查結果：'yfinance' 套件已安裝！ --- ✅")
    else:
        print("❌ --- 檢查結果：找不到 'yfinance' 套件！ --- ❌")
        print("   請依照指示，在此環境中執行 'pip install yfinance'")

except Exception as e:
    print(f"\n❌ 無法執行 'pip list'。錯誤: {e}")

print("="*50)
