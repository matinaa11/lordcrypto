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
        self._consecutive_spikes = 0

    def _fetch_from_gold_api(self) -> float | None:
        """
        منبع اول: نرخ اسپات لحظه‌ای طلای جهانی (Spot XAU/USD)
        """
        url = "https://api.gold-api.com/price/XAU"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            if price:
                return float(price)
            return None

    def _fetch_from_binance(self) -> float | None:
        """
        منبع دوم: توکن طلای بایننس با پشتوانه فیزیکی طلا (PAXGUSDT)
        قیمت PAXG دقیقاً برابر با انس اسپات طلا است.
        """
        url = "https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            if price:
                return float(price)
            return None

    def _fetch_from_yahoo(self) -> float | None:
        """
        منبع سوم: یاهو فایننس جفت‌ارز اسپات طلا (XAUUSD=X)
        توجه مهم: هرگز از GC=F (فیوچرز کامکس با اختلاف ۲۰ دلار) استفاده نمی‌شود!
        """
        url = "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            if price:
                return float(price)
            return None

    def fetch_price_sync(self) -> float | None:
        """
        دریافت قیمت اسپات واقعی طلا با سیستم Fallback و فیلتر جهش کاذب
        """
        raw_price = None

        # ۱. تلاش از منبع اصلی Spot XAUUSD
        try:
            p = self._fetch_from_gold_api()
            if p and p > 1000:
                raw_price = p
        except Exception as e:
            logger.debug(f"gold-api error: {e}")

        # ۲. تلاش از بایننس PAXGUSDT (روی سرور بدون تحریم کار می‌کند)
        if not raw_price:
            try:
                p = self._fetch_from_binance()
                if p and p > 1000:
                    raw_price = p
            except Exception as e:
                logger.debug(f"binance error: {e}")

        # ۳. تلاش از یاهو فایننس (جفت‌ارز فارکس اسپات XAUUSD=X و نه فیوچرز GC=F)
        if not raw_price:
            try:
                p = self._fetch_from_yahoo()
                if p and p > 1000:
                    raw_price = p
            except Exception as e:
                logger.debug(f"yahoo spot error: {e}")

        if not raw_price:
            return None

        # فیلتر حفاظتی جهش غیرعادی (Spike Filter):
        # اگر منبعی به اشتباه قیمتی با اختلاف بیش از ۶ دلار نسبت به قیمت قبلی بدهد (مثلاً پرش ۲۰ دلاری فیوچرز)،
        # بلافاصله رد می‌شود تا استاپ‌لاس کاذب نخورد.
        if self.current_price is not None:
            diff = abs(raw_price - self.current_price)
            if diff > 6.0:
                logger.warning(
                    f"⚠️ پرش غیرعادی قیمت رد شد: قیمت قبلی={self.current_price:.2f} | قیمت دریافتی={raw_price:.2f} (اختلاف={diff:.2f}$)"
                )
                self._consecutive_spikes += 1
                if self._consecutive_spikes < 3:
                    # قیمت غیرعادی رد می‌شود و قیمت قبلی معتبر می‌ماند
                    return self.current_price
            else:
                self._consecutive_spikes = 0

        return raw_price

    async def run_loop(self):
        self.is_running = True
        logger.info("📡 رصدگر قیمت لحظه‌ای طلای جهانی (Spot XAUUSD) استارت شد...")

        loop = asyncio.get_running_loop()
        while self.is_running:
            try:
                price = await loop.run_in_executor(None, self.fetch_price_sync)
                if price:
                    self.current_price = round(price, 2)
                    self.last_update_time = time.time()
                    logger.debug(f"قیمت لحظه‌ای طلا: {self.current_price} دلار")
            except Exception as e:
                logger.error(f"خطا در دریافت قیمت طلا: {e}")

            await asyncio.sleep(self.update_interval)

    def get_price(self) -> float | None:
        return self.current_price

# نمونه سراسری
gold_tracker = GoldTracker(update_interval=2.0)
