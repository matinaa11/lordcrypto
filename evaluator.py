import logging
import time
import json
import os
from typing import Optional, Dict, Any, List, Tuple, Callable

logger = logging.getLogger("Evaluator")

DEFAULT_SETTINGS = {
    "balance": 15.0,              # سرمایه اولیه دلاری
    "mode": "OURBIT_FUTURES",     # OURBIT_FUTURES یا FOREX_MT5
    "leverage": 100,              # ضریب اهرم فیوچرز
    "lot_size": 0.01,             # حجم معامله فارکس به لات
    "fee_rate": 0.04,             # درصد کارمزد صرافی در هر طرف معامله (Ourbit Taker: 0.04%)
    "order_type": "MARKET"        # نوع سفارش: MARKET (0.04%) یا LIMIT (0.02%)
}

def format_price(p: Optional[float]) -> str:
    """فرمت هوشمند قیمت با دقت مناسب برای طلا و آلت‌کوین‌ها"""
    if p is None:
        return "N/A"
    if p >= 100:
        return f"{p:.2f}"
    elif p >= 1:
        return f"{p:.4f}"
    elif p >= 0.001:
        return f"{p:.5f}"
    else:
        return f"{p:.7f}"


class SignalEvaluator:
    def __init__(
        self, 
        history_file: str = "trade_history.json", 
        active_file: str = "active_signal.json", 
        settings_file: str = "settings.json",
        default_budget: float = 15.0
    ):
        data_dir = os.getenv("DATA_DIR", ".").strip()
        if data_dir and data_dir != ".":
            import shutil
            os.makedirs(data_dir, exist_ok=True)
            self.history_file = os.path.join(data_dir, os.path.basename(history_file))
            self.active_file = os.path.join(data_dir, os.path.basename(active_file))
            self.settings_file = os.path.join(data_dir, os.path.basename(settings_file))

            # مهاجرت خودکار فایل‌های قبلی به Volume پایدار در صورت وجود
            for old_p, new_p in [(history_file, self.history_file), (active_file, self.active_file), (settings_file, self.settings_file)]:
                if os.path.exists(old_p) and not os.path.exists(new_p) and os.path.abspath(old_p) != os.path.abspath(new_p):
                    try:
                        shutil.copy2(old_p, new_p)
                        logger.info(f"📦 فایل {old_p} با موفقیت به مسیر پایدار {new_p} کپی شد.")
                    except Exception as e:
                        logger.error(f"خطا در کپی فایل به ولوم: {e}")
        else:
            self.history_file = history_file
            self.active_file = active_file
            self.settings_file = settings_file
        
        self.settings: Dict[str, Any] = self._load_settings()
        if default_budget != 15.0 and "balance" not in self.settings:
            self.settings["balance"] = default_budget
            
        self.trade_history: List[Dict[str, Any]] = self._load_history()
        # دیکشنری معاملات باز به تفکیک کانال: {channel_name: signal_dict}
        self.active_signals: Dict[str, Dict[str, Any]] = self._load_active_signals()
        self.signal_counter: int = self._determine_counter()

    # ════════════════════ سازگاری با کدهای تک‌کاناله قبلی ════════════════════
    @property
    def active_signal(self) -> Optional[Dict[str, Any]]:
        if "lordxau" in self.active_signals and not self.active_signals["lordxau"].get("is_closed"):
            return self.active_signals["lordxau"]
        for sig in self.active_signals.values():
            if sig and not sig.get("is_closed"):
                return sig
        return None

    @active_signal.setter
    def active_signal(self, val: Optional[Dict[str, Any]]):
        if val is None:
            pass
        else:
            ch = val.get("source_channel", "lordxau").lower().replace("@", "").strip()
            self.active_signals[ch] = val
            self._save_active_signals()

    # ════════════════════ مدیریت تنظیمات سرمایه و کارمزد ════════════════════

    def _load_settings(self) -> Dict[str, Any]:
        settings = DEFAULT_SETTINGS.copy()
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    settings.update(data)
            except Exception as e:
                logger.error(f"خطا در خواندن فایل تنظیمات: {e}")
        return settings

    def _save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"خطا در ذخیره فایل تنظیمات: {e}")

    @property
    def trade_budget(self) -> float:
        return float(self.settings.get("balance", 15.0))

    def set_balance(self, new_balance: float) -> str:
        if new_balance <= 0:
            return "❌ مبلغ سرمایه باید بزرگتر از صفر باشد."
        self.settings["balance"] = round(new_balance, 2)
        self._save_settings()
        for sig in self.active_signals.values():
            if sig and not sig.get("is_closed"):
                sig["settings"]["balance"] = self.settings["balance"]
        self._save_active_signals()
        return f"✅ سرمایه مارجین با موفقیت به <b>${self.settings['balance']:.2f}</b> تنظیم شد."

    def set_budget(self, new_budget: float) -> str:
        return self.set_balance(new_budget)

    def set_mode(self, mode: str) -> str:
        mode_clean = mode.upper().strip()
        if mode_clean in ["OURBIT_FUTURES", "OURBIT", "FUTURES", "اوربیت", "فیوچرز"]:
            self.settings["mode"] = "OURBIT_FUTURES"
            label = "صرافی Ourbit (فیوچرز با اهرم)"
        elif mode_clean in ["FOREX_MT5", "FOREX", "MT5", "فارکس", "متاتریدر"]:
            self.settings["mode"] = "FOREX_MT5"
            label = "Forex MT5 (معاملات بر اساس حجم لات)"
        else:
            return "❌ حالت نامعتبر است. فقط `OURBIT_FUTURES` یا `FOREX_MT5` مجاز هستند."
        self._save_settings()
        return f"✅ پلتفرم معاملاتی به <b>{label}</b> تغییر یافت."

    def set_leverage(self, leverage: int) -> str:
        if leverage < 1 or leverage > 1000:
            return "❌ ضریب اهرم باید عددی بین ۱ تا ۱۰۰۰ باشد."
        self.settings["leverage"] = int(leverage)
        self._save_settings()
        return f"✅ ضریب اهرم فیوچرز به <b>{leverage}x</b> تنظیم شد."

    def set_lot_size(self, lot: float) -> str:
        if lot <= 0 or lot > 100:
            return "❌ حجم لات باید عددی مثبت باشد (مثلاً 0.01 یا 0.05)."
        self.settings["lot_size"] = round(lot, 2)
        self._save_settings()
        return f"✅ حجم معامله فارکس به <b>{lot:.2f} لات</b> تنظیم شد."

    def set_fee_rate(self, fee_percent: float) -> str:
        if fee_percent < 0 or fee_percent > 5:
            return "❌ درصد کارمزد نامعتبر است (معمولاً بین 0.02% تا 0.1%)."
        self.settings["fee_rate"] = round(fee_percent, 4)
        self._save_settings()
        return f"✅ نرخ کارمزد صرافی به <b>{fee_percent:.2f}%</b> تنظیم شد."

    def set_order_type(self, order_type: str) -> str:
        ot = order_type.upper().strip()
        if ot in ["MARKET", "مارکت", "TAKER"]:
            self.settings["order_type"] = "MARKET"
            self.settings["fee_rate"] = 0.04
            msg = "مارکت (Taker) با کارمزد پیش‌فرض 0.04%"
        elif ot in ["LIMIT", "لیمیت", "MAKER"]:
            self.settings["order_type"] = "LIMIT"
            self.settings["fee_rate"] = 0.02
            msg = "لیمیت (Maker) با کارمزد پیش‌فرض 0.02%"
        else:
            return "❌ نوع سفارش نامعتبر است (فقط MARKET یا LIMIT)."
        self._save_settings()
        return f"✅ نوع سفارش به <b>{msg}</b> تنظیم شد."

    def get_settings_summary_text(self) -> str:
        s = self.settings
        mode = s.get("mode", "OURBIT_FUTURES")
        mode_label = "🪙 Ourbit فیوچرز (مارجین + اهرم)" if mode == "OURBIT_FUTURES" else "📈 Forex MT5 (حجم لات)"
        
        return (
            f"⚙️ <b>تنظیمات فعلی مدیریت سرمایه و کارمزد:</b>\n\n"
            f"🔄 <b>پلتفرم معاملاتی:</b> <code>{mode_label}</code>\n"
            f"💰 <b>سرمایه مارجین:</b> <code>${float(s.get('balance', 15.0)):.2f}</code>\n"
            f"⚡️ <b>اهرم فیوچرز (Ourbit):</b> <code>{int(s.get('leverage', 100))}x</code>\n"
            f"📊 <b>حجم معامله (Forex MT5):</b> <code>{float(s.get('lot_size', 0.01))} Lot</code>\n"
            f"💸 <b>نرخ کارمزد صرافی:</b> <code>{float(s.get('fee_rate', 0.04)):.2f}%</code> ({s.get('order_type', 'MARKET')})\n"
            f"🪙 <b>قرارداد طلا در Ourbit:</b> <code>GOLD(XAUT)USDT</code>\n"
        )

    # ════════════════════ محاسبات دقیق سود و کارمزد ════════════════════

    def calculate_trade_metrics(
        self, 
        entry_price: float, 
        price_diff: float, 
        custom_settings: Optional[Dict[str, Any]] = None,
        custom_leverage: Optional[int] = None
    ) -> Dict[str, Any]:
        s = custom_settings or self.settings
        mode = s.get("mode", "OURBIT_FUTURES")
        fee_rate = float(s.get("fee_rate", 0.04)) / 100.0
        balance = float(s.get("balance", 15.0))

        if mode == "OURBIT_FUTURES":
            leverage = custom_leverage if custom_leverage else int(s.get("leverage", 100))
            position_value = balance * leverage
            quantity = position_value / entry_price if entry_price > 0 else 0.0
            used_margin = balance

            gross_pnl = quantity * price_diff
            entry_fee = position_value * fee_rate
            exit_position_val = quantity * (entry_price + price_diff) if entry_price > 0 else position_value
            exit_fee = exit_position_val * fee_rate
            total_fee = entry_fee + exit_fee

            net_pnl = gross_pnl - total_fee
            net_pct = (net_pnl / balance * 100.0) if balance > 0 else 0.0
            liq_distance_dollars = (entry_price / leverage) * 0.9 if leverage > 0 else 0.0

        else:
            lot = float(s.get("lot_size", 0.01))
            gold_oz = lot * 100.0
            position_value = gold_oz * entry_price
            used_margin = (position_value / 100.0)

            gross_pnl = gold_oz * price_diff
            total_fee = position_value * (fee_rate * 2)
            net_pnl = gross_pnl - total_fee
            net_pct = (net_pnl / used_margin * 100.0) if used_margin > 0 else 0.0
            liq_distance_dollars = (used_margin / gold_oz) if gold_oz > 0 else 0.0

        return {
            "mode": mode,
            "balance": balance,
            "leverage": leverage if mode == "OURBIT_FUTURES" else None,
            "position_value": round(position_value, 2),
            "used_margin": round(used_margin, 2),
            "quantity": round(quantity if mode == "OURBIT_FUTURES" else gold_oz, 4),
            "gold_oz": round(quantity if mode == "OURBIT_FUTURES" else gold_oz, 4),
            "gross_pnl": round(gross_pnl, 2),
            "total_fee": round(total_fee, 2),
            "net_pnl": round(net_pnl, 2),
            "net_pct": round(net_pct, 1),
            "liq_distance_dollars": round(liq_distance_dollars, 4)
        }

    # ════════════════════ دیتابیس پایدار و بازیابی ════════════════════

    def _determine_counter(self) -> int:
        if self.trade_history:
            return max(t.get("number", 0) for t in self.trade_history)
        return 0

    def _load_history(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"خطا در خواندن تاریخچه: {e}")
        return []

    def _save_history(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.trade_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"خطا در ذخیره تاریخچه: {e}")

    def _load_active_signals(self) -> Dict[str, Dict[str, Any]]:
        signals = {}
        if os.path.exists(self.active_file):
            try:
                with open(self.active_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    now = time.time()
                    if isinstance(data, dict):
                        # بررسی ساختار جدید دیکشنری کانال‌ها: {channel: signal}
                        if any("direction" in v for v in data.values() if isinstance(v, dict)):
                            for ch, sig in data.items():
                                if isinstance(sig, dict) and not sig.get("is_closed"):
                                    if now - sig.get("created_at", 0) < 172800:
                                        signals[ch.lower().replace("@", "").strip()] = sig
                        # بررسی ساختار قدیمی تک‌سیگنالی
                        elif "direction" in data and not data.get("is_closed"):
                            ch = data.get("source_channel", "lordxau").lower().replace("@", "").strip()
                            signals[ch] = data
            except Exception as e:
                logger.error(f"خطا در بازیابی سیگنال‌های فعال: {e}")
        return signals

    def _save_active_signals(self):
        try:
            active_map = {}
            for ch, sig in self.active_signals.items():
                if sig and not sig.get("is_closed"):
                    saved_copy = sig.copy()
                    if "profit_alerted_levels" in saved_copy and isinstance(saved_copy["profit_alerted_levels"], set):
                        saved_copy["profit_alerted_levels"] = list(saved_copy["profit_alerted_levels"])
                    active_map[ch] = saved_copy

            if active_map:
                with open(self.active_file, "w", encoding="utf-8") as f:
                    json.dump(active_map, f, ensure_ascii=False, indent=2)
            else:
                if os.path.exists(self.active_file):
                    os.remove(self.active_file)
        except Exception as e:
            logger.error(f"خطا در ذخیره سیگنال‌های فعال: {e}")

    def _save_active_signal(self):
        self._save_active_signals()

    def has_active_trade(self, source_channel: Optional[str] = None) -> bool:
        """بررسی وجود سیگنال باز و فعال برای کانال مشخص یا هر کانال"""
        if not self.active_signals:
            self.active_signals = self._load_active_signals()

        if source_channel:
            clean_ch = source_channel.lower().replace("@", "").strip()
            sig = self.active_signals.get(clean_ch)
            return bool(sig and not sig.get("is_closed"))

        return any(bool(s and not s.get("is_closed")) for s in self.active_signals.values())

    # ════════════════════ ثبت و مانیتورینگ سیگنال‌ها (ایزوله به ازای هر کانال) ════════════════════

    def _parse_entry_range(self, entry_raw: str, current_price: Optional[float]) -> Tuple[float, float]:
        if not entry_raw:
            p = current_price or 0.0
            return (p, p)

        raw = entry_raw.replace(" ", "").strip()
        parts = []
        if "/" in raw:
            parts = raw.split("/")
        elif "-" in raw:
            parts = raw.split("-")
        else:
            parts = [raw]

        nums = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                pass

        if len(nums) >= 2:
            return (min(nums[0], nums[1]), max(nums[0], nums[1]))
        elif len(nums) == 1:
            return (nums[0], nums[0])
        else:
            p = current_price or 0.0
            return (p, p)

    def register_entry(
        self, 
        direction: str, 
        entry_raw: str, 
        current_price: Optional[float],
        source_channel: str = "lordxau",
        channel_title: str = "LORD XAU (XAUT/USDT)",
        symbol: str = "XAUTUSDT",
        stop_loss: Optional[float] = None,
        tp1_price: Optional[float] = None,
        tp2_price: Optional[float] = None,
        tp3_price: Optional[float] = None,
        leverage: Optional[int] = None,
        market_type: str = "GOLD",
        risk_percent: Optional[float] = None
    ) -> Tuple[int, str]:
        clean_ch = source_channel.lower().replace("@", "").strip()

        # اگر برای این کانال معامله بازی از قبل وجود داشت، آن را به عنوان منقضی شده ببند
        if clean_ch in self.active_signals and not self.active_signals[clean_ch].get("is_closed"):
            self.close_trade(
                outcome="EXPIRED",
                reason=f"سیگنال جدید در کانال {channel_title} صادر شد و معامله قبلی جایگزین گردید.",
                exit_price=current_price,
                source_channel=clean_ch
            )

        self.signal_counter += 1
        sig_num = self.signal_counter

        dir_clean = "BUY" if ("buy" in direction.lower() or "long" in direction.lower() or "بای" in direction.lower()) else "SELL"

        # محاسبه ورود و حد ضرر پیش‌فرض
        if symbol in ["XAUUSD", "XAUTUSDT"] or market_type == "GOLD":
            entry_min, entry_max = self._parse_entry_range(entry_raw, current_price)
            mid_entry = (entry_min + entry_max) / 2 if (entry_min and entry_max) else (current_price or 0.0)
            default_sl = stop_loss if stop_loss else (round(mid_entry - 3.0, 2) if dir_clean == "BUY" else round(mid_entry + 3.0, 2))
        else: # Crypto
            mid_entry = current_price or 0.0
            entry_min, entry_max = mid_entry, mid_entry
            default_sl = stop_loss if stop_loss else (round(mid_entry * 0.97, 5) if dir_clean == "BUY" else round(mid_entry * 1.03, 5))

        sig_settings = self.settings.copy()
        sig_lev = leverage if leverage else (20 if market_type == "CRYPTO" else int(sig_settings.get("leverage", 100)))
        sig_settings["leverage"] = sig_lev

        init_metrics = self.calculate_trade_metrics(mid_entry, 0.0, sig_settings, custom_leverage=sig_lev)

        new_sig = {
            "id": int(time.time()),
            "number": sig_num,
            "source_channel": clean_ch,
            "channel_title": channel_title,
            "symbol": symbol,
            "market_type": market_type,
            "direction": dir_clean,
            "entry_min": entry_min,
            "entry_max": entry_max,
            "entry_price": mid_entry,
            "entry_raw": entry_raw,
            "stop_loss": default_sl,
            "is_default_sl": (stop_loss is None),
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp3_price": tp3_price,
            "leverage": sig_lev,
            "risk_percent": risk_percent,
            "settings": sig_settings,
            "budget": sig_settings.get("balance", 15.0),
            "total_fee": init_metrics["total_fee"],
            "gold_oz": init_metrics["gold_oz"],
            "position_value": init_metrics["position_value"],
            "created_at": time.time(),
            "max_profit": 0.0,
            "max_drawdown": 0.0,
            "is_risk_free": False,
            "is_win": False,
            "target_hit": False,
            "entered_zone_alerted": False,
            "profit_alerted_levels": [],
            "is_closed": False,
            "outcome": None,
            "outcome_reason": "",
            "realized_gross_pnl": 0.0,
            "realized_pnl_usd": 0.0,
            "realized_pnl_pct": 0.0
        }

        self.active_signals[clean_ch] = new_sig
        self._save_active_signals()
        logger.info(f"✅ سیگنال ورود #{sig_num} ({symbol}) برای کانال {channel_title} ثبت شد.")
        return sig_num, self.evaluate_signal_status(current_price, source_channel=clean_ch)

    def register_stop(self, stop_val_str: str, current_price: Optional[float], source_channel: str = "lordxau") -> Tuple[str, Optional[str]]:
        clean_ch = source_channel.lower().replace("@", "").strip()
        sig = self.active_signals.get(clean_ch)
        if not sig or sig.get("is_closed"):
            return "", None

        try:
            sl = float(stop_val_str)
        except ValueError:
            return "", None

        # اگر استاپ پیپ‌محور باشد و نماد طلا باشد
        if sl < 500 and (sig.get("symbol") in ["XAUUSD", "XAUTUSDT"] or sig.get("market_type") == "GOLD"):
            d = sig["direction"]
            entry = sig["entry_price"]
            sl = round(entry + (sl / 10.0), 2) if d == "SELL" else round(entry - (sl / 10.0), 2)

        sig["stop_loss"] = sl
        sig["is_default_sl"] = False
        self._save_active_signals()
        logger.info(f"✅ حد ضرر سیگنال #{sig['number']} کانال {sig.get('channel_title')} به عدد {sl} آپدیت شد.")

        if current_price and not sig.get("is_win") and not sig.get("target_hit"):
            d = sig["direction"]
            is_hit = (d == "BUY" and current_price <= sl) or (d == "SELL" and current_price >= sl)
            if is_hit:
                outcome_report = self.close_trade("LOSS", f"استاپ‌لاس اعلامی ({sl}) بلافاصله لمس شد.", current_price, source_channel=clean_ch)
                return f"🛑 <b>حد ضرر لمس شد:</b> <code>{sl}</code>", outcome_report

        return self.evaluate_signal_status(current_price, source_channel=clean_ch), None

    def register_risk_free(self, source_channel: str = "lordxau") -> Tuple[bool, str]:
        clean_ch = source_channel.lower().replace("@", "").strip()
        sig = self.active_signals.get(clean_ch)
        if sig and not sig.get("is_closed"):
            sig["is_risk_free"] = True
            sig["is_win"] = True
            sig["stop_loss"] = sig["entry_price"]
            self._save_active_signals()

            ch_title = sig.get("channel_title", f"@{clean_ch}")
            msg = (
                f"📢 <b>کانال:</b> {ch_title}\n"
                f"🛡 <b>معامله سیگنال #{sig['number']} ریسک‌فری شد!</b>\n\n"
                f"📌 حد ضرر (SL) دقیقاً به نقطه ورود (<code>{sig['entry_price']:.2f}</code>) منتقل شد.\n"
                f"در صورت برگشت قیمت، معامله سر‌به‌سر (فقط با کسر کارمزد صرافی) بسته می‌شود."
            )
            return True, msg
        return False, "⚠️ سیگنال فعالی برای این کانال یافت نشد."

    def register_manual_close(self, current_price: Optional[float], source_channel: str = "lordxau", reason: str = "دستور بستن توسط ادمین") -> Tuple[bool, str, Optional[str]]:
        clean_ch = source_channel.lower().replace("@", "").strip()
        sig = self.active_signals.get(clean_ch)
        if not sig or sig.get("is_closed"):
            return False, "⚠️ سیگنال بازی برای این کانال یافت نشد.", None

        exit_p = current_price or sig["entry_price"]
        direction = sig["direction"]
        entry = sig["entry_price"]

        pnl_points = (exit_p - entry) if direction == "BUY" else (entry - exit_p)
        outcome = "WIN" if pnl_points >= 0 else "LOSS"

        outcome_report = self.close_trade(
            outcome=outcome,
            reason=f"{reason} در قیمت {exit_p:.2f}",
            exit_price=exit_p,
            source_channel=clean_ch
        )
        return True, f"🔒 <b>سیگنال #{sig['number']} کانال {sig.get('channel_title')} با موفقیت بسته شد.</b>", outcome_report

    def register_break_even(self, current_price: Optional[float], source_channel: str = "lordxau") -> Optional[str]:
        clean_ch = source_channel.lower().replace("@", "").strip()
        sig = self.active_signals.get(clean_ch)
        if sig and not sig.get("is_closed"):
            max_p = sig.get("max_profit", 0.0)
            reason = f"سیگنال پس از ثبت بیشینه سود {max_p:.1f}$، در نقطه ورود بسته شد."
            return self.close_trade("BREAK_EVEN_WIN", reason, current_price, source_channel=clean_ch)
        return None

    def register_stop_hit_message(self, current_price: Optional[float], source_channel: str = "lordxau") -> Optional[str]:
        clean_ch = source_channel.lower().replace("@", "").strip()
        sig = self.active_signals.get(clean_ch)
        if sig and not sig.get("is_closed"):
            if sig.get("target_hit"):
                return self.close_trade("PARTIAL_WIN_THEN_SL", "ادمین اعلام استاپ کرد، اما تارگت سود قبلاً محقق شده بود و معامله با سود تارگت بسته شد.", current_price, source_channel=clean_ch)
            if sig.get("is_win") or sig.get("is_risk_free"):
                return self.close_trade("BREAK_EVEN_WIN", "ادمین اعلام استاپ کرد اما معامله ریسک‌فری شده بود و در نقطه ورود بسته شد.", current_price, source_channel=clean_ch)
            return self.close_trade("LOSS", "ادمین کانال اعلام کرد حد ضرر تاچ شد.", current_price, source_channel=clean_ch)
        return None

    def close_trade(self, outcome: str, reason: str, exit_price: Optional[float], source_channel: str = "lordxau") -> str:
        clean_ch = source_channel.lower().replace("@", "").strip()
        sig = self.active_signals.get(clean_ch)
        if not sig:
            return ""

        sig_settings = sig.get("settings", self.settings)
        entry = sig["entry_price"]
        exit_p = exit_price or entry
        direction = sig["direction"]

        if (sig.get("is_win") or sig.get("target_hit") or sig.get("is_risk_free")) and outcome == "LOSS":
            if sig.get("target_hit"):
                outcome = "PARTIAL_WIN_THEN_SL"
                reason = f"سیگنال ابتدا به تارگت سود رسید و در برگشت بازار استاپ خورد."
            else:
                outcome = "BREAK_EVEN_WIN"
                reason = f"سیگنال قبلاً به سود رسیده بود و در نقطه ورود سر‌به‌سر شد."

        sig["is_closed"] = True
        sig["outcome"] = outcome
        sig["outcome_reason"] = reason
        sig["exit_price"] = exit_p
        sig["closed_at"] = time.time()

        max_p = sig.get("max_profit", 0.0)
        sig_lev = sig.get("leverage")

        if outcome == "BREAK_EVEN_WIN":
            m = self.calculate_trade_metrics(entry, 0.0, sig_settings, custom_leverage=sig_lev)
            gross_pnl = 0.0
            total_fee = m["total_fee"]
            net_pnl = -total_fee
            net_pct = round((net_pnl / m["balance"] * 100.0), 1) if m["balance"] > 0 else 0.0

        elif outcome in ["WIN", "PARTIAL_WIN_THEN_SL"]:
            profit_points = max_p if max_p > 0 else abs(exit_p - entry)
            m = self.calculate_trade_metrics(entry, profit_points, sig_settings, custom_leverage=sig_lev)
            gross_pnl = m["gross_pnl"]
            total_fee = m["total_fee"]
            net_pnl = m["net_pnl"]
            net_pct = m["net_pct"]

        elif outcome == "LOSS":
            sl = sig.get("stop_loss")
            sl_dist = abs(entry - sl) if sl else (3.0 if sig.get("symbol") in ["XAUUSD", "XAUTUSDT"] else entry * 0.03)
            m = self.calculate_trade_metrics(entry, -sl_dist, sig_settings, custom_leverage=sig_lev)
            gross_pnl = m["gross_pnl"]
            total_fee = m["total_fee"]
            net_pnl = max(-m["balance"], m["net_pnl"])
            net_pct = -100.0

        else: # EXPIRED
            m = self.calculate_trade_metrics(entry, 0.0, sig_settings, custom_leverage=sig_lev)
            gross_pnl = 0.0
            total_fee = 0.0
            net_pnl = 0.0
            net_pct = 0.0

        sig["realized_gross_pnl"] = round(gross_pnl, 2)
        sig["total_fee"] = round(total_fee, 2)
        sig["realized_pnl_usd"] = round(net_pnl, 2)
        sig["realized_pnl_pct"] = round(net_pct, 1)

        saved_copy = sig.copy()
        if "profit_alerted_levels" in saved_copy and isinstance(saved_copy["profit_alerted_levels"], set):
            saved_copy["profit_alerted_levels"] = list(saved_copy["profit_alerted_levels"])
        self.trade_history.append(saved_copy)
        self._save_history()

        del self.active_signals[clean_ch]
        self._save_active_signals()

        return self._format_outcome_report(saved_copy)

    def _format_outcome_report(self, sig: Dict[str, Any]) -> str:
        sig_num = sig.get("number", 1)
        outcome = sig["outcome"]
        ch_title = sig.get("channel_title", f"@{sig.get('source_channel', 'lordxau')}")
        symbol = sig.get("symbol", "XAUTUSDT")
        sym_display = "XAUT/USDT (GOLD)" if symbol in ["XAUUSD", "XAUTUSDT"] else symbol
        
        s = sig.get("settings", self.settings)
        mode = s.get("mode", "OURBIT_FUTURES")
        balance = float(s.get("balance", 15.0))
        fee_rate = float(s.get("fee_rate", 0.04))

        gross_pnl = sig.get("realized_gross_pnl", 0.0)
        total_fee = sig.get("total_fee", 0.0)
        net_pnl = sig.get("realized_pnl_usd", 0.0)
        net_pct = sig.get("realized_pnl_pct", 0.0)

        header_banner = f"📢 <b>کانال:</b> {ch_title}\n"

        if outcome == "WIN":
            header = f"{header_banner}🏆 <b>نتیجه نهایی سیگنال #{sig_num} ({sym_display}): درست درآمد (WIN) ✅</b>"
            badge = "🟢 <b>موفق (سودده)</b>"
            pnl_details = (
                f"📈 <b>سود ناخالص:</b> <code>+{gross_pnl:.2f}$</code>\n"
                f"💸 <b>کارمزد صرافی ({fee_rate}%):</b> <code>-${total_fee:.2f}</code>\n"
                f"💰 <b>سود خالص دریافتی شما:</b> <code>+{net_pnl:.2f}$</code> (<b>+{net_pct:.0f}%</b>) 🚀"
            )
        elif outcome == "PARTIAL_WIN_THEN_SL":
            header = f"{header_banner}🏆 <b>نتیجه نهایی سیگنال #{sig_num} ({sym_display}): تارگت محقق شده (سپس استاپ) ✅</b>"
            badge = "🟡 <b>تارگت اول زده شد (Partial Win)</b>"
            pnl_details = (
                f"📈 <b>سود ناخالص تارگت:</b> <code>+{gross_pnl:.2f}$</code>\n"
                f"💸 <b>کارمزد صرافی ({fee_rate}%):</b> <code>-${total_fee:.2f}</code>\n"
                f"💰 <b>سود خالص شما:</b> <code>+{net_pnl:.2f}$</code> (<b>+{net_pct:.0f}%</b>)\n"
                f"⚠️ <i>معامله ابتدا به تارگت رسید و سود ثبت کرد، سپس با بازگشت بازار استاپ خورد.</i>"
            )
        elif outcome == "BREAK_EVEN_WIN":
            header = f"{header_banner}🏆 <b>نتیجه نهایی سیگنال #{sig_num} ({sym_display}): خروج سر‌به‌سر (Risk-Free)</b>"
            badge = "🟡 <b>ریسک‌فری (بدون سود چارت)</b>"
            pnl_details = (
                f"🟡 <b>بسته شدن در نقطه ورود:</b> سود چارت <code>$0.00</code> | کارمزد: <code>-${total_fee:.2f}</code>\n"
                f"💸 <b>تغییر خالص موجودی:</b> <code>-${total_fee:.2f}</code> (کسر کارمزد رفت‌وبرگشت)"
            )
        elif outcome == "LOSS":
            header = f"{header_banner}🚨 <b>نتیجه نهایی سیگنال #{sig_num} ({sym_display}): اشتباه درآمد (LOSS) ❌</b>"
            badge = "🔴 <b>ناموفق (استاپ خورد)</b>"
            pnl_details = (
                f"📉 <b>ضرر ناخالص استاپ:</b> <code>-${abs(gross_pnl):.2f}</code>\n"
                f"💸 <b>کارمزد صرافی ({fee_rate}%):</b> <code>-${total_fee:.2f}</code>\n"
                f"💸 <b>مجموع زیان خالص این معامله:</b> <code>-${abs(net_pnl):.2f}</code>"
            )
        else:
            header = f"{header_banner}⚪️ <b>نتیجه نهایی سیگنال #{sig_num} ({sym_display}): پایان معامله</b>"
            badge = "⚪️ <b>منقضی / نامشخص</b>"
            pnl_details = f"علت خروج: {sig.get('outcome_reason', 'پایان زمان')}"

        ourbit_line = f"🪙 <b>قرارداد Ourbit:</b> <code>GOLD(XAUT)USDT</code>\n" if symbol in ["XAUUSD", "XAUTUSDT"] else ""

        return (
            f"{header}\n\n"
            f"🔸 <b>وضعیت:</b> {badge}\n"
            f"🔹 <b>جهت:</b> {sig['direction']} | <b>نقطه ورود:</b> <code>{format_price(sig['entry_price'])}</code>\n"
            f"🔹 <b>خروج در:</b> <code>{format_price(sig.get('exit_price', sig['entry_price']))}</code>\n"
            f"{ourbit_line}\n"
            f"{pnl_details}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{self.get_stats_summary()}"
        )

    def evaluate_signal_status(self, current_price: Optional[float], source_channel: str = "lordxau") -> str:
        clean_ch = source_channel.lower().replace("@", "").strip()
        sig = self.active_signals.get(clean_ch)
        if not sig:
            return "سیگنال فعالی برای این کانال وجود ندارد."

        direction = sig["direction"]
        entry = sig["entry_price"]
        sl = sig.get("stop_loss")
        symbol = sig.get("symbol", "XAUTUSDT")
        sym_display = "XAUT/USDT (GOLD)" if symbol in ["XAUUSD", "XAUTUSDT"] else symbol
        s = sig.get("settings", self.settings)
        lev = sig.get("leverage")

        tp1_p = sig.get("tp1_price")
        if tp1_p and entry > 0:
            tp_diff = abs(tp1_p - entry)
        else:
            tp_diff = 2.0 if symbol in ["XAUUSD", "XAUTUSDT"] else (entry * 0.01)

        m_tp1 = self.calculate_trade_metrics(entry, tp_diff, s, custom_leverage=lev)
        sl_dist = abs(entry - sl) if sl else (3.0 if symbol in ["XAUUSD", "XAUTUSDT"] else entry * 0.03)
        m_sl = self.calculate_trade_metrics(entry, -sl_dist, s, custom_leverage=lev)

        status_lines = [
            f"📢 <b>کانال:</b> {sig.get('channel_title', clean_ch)}",
            f"📊 <b>نماد:</b> <code>{sym_display}</code> | <b>جهت:</b> <b>{direction}</b> | <b>نقطه ورود:</b> <code>{format_price(entry)}</code>",
        ]
        if symbol in ["XAUUSD", "XAUTUSDT"]:
            status_lines.append("🪙 <b>قرارداد Ourbit:</b> <code>GOLD(XAUT)USDT</code>")
        status_lines.extend([
            f"🛑 <b>حد ضرر:</b> <code>{format_price(sl)}</code>" if sl else "🛑 <b>حد ضرر:</b> مشخص نشده",
            f"💰 <b>پیش‌بینی سود و زیان (اهرم {lev or 100}x):</b>",
            f"• تارگت اول: خالص <b><code>+{m_tp1['net_pnl']:.2f}$</code></b> (+{m_tp1['net_pct']:.0f}%)",
            f"• در صورت استاپ: خالص با کارمزد <b><code>-${abs(m_sl['net_pnl']):.2f}</code></b>"
        ])
        return "\n".join(status_lines)

    # ════════════════════ بررسی زنده وضعیت برای همه کانال‌ها ════════════════════

    def check_live_status_change(self, get_price_func_or_price: Any) -> List[str]:
        alerts = []
        if not self.active_signals:
            self.active_signals = self._load_active_signals()

        for ch, sig in list(self.active_signals.items()):
            if not sig or sig.get("is_closed"):
                continue

            symbol = sig.get("symbol", "XAUTUSDT")
            if callable(get_price_func_or_price):
                cur_price = get_price_func_or_price(symbol)
            elif isinstance(get_price_func_or_price, (int, float)):
                cur_price = float(get_price_func_or_price)
            else:
                continue

            if not cur_price:
                continue

            alert = self._check_single_trade_live(sig, cur_price, source_channel=ch)
            if alert:
                alerts.append(alert)

        return alerts

    def _check_single_trade_live(self, sig: Dict[str, Any], current_price: float, source_channel: str) -> Optional[str]:
        sig_num = sig.get("number", 1)
        direction = sig["direction"]
        e_min = sig["entry_min"]
        e_max = sig["entry_max"]
        entry = sig["entry_price"]
        sl = sig.get("stop_loss")
        symbol = sig.get("symbol", "XAUTUSDT")
        sym_display = "XAUT/USDT (GOLD)" if symbol in ["XAUUSD", "XAUTUSDT"] else symbol
        ch_title = sig.get("channel_title", f"@{source_channel}")
        s = sig.get("settings", self.settings)
        lev = sig.get("leverage")

        if direction == "BUY":
            cur_profit = current_price - entry
            drawdown = entry - current_price
        else:
            cur_profit = entry - current_price
            drawdown = current_price - entry

        if cur_profit > sig["max_profit"]:
            sig["max_profit"] = cur_profit
        if drawdown > sig["max_drawdown"]:
            sig["max_drawdown"] = drawdown

        # ۱. رسیدن به تارگت سود
        tp1 = sig.get("tp1_price")
        if tp1:
            is_tp_hit = (direction == "BUY" and current_price >= tp1) or (direction == "SELL" and current_price <= tp1)
        else:
            threshold = 2.0 if symbol in ["XAUUSD", "XAUTUSDT"] else (entry * 0.01)
            is_tp_hit = (cur_profit >= threshold)

        if is_tp_hit and not sig.get("target_hit"):
            sig["target_hit"] = True
            sig["is_win"] = True
            self._save_active_signals()

            m_cur = self.calculate_trade_metrics(entry, cur_profit, s, custom_leverage=lev)
            net_sign = "+" if m_cur["net_pnl"] >= 0 else ""

            return (
                f"📢 <b>کانال:</b> {ch_title}\n"
                f"🎯 <b>تارگت اول سیگنال #{sig_num} ({sym_display}) محقق شد!</b>\n\n"
                f"قیمت لحظه‌ای: <code>{format_price(current_price)}</code>\n"
                f"📈 <b>سود ناخالص:</b> <code>+{m_cur['gross_pnl']:.2f}$</code> | 💸 <b>کارمزد صرافی:</b> <code>-${m_cur['total_fee']:.2f}</code>\n"
                f"💰 <b>سود خالص دریافتی شما:</b> <code>{net_sign}${m_cur['net_pnl']:.2f}</code> (<b>+{m_cur['net_pct']:.0f}%</b>) 🚀\n\n"
                f"✅ تارگت اول محقق شد و معامله به عنوان برد (WIN) ثبت گردید."
            )

        # ۲. بازگشت به نقطه ورود پس از ریسک‌فری
        if sig.get("is_risk_free"):
            is_returned = (direction == "BUY" and current_price <= entry) or (direction == "SELL" and current_price >= entry)
            if is_returned:
                return self.close_trade("BREAK_EVEN_WIN", "سیگنال پس از ریسک‌فری، در نقطه ورود بسته شد.", current_price, source_channel=source_channel)

        # ۳. لمس حد ضرر
        if sl:
            is_stopped = (direction == "BUY" and current_price <= sl) or (direction == "SELL" and current_price >= sl)
            if is_stopped:
                if sig.get("target_hit"):
                    return self.close_trade("PARTIAL_WIN_THEN_SL", f"تارگت قبلاً محقق شده بود و در بازگشت استاپ ({format_price(sl)}) لمس شد.", current_price, source_channel=source_channel)
                elif sig.get("is_risk_free") or sig.get("is_win"):
                    return self.close_trade("BREAK_EVEN_WIN", f"حد ضرر ریسک‌فری ({format_price(sl)}) لمس شد.", current_price, source_channel=source_channel)
                else:
                    return self.close_trade("LOSS", f"قیمت به {format_price(current_price)} رسید و حد ضرر ({format_price(sl)}) لمس شد.", current_price, source_channel=source_channel)

        # ۴. ورود به محدوده (تنها برای طلا که زون دارد)
        if symbol in ["XAUUSD", "XAUTUSDT"] and not sig["entered_zone_alerted"] and (e_min <= current_price <= e_max):
            sig["entered_zone_alerted"] = True
            self._save_active_signals()
            return (
                f"📢 <b>کانال:</b> {ch_title}\n"
                f"🎯 <b>سیگنال #{sig_num} ({sym_display}): وارد زون ورود شد!</b>\n\n"
                f"جهت: <b>{direction}</b> | قیمت: <code>{format_price(current_price)}</code>\n"
                f"محدوده ورود: <code>{sig['entry_raw']}</code>"
            )

        # ۵. منقضی شدن بعد از ۲ ساعت
        if time.time() - sig["created_at"] > 7200:
            if sig.get("is_win"):
                return self.close_trade("WIN", f"سیگنال پس از ثبت سود به پایان رسید.", current_price, source_channel=source_channel)
            else:
                return self.close_trade("EXPIRED", "سیگنال پس از زمان مجاز منقضی شد.", current_price, source_channel=source_channel)

        return None

    # ════════════════════ تفکیک کارنامه و آمار کل ════════════════════

    def get_stats_summary(self, channel_filter: Optional[str] = None) -> str:
        trades = self.trade_history
        if channel_filter:
            clean_f = channel_filter.lower().replace("@", "").strip()
            trades = [t for t in trades if t.get("source_channel", "").lower() == clean_f]

        if not trades:
            return "هنوز هیچ معامله ثبت‌شده‌ای در تاریخچه وجود ندارد."

        total = len(trades)
        wins = sum(1 for t in trades if t.get("outcome") in ["WIN", "PARTIAL_WIN_THEN_SL"])
        losses = sum(1 for t in trades if t.get("outcome") == "LOSS")
        be = sum(1 for t in trades if t.get("outcome") == "BREAK_EVEN_WIN")
        rate = (wins / total * 100) if total > 0 else 0
        total_gross = sum(t.get("realized_gross_pnl", 0.0) for t in trades)
        total_fees = sum(t.get("total_fee", 0.0) for t in trades)
        total_net = sum(t.get("realized_pnl_usd", 0.0) for t in trades)

        lines = [
            f"📊 <b>کارنامه و عملکرد کل ربات:</b>",
            f"• کل معاملات: <b>{total}</b> | برد: <b>{wins} ✅</b> | باخت: <b>{losses} ❌</b> | ریسک‌فری: <b>{be}</b>",
            f"• نرخ موفقیت کلی (Win Rate): <b>{rate:.0f}%</b>",
            f"• سود ناخالص چارت: <code>{'+' if total_gross>=0 else ''}{total_gross:.2f}$</code>",
            f"• کل کارمزد کسرشده صرافی: <code>-${total_fees:.2f}</code>",
            f"• 💰 <b>سود/زیان خالص نهایی شما:</b> <code>{'+' if total_net>=0 else ''}{total_net:.2f}$</code> 🚀\n",
            "━━━━━━━━━━━━━━━━━━━━\n<b>تفکیک عملکرد به ازای هر کانال:</b>"
        ]

        # تفکیک بر اساس کانال‌ها
        channel_names = set(t.get("source_channel", "lordxau") for t in trades)
        for ch in sorted(channel_names):
            ch_trades = [t for t in trades if t.get("source_channel", "lordxau") == ch]
            ch_total = len(ch_trades)
            ch_wins = sum(1 for t in ch_trades if t.get("outcome") in ["WIN", "PARTIAL_WIN_THEN_SL"])
            ch_losses = sum(1 for t in ch_trades if t.get("outcome") == "LOSS")
            ch_rate = (ch_wins / ch_total * 100) if ch_total > 0 else 0
            ch_net = sum(t.get("realized_pnl_usd", 0.0) for t in ch_trades)
            ch_title = ch_trades[0].get("channel_title", f"@{ch}")

            lines.append(
                f"\n📢 <b>{ch_title}:</b>\n"
                f"• معاملات: <b>{ch_total}</b> (برد: <b>{ch_wins} ✅</b> | باخت: <b>{ch_losses} ❌</b>)\n"
                f"• نرخ برد: <b>{ch_rate:.0f}%</b> | سود خالص: <code>{'+' if ch_net>=0 else ''}{ch_net:.2f}$</code>"
            )

        return "\n".join(lines)

    def get_daily_summary(self) -> str:
        return self.get_stats_summary()

    def mark_user_participation(self, signal_number: int, entered: bool) -> str:
        for sig in self.active_signals.values():
            if sig.get("number") == signal_number:
                sig["user_entered"] = entered
                self._save_active_signals()
                return f"✅ معامله #{signal_number} ثبت شد."
        return "⚠️ معامله یافت نشد."

evaluator = SignalEvaluator()
