import asyncio
import logging
import time
import urllib.request
import json
from typing import Optional, Dict

logger = logging.getLogger("PriceFetcher")

class PriceFetcher:
    def __init__(self, update_interval: float = 2.0):
        self.update_interval = update_interval
        self.price_cache: Dict[str, float] = {}
        self.last_update_times: Dict[str, float] = {}
        self.is_running = False
        self._consecutive_spikes = 0
        self.monitored_symbols = set(["XAUUSD"])

    def _normalize_symbol(self, raw_symbol: str) -> str:
        s = raw_symbol.upper().replace("/", "").replace("-", "").strip()
        if s in ["XAU", "GOLD", "XAUUSD", "طلا"]:
            return "XAUUSD"
        if not s.endswith("USDT") and not s.endswith("USD"):
            s = f"{s}USDT"
        return s

    # ════════════════════ قیمت انس طلا (Gold Spot) ════════════════════

    def _fetch_from_gold_api(self) -> Optional[float]:
        url = "https://api.gold-api.com/price/XAU"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            return float(price) if price else None

    def _fetch_from_binance_paxg(self) -> Optional[float]:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            return float(price) if price else None

    def _fetch_from_yahoo(self) -> Optional[float]:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data["chart"]["result"][0]["meta"].get("regularMarketPrice")
            return float(price) if price else None

    def _fetch_gold_spot(self) -> Optional[float]:
        raw_price = None
        try:
            p = self._fetch_from_gold_api()
            if p and p > 1000:
                raw_price = p
        except Exception as e:
            logger.debug(f"gold-api error: {e}")

        if not raw_price:
            try:
                p = self._fetch_from_binance_paxg()
                if p and p > 1000:
                    raw_price = p
            except Exception as e:
                logger.debug(f"binance paxg error: {e}")

        if not raw_price:
            try:
                p = self._fetch_from_yahoo()
                if p and p > 1000:
                    raw_price = p
            except Exception as e:
                logger.debug(f"yahoo error: {e}")

        if not raw_price:
            return None

        # فیلتر جهش غیرعادی طلا
        cur_gold = self.price_cache.get("XAUUSD")
        if cur_gold is not None:
            diff = abs(raw_price - cur_gold)
            if diff > 6.0:
                self._consecutive_spikes += 1
                if self._consecutive_spikes < 3:
                    logger.warning(f"جهش مشکوک طلا {raw_price} نسبت به {cur_gold} رد شد.")
                    return cur_gold
            else:
                self._consecutive_spikes = 0

        return raw_price

    # ════════════════════ قیمت کریپتو (Multi-Exchange Crypto Ticker) ════════════════════

    def _extract_coin_name(self, pair: str) -> str:
        s = pair.upper().replace("/", "").replace("-", "").strip()
        if s.endswith("USDT"):
            return s[:-4]
        if s.endswith("USD"):
            return s[:-3]
        return s

    def _fetch_mexc_futures(self, coin: str) -> Optional[float]:
        url = f"https://contract.mexc.com/api/v1/contract/ticker?symbol={coin}_USDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("data", {}).get("lastPrice")
            return float(price) if price else None

    def _fetch_mexc_spot(self, coin: str) -> Optional[float]:
        url = f"https://api.mexc.com/api/v3/ticker/price?symbol={coin}USDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            return float(price) if price else None

    def _fetch_bybit_linear(self, coin: str) -> Optional[float]:
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={coin}USDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            result_list = data.get("result", {}).get("list", [])
            if result_list:
                price = result_list[0].get("lastPrice")
                return float(price) if price else None
            return None

    def _fetch_binance_futures(self, coin: str) -> Optional[float]:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={coin}USDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            return float(price) if price else None

    def _fetch_binance_spot(self, coin: str) -> Optional[float]:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={coin}USDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            return float(price) if price else None

    def _fetch_crypto(self, pair: str) -> Optional[float]:
        coin = self._extract_coin_name(pair)

        # ۱. صرافی MEXC Futures (چون مارکت فیوچرز Ourbit دقیقاً نقدینگی و کوین‌های مشابه MEXC دارد)
        try:
            p = self._fetch_mexc_futures(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"MEXC Futures {coin} error: {e}")

        # ۲. صرافی MEXC Spot
        try:
            p = self._fetch_mexc_spot(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"MEXC Spot {coin} error: {e}")

        # ۳. صرافی Bybit Linear Tickers
        try:
            p = self._fetch_bybit_linear(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"Bybit {coin} error: {e}")

        # ۴. صرافی Binance Futures
        try:
            p = self._fetch_binance_futures(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"Binance Futures {coin} error: {e}")

        # ۵. صرافی Binance Spot
        try:
            p = self._fetch_binance_spot(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"Binance Spot {coin} error: {e}")

        return None

    # ════════════════════ دریافت قیمت عمومی ════════════════════

    def fetch_price_sync(self, symbol: str = "XAUUSD") -> Optional[float]:
        norm = self._normalize_symbol(symbol)
        now = time.time()

        # اگر کش تازه است (زیر ۱.۵ ثانیه)، همان را برگردان
        if norm in self.price_cache and (now - self.last_update_times.get(norm, 0) < 1.5):
            return self.price_cache[norm]

        if norm == "XAUUSD":
            price = self._fetch_gold_spot()
        else:
            price = self._fetch_crypto(norm)

        if price:
            self.price_cache[norm] = price
            self.last_update_times[norm] = now
            return price

        return self.price_cache.get(norm)

    def get_price(self, symbol: str = "XAUUSD") -> Optional[float]:
        norm = self._normalize_symbol(symbol)
        cached = self.price_cache.get(norm)
        if cached:
            return cached
        # اگر هنوز در کش نبود، همگام دریافت کن
        return self.fetch_price_sync(norm)

    def track_symbol(self, symbol: str):
        norm = self._normalize_symbol(symbol)
        self.monitored_symbols.add(norm)

    async def run_loop(self):
        self.is_running = True
        logger.info("⚡️ حلقه به‌روزرسانی قیمت‌های زنده فعال شد...")
        while self.is_running:
            try:
                # کپی برای جلوگیری از تغییر هم‌روند
                symbols = list(self.monitored_symbols)
                for sym in symbols:
                    p = self.fetch_price_sync(sym)
                    if p and sym == "XAUUSD":
                        logger.debug(f"قیمت زنده طلا: ${p:.2f}")
            except Exception as e:
                logger.error(f"خطا در حلقه دریافت قیمت: {e}")

            await asyncio.sleep(self.update_interval)

price_fetcher = PriceFetcher()
# برای سازگاری کامل با کدهای قبلی
gold_tracker = price_fetcher
