import os
import time
import requests
import datetime
import pandas as pd
from fugle_marketdata import RestClient

# --- 45 檔監控名單 ---
WATCH_LIST = [
    "2330", "2317", "2454", "2303", "2308", "3037", "3035", "2382", "3017", "6669",
    "2357", "3231", "2376", "2353", "2324", "2356", "2377", "2395", "4938", "2408",
    "2449", "3711", "2337", "2344", "2379", "3034", "3661", "5269", "6415", "8046",
    "3189", "3532", "6488", "3406", "3008", "2313", "2368", "6213", "6271", "3376",
    "1513", "1519", "1503", "1504", "1514"
]

FUGLE_API_KEY = os.getenv("FUGLE_API_KEY")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

vsa_memory = {} # 儲存每檔股票的高量陰線數值

def send_telegram_msg(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        print(f"Telegram 配置缺失: {message}")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, timeout=10)
        res.raise_for_status()
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")

def get_vsa_setup(client, symbol):
    """找出 20 天內的高量陰線高點與成交量"""
    try:
        # 修改點：補齊富果 API 要求的必填欄位，避免 Status 400 錯誤
        res = client.stock.historical.candles(
            symbol=symbol, 
            timeframe='D', 
            fields=['open', 'high', 'low', 'close', 'volume', 'turnover', 'change']
        )
        
        if not res or 'data' not in res:
            return None
            
        df = pd.DataFrame(res['data'])
        if df.empty: return None
        
        # 找出陰線 (收盤 < 開盤)
        bear_candles = df[df['close'] < df['open']]
        if bear_candles.empty: return None
        
        # 找出成交量最大的那一根陰線 (High Volume Bearish Candle)
        hvbc = bear_candles.loc[bear_candles['volume'].idxmax()]
        return {
            "high_target": hvbc['high'],
            "hvbc_vol": hvbc['volume'],
            "triggered": False
        }
    except Exception as e:
        print(f"初始化 {symbol} 失敗: {e}")
        return None

def start_monitor():
    if not FUGLE_API_KEY:
        print("錯誤: 找不到 FUGLE_API_KEY")
        return

    client = RestClient(api_key=FUGLE_API_KEY)
    send_telegram_msg("🚀 VSA 縮量突破監控啟動\n策略：突破高量陰線 + 籌碼真空判定")

    while True:
        # 處理台灣時區 (UTC+8)
        tz_tw = datetime.timezone(datetime.timedelta(hours=8))
        now = datetime.datetime.now(tz_tw)
        current_time = now.strftime("%H:%M")
        
        # 盤後自動停止 (13:35 停止監控)
        if current_time > "13:35":
            send_telegram_msg("🔔 盤後時間已到，停止今日監控。")
            break

        # 開盤時間監控
        if "09:00" <= current_time <= "13:35":
            print(f"--- 開始新一輪掃描 ({current_time}) ---")
            for symbol in WATCH_LIST:
                # 1. 取得 VSA 基準資料
                if symbol not in vsa_memory:
                    vsa_memory[symbol] = get_vsa_setup(client, symbol)
                    time.sleep(0.1) # 緩衝避開頻率限制
                
                setup = vsa_memory.get(symbol)
                if not setup or setup["triggered"]: continue

                try:
                    # 2. 取得今日即時行情
                    quote = client.stock.intraday.quote(symbol=symbol)
                    price = quote.get('lastPrice')
                    
                    total_info = quote.get('total', {})
                    volume = total_info.get('tradeVolume', 0) if total_info else 0
                    
                    # 偵錯心跳線：讓您在 GitHub Actions 日誌中確認數據有正常抓到
                    if price:
                        print(f"偵測中... {symbol} | 現價: {price} | 目標價: {setup['high_target']}")

                    if not price or not volume: continue

                    # 3. 判斷邏輯：突破高點 且 今日總量尚未超越當初的高量陰線 (縮量突破)
                    if price > setup["high_target"] and volume < setup["hvbc_vol"]:
                        msg = (f"🎯 VSA 突破訊號！\n"
                               f"標的：{symbol}\n"
                               f"現價：{price} (突破壓力 {setup['high_target']})\n"
                               f"今日成交量：{volume} (低於高量陰線 {setup['hvbc_vol']})\n"
                               f"狀態：縮量創高，疑似主力高度控盤")
                        send_telegram_msg(msg)
                        setup["triggered"] = True # 避免重複提醒
                    
                    time.sleep(0.5) # 符合 Fugle 每秒請求限制
                except Exception as e:
                    print(f"監控 {symbol} 時發生異常: {e}")
                    continue
        else:
            print(f"等待開盤中... 目前時間: {current_time}")
        
        # 每一分鐘輪詢一次全名單
        time.sleep(60)

if __name__ == "__main__":
    start_monitor()