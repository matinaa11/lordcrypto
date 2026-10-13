import asyncio
import logging
import time
import urllib.request
import json

logger = logging.getLogger("GoldTracker")

class GoldTracker:
    def __init__(self, update_interval: float = 2.0):
        self.update_interval = update_interval
        self.current_price: float | None = None
        self.last_update_time: float = 0
        self.is_running = False

    def _fetch_from_gold_api(self) -> float | None:
        url = "https://api.gold-api.com/price/XAU"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return float(data.get("price"))

    def _fetch_from_yahoo(self) -> float | None:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])

    def _fetch_from_binance(self) -> float | None:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return float(data.get("price"))

    def fetch_price_sync(self) -> float | None:
        """
        تلاش برای دریافت قیمت از چند منبع با اولویت (Fallback Mechanism)
        """
        # ۱. منبع اول: gold-api.com (Spot XAUUSD)
        try:
            p = self._fetch_from_gold_api()
            if p: return p
        except Exception as e:
            logger.debug(f"gold-api error: {e}")

        # ۲. منبع دوم: بایننس (روی سرورهای خارجی ریل‌وی بدون تحریم کار می‌کند)
        try:
            p = self._fetch_from_binance()
            if p: return p
        except Exception as e:
            logger.debug(f"binance error: {e}")

        # ۳. منبع سوم: یاهو فایننس (انس جهانی)
        try:
            p = self._fetch_from_yahoo()
            if p: return p
        except Exception as e:
            logger.debug(f"yahoo error: {e}")

        return None

    async def run_loop(self):
        """
        حلقه نامتقارن برای بروزرسانی قیمت هر چند ثانیه یکبار
        """
        self.is_running = True
        logger.info("📡 رصدگر قیمت لحظه‌ای طلای جهانی استارت شد...")

        loop = asyncio.get_running_loop()
        while self.is_running:
            try:
                # اجرای فراخوانی شبکه در ترد جداگانه تا ایونت‌لوپ مسدود نشود
                price = await loop.run_in_executor(None, self.fetch_price_sync)
                if price:
                    self.current_price = round(price, 2)
                    self.last_update_time = time.time()
                    logger.debug(f"قیمت لحظه‌ای طلا: {self.current_price} دلار")
            except Exception as e:
                logger.error(f"خطا در دریافت قیمت طلا: {e}")

            await asyncio.sleep(self.update_interval)

    def get_price(self) -> float | None:
        """
        برگرداندن آنی قیمت کش‌شده در حافظه (بدون هیچ تاخیر و پینگ شبکه)
        """
        return self.current_price

# نمونه سراسری
gold_tracker = GoldTracker(update_interval=2.0)
