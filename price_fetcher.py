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
        if s in ["XAU", "GOLD", "XAUUSD", "طلا", "XAUT", "XAUTUSDT", "GOLD(XAUT)USDT"]:
            return "XAUUSD"
        if not s.endswith("USDT") and not s.endswith("USD"):
            s = f"{s}USDT"
        return s

    # ════════════════════ استعلام زنده قیمت از TradingView ════════════════════

    def _fetch_from_tradingview(self, symbol: str) -> Optional[float]:
        """دریافت مستقیم و زنده قیمت از اسکنر رسمی TradingView"""
        s = symbol.upper().replace("/", "").replace("-", "").strip()
        is_gold = s in ["XAU", "GOLD", "XAUUSD", "طلا", "XAUT", "XAUTUSDT", "GOLD(XAUT)USDT"]

        if is_gold:
            url = "https://scanner.tradingview.com/cfd/scan"
            tickers = ["TVC:GOLD", "OANDA:XAUUSD", "FOREXCOM:XAUUSD", "FX_IDC:XAUUSD"]
        else:
            url = "https://scanner.tradingview.com/crypto/scan"
            coin = s[:-4] if s.endswith("USDT") else (s[:-3] if s.endswith("USD") else s)
            tickers = [f"BINANCE:{coin}USDT", f"BYBIT:{coin}USDT", f"MEXC:{coin}USDT", f"OKX:{coin}USDT"]

        payload = {
            "symbols": {"tickers": tickers},
            "columns": ["close"]
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                rows = data.get("data", [])
                if rows:
                    for r in rows:
                        val = r.get("d", [])[0]
                        if val and float(val) > 0:
                            return float(val)
        except Exception as e:
            logger.debug(f"TradingView scan error for {symbol}: {e}")

        return None

    # ════════════════════ قیمت طلا (TradingView + Fallbacks) ════════════════════

    def _fetch_xaut_mexc(self) -> Optional[float]:
        # اولویت ۱-الف: MEXC Spot GOLD(XAUT)USDT
        try:
            url = "https://api.mexc.com/api/v3/ticker/price?symbol=GOLD(XAUT)USDT"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                p = data.get("price")
                if p and float(p) > 1000:
                    return float(p)
        except Exception as e:
            logger.debug(f"MEXC Spot GOLD(XAUT) error: {e}")

        # اولویت ۱-ب: MEXC Futures XAUT_USDT
        try:
            url = "https://contract.mexc.com/api/v1/contract/ticker?symbol=XAUT_USDT"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                p = data.get("data", {}).get("lastPrice")
                if p and float(p) > 1000:
                    return float(p)
        except Exception as e:
            logger.debug(f"MEXC Futures XAUT error: {e}")

        # اولویت ۱-ج: MEXC Spot XAUTUSDT
        try:
            url = "https://api.mexc.com/api/v3/ticker/price?symbol=XAUTUSDT"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                p = data.get("price")
                if p and float(p) > 1000:
                    return float(p)
        except Exception as e:
            logger.debug(f"MEXC Spot XAUT error: {e}")

        return None

    def _fetch_xaut_bybit(self) -> Optional[float]:
        # اولویت ۲: Bybit Spot
        try:
            url = "https://api.bybit.com/v5/market/tickers?category=spot&symbol=XAUTUSDT"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                res_list = data.get("result", {}).get("list", [])
                if res_list:
                    p = res_list[0].get("lastPrice")
                    if p and float(p) > 1000:
                        return float(p)
        except Exception as e:
            logger.debug(f"Bybit Spot XAUT error: {e}")

        # Bybit Linear
        try:
            url = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=XAUTUSDT"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                res_list = data.get("result", {}).get("list", [])
                if res_list:
                    p = res_list[0].get("lastPrice")
                    if p and float(p) > 1000:
                        return float(p)
        except Exception as e:
            logger.debug(f"Bybit Linear XAUT error: {e}")

        return None

    def _fetch_xaut_binance(self) -> Optional[float]:
        # اولویت ۳: Binance Spot
        try:
            url = "https://api.binance.com/api/v3/ticker/price?symbol=XAUTUSDT"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                p = data.get("price")
                if p and float(p) > 1000:
                    return float(p)
        except Exception as e:
            logger.debug(f"Binance Spot XAUT error: {e}")

        return None

    def _fetch_from_binance_paxg(self) -> Optional[float]:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            return float(price) if price else None

    def _fetch_from_gold_api(self) -> Optional[float]:
        url = "https://api.gold-api.com/price/XAU"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            price = data.get("price")
            return float(price) if price else None

    def _fetch_gold_price(self) -> Optional[float]:
        raw_price = None

        # اولویت ۱: قیمت چارت رسمی TradingView (TVC:GOLD / OANDA:XAUUSD)
        try:
            raw_price = self._fetch_from_tradingview("XAUUSD")
        except Exception as e:
            logger.debug(f"TradingView gold fetch error: {e}")

        # اولویت ۲ (بک‌آپ): Gold-API مستقیم جهانی (Spot XAU/USD)
        if not raw_price:
            try:
                p = self._fetch_from_gold_api()
                if p and p > 1000:
                    raw_price = p
            except Exception:
                pass

        # اولویت ۳ (بک‌آپ): PAXG بایننس
        if not raw_price:
            try:
                p = self._fetch_from_binance_paxg()
                if p and p > 1000:
                    raw_price = p
            except Exception:
                pass

        # اولویت ۴ (بک‌آپ): صرافی‌های کریپتو (MEXC / Bybit)
        if not raw_price:
            raw_price = self._fetch_xaut_mexc() or self._fetch_xaut_bybit() or self._fetch_xaut_binance()

        if not raw_price:
            return None

        # فیلتر جهش غیرعادی طلا
        cur_gold = self.price_cache.get("XAUUSD") or self.price_cache.get("XAUTUSDT")
        if cur_gold is not None:
            diff = abs(raw_price - cur_gold)
            if diff > 15.0:
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
        # اولویت ۱: استعلام زنده و مستقیم از TradingView
        try:
            tv_p = self._fetch_from_tradingview(pair)
            if tv_p and tv_p > 0:
                return tv_p
        except Exception as e:
            logger.debug(f"TradingView crypto error {pair}: {e}")

        coin = self._extract_coin_name(pair)

        # اولویت ۲: صرافی MEXC Futures (چون مارکت فیوچرز Ourbit دقیقاً نقدینگی و کوین‌های مشابه MEXC دارد)
        try:
            p = self._fetch_mexc_futures(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"MEXC Futures {coin} error: {e}")

        # اولویت ۳: صرافی MEXC Spot
        try:
            p = self._fetch_mexc_spot(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"MEXC Spot {coin} error: {e}")

        # اولویت ۴: صرافی Bybit Linear Tickers
        try:
            p = self._fetch_bybit_linear(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"Bybit {coin} error: {e}")

        # اولویت ۵: صرافی Binance Futures
        try:
            p = self._fetch_binance_futures(coin)
            if p and p > 0:
                return p
        except Exception as e:
            logger.debug(f"Binance Futures {coin} error: {e}")

        # اولویت ۶: صرافی Binance Spot
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

        if norm in ["XAUUSD", "XAUTUSDT", "GOLD"]:
            price = self._fetch_gold_price()
        else:
            price = self._fetch_crypto(norm)

        if price:
            self.price_cache[norm] = price
            if norm in ["XAUUSD", "XAUTUSDT", "GOLD"]:
                self.price_cache["XAUUSD"] = price
                self.price_cache["XAUTUSDT"] = price
                self.price_cache["GOLD"] = price
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

    def get_gold_price(self) -> Optional[float]:
        return self.get_price("XAUUSD")

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
                    if p and sym in ["XAUUSD", "XAUTUSDT", "GOLD"]:
                        logger.debug(f"قیمت زنده طلا (TradingView): ${p:.2f}")
            except Exception as e:
                logger.error(f"خطا در حلقه دریافت قیمت: {e}")

            await asyncio.sleep(self.update_interval)

price_fetcher = PriceFetcher()
# برای سازگاری کامل با کدهای قبلی
gold_tracker = price_fetcher
get_price = price_fetcher.get_price
get_gold_price = price_fetcher.get_gold_price
