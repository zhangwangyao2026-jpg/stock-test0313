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

vsa_memory = {} 

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
    """找出 20 天內的高量陰線"""
    try:
        # 修正策略：不手動指定 fields，讓 SDK 抓取預設全部欄位，避開 400 錯誤
        res = client.stock.historical.candles(
            symbol=symbol, 
            timeframe='D'
        )
        
        if not res or 'data' not in res or len(res['data']) == 0:
            print(f"⚠️ {symbol} 無歷史資料")
            return None
            
        df = pd.DataFrame(res['data'])
        
        # 檢查必要欄位是否存在
        required_cols = ['open', 'close', 'high', 'volume']
        if not all(col in df.columns for col in required_cols):
            print(f"⚠️ {symbol} 資料欄位不全: {df.columns.tolist()}")
            return None
        
        # 找出陰線 (收盤 < 開盤)
        bear_candles = df[df['close'] < df['open']]
        if bear_candles.empty: 
            return None
        
        # 找出成交量最大的陰線
        hvbc = bear_candles.loc[bear_candles['volume'].idxmax()]
        return {
            "high_target": hvbc['high'],
            "hvbc_vol": hvbc['volume'],
            "triggered": False
        }
    except Exception as e:
        print(f"❌ 初始化 {symbol} 失敗: {e}")
        return None

def start_monitor():
    if not FUGLE_API_KEY:
        print("❌ 錯誤: 找不到 FUGLE_API_KEY")
        return

    client = RestClient(api_key=FUGLE_API_KEY)
    send_telegram_msg("🚀 VSA 監控已修正啟動\n(已移除強制欄位限制以避開 API 400 錯誤)")

    while True:
        tz_tw = datetime.timezone(datetime.timedelta(hours=8))
        now = datetime.datetime.now(tz_tw)
        current_time = now.strftime("%H:%M")
        
        if current_time > "13:35":
            send_telegram_msg("🔔 盤後時間，停止監控。")
            break

        if "09:00" <= current_time <= "13:35":
            print(f"\n--- 掃描時間: {current_time} ---")
            for symbol in WATCH_LIST:
                # 取得或初始化 VSA 資料
                if symbol not in vsa_memory:
                    vsa_memory[symbol] = get_vsa_setup(client, symbol)
                    time.sleep(0.15) 
                
                setup = vsa_memory.get(symbol)
                if not setup or setup["triggered"]: continue

                try:
                    quote = client.stock.intraday.quote(symbol=symbol)
                    price = quote.get('lastPrice')
                    volume = quote.get('total', {}).get('tradeVolume', 0)
                    
                    if not price or not volume: continue

                    # 偵錯 Log
                    print(f"[{symbol}] 現價: {price} | 目標: {setup['high_target']} | 量: {volume}/{setup['hvbc_vol']}")

                    # VSA 邏輯判斷
                    if price > setup["high_target"] and volume < setup["hvbc_vol"]:
                        msg = (f"🎯 VSA 突破訊號！\n標的：{symbol}\n"
                               f"現價：{price} (壓力 {setup['high_target']})\n"
                               f"成交量：{volume} (低量突破 {setup['hvbc_vol']})")
                        send_telegram_msg(msg)
                        setup["triggered"] = True 
                    
                    time.sleep(0.1) # 快速輪詢
                except Exception as e:
                    continue
        else:
            print(f"非開盤時間 ({current_time})，每 10 分鐘檢查一次...")
            time.sleep(600)
            continue
            
        time.sleep(60)

if __name__ == "__main__":
    start_monitor()