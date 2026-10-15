import logging
import time
import json
import os
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("Evaluator")

DEFAULT_SETTINGS = {
    "balance": 15.0,              # سرمایه اولیه دلاری
    "mode": "OURBIT_FUTURES",     # OURBIT_FUTURES یا FOREX_MT5
    "leverage": 100,              # ضریب اهرم فیوچرز
    "lot_size": 0.01,             # حجم معامله فارکس به لات
    "fee_rate": 0.04,             # درصد کارمزد صرافی در هر طرف معامله (Ourbit Taker: 0.04%)
    "order_type": "MARKET"        # نوع سفارش: MARKET (0.04%) یا LIMIT (0.02%)
}

class SignalEvaluator:
    def __init__(
        self, 
        history_file: str = "trade_history.json", 
        active_file: str = "active_signal.json", 
        settings_file: str = "settings.json",
        default_budget: float = 15.0
    ):
        self.history_file = history_file
        self.active_file = active_file
        self.settings_file = settings_file
        
        self.settings: Dict[str, Any] = self._load_settings()
        if default_budget != 15.0 and "balance" not in self.settings:
            self.settings["balance"] = default_budget
            
        self.trade_history: List[Dict[str, Any]] = self._load_history()
        self.active_signal: Optional[Dict[str, Any]] = self._load_active_signal()
        self.signal_counter: int = self._determine_counter()

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
        if self.active_signal and not self.active_signal.get("is_closed"):
            self.active_signal["settings"]["balance"] = self.settings["balance"]
            self._save_active_signal()
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
            return "❌ حالت نامعتبر است. انتخاب‌ها: <code>OURBIT_FUTURES</code> یا <code>FOREX_MT5</code>"
        
        self._save_settings()
        return f"🔄 پلتفرم معاملاتی به <b>{label}</b> تغییر یافت."

    def set_leverage(self, leverage: int) -> str:
        if leverage < 1 or leverage > 1000:
            return "❌ اهرم باید بین 1 تا 1000 باشد."
        self.settings["leverage"] = int(leverage)
        self._save_settings()
        return f"⚡️ اهرم فیوچرز به <b>{self.settings['leverage']}x</b> تغییر یافت."

    def set_lot_size(self, lot_size: float) -> str:
        if lot_size <= 0 or lot_size > 50.0:
            return "❌ حجم لات باید بین 0.01 تا 50.0 باشد."
        self.settings["lot_size"] = round(lot_size, 3)
        self._save_settings()
        return f"📊 حجم لات فارکس به <b>{self.settings['lot_size']} Lot</b> تنظیم شد."

    def set_fee_rate(self, fee_rate: float, order_type: Optional[str] = None) -> str:
        if fee_rate < 0 or fee_rate > 5.0:
            return "❌ درصد کارمزد باید بین 0 تا 5 درصد باشد."
        self.settings["fee_rate"] = round(fee_rate, 4)
        if order_type:
            self.settings["order_type"] = order_type.upper()
        self._save_settings()
        return f"💸 نرخ کارمزد صرافی به <b>{self.settings['fee_rate']}%</b> تنظیم شد."

    def set_order_type(self, order_type: str) -> str:
        ot = order_type.upper().strip()
        if ot in ["MARKET", "TAKER", "مارکت"]:
            self.settings["order_type"] = "MARKET"
            self.settings["fee_rate"] = 0.04
            msg = "⚡️ نوع سفارش به <b>MARKET (Taker)</b> تغییر یافت (کارمزد: <b>0.04%</b>)"
        elif ot in ["LIMIT", "MAKER", "لیمیت"]:
            self.settings["order_type"] = "LIMIT"
            self.settings["fee_rate"] = 0.02
            msg = "🎯 نوع سفارش به <b>LIMIT (Maker)</b> تغییر یافت (کارمزد: <b>0.02%</b>)"
        elif ot in ["ZERO", "NO_FEE", "صفر"]:
            self.settings["order_type"] = "NO_FEE"
            self.settings["fee_rate"] = 0.0
            msg = "🆓 حالت <b>بدون کارمزد (0%)</b> فعال شد."
        else:
            return "❌ نوع سفارش نامعتبر است. (MARKET یا LIMIT)"
        self._save_settings()
        return msg

    def get_settings_summary_text(self) -> str:
        s = self.settings
        mode = s.get("mode", "OURBIT_FUTURES")
        balance = float(s.get("balance", 15.0))
        lev = int(s.get("leverage", 100))
        pos_val = balance * lev
        lot = float(s.get("lot_size", 0.01))
        fee = float(s.get("fee_rate", 0.04))
        ot = s.get("order_type", "MARKET")
        round_trip_fee = pos_val * (fee / 100.0) * 2.0

        if mode == "OURBIT_FUTURES":
            mode_badge = "🟢 صرافی Ourbit (فیوچرز)"
            primary_info = (
                f"💰 <b>سرمایه مارجین:</b> <code>${balance:.2f}</code>\n"
                f"⚡️ <b>اهرم معاملاتی:</b> <code>{lev}x</code>\n"
                f"📐 <b>ارزش کل پوزیشن:</b> <code>${pos_val:,.2f}</code>\n"
                f"💸 <b>کارمزد رفت‌وبرگشت ({fee}% {ot}):</b> <code>${round_trip_fee:.2f}</code>"
            )
        else:
            mode_badge = "🔵 Forex MT5 (متاتریدر)"
            primary_info = (
                f"📊 <b>حجم معامله:</b> <code>{lot} Lot</code> ({lot*100:.1f} انس طلا)\n"
                f"💰 <b>سرمایه مبنا:</b> <code>${balance:.2f}</code>\n"
                f"💸 <b>کارمزد/کمیسیون:</b> <code>{fee}%</code>"
            )

        return (
            f"⚙️ <b>کنترل پنل تنظیمات سرمایه و کارمزد</b>\n\n"
            f"📊 <b>پلتفرم فعال:</b> {mode_badge}\n"
            f"{primary_info}\n\n"
            f"<i>برای اعمال تغییرات، از دکمه‌های زیر استفاده کنید:</i>"
        )

    # ════════════════════ فرمول‌های محاسبه دقیق مالی ════════════════════

    def calculate_trade_metrics(self, entry_price: float, price_diff: float, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        محاسبه دقیق متریک‌های مالی شامل:
        - ارزش کل پوزیشن (position_value)
        - حجم معادل طلا به انس (gold_oz)
        - کارمزد رفت‌وبرگشت (total_fee)
        - سود/ضرر ناخالص (gross_pnl)
        - سود/ضرر خالص (net_pnl)
        - فاصله و قیمت لیکوئیدی (liq_distance_dollars, liq_price)
        """
        s = settings or self.settings
        mode = s.get("mode", "OURBIT_FUTURES")
        fee_rate = float(s.get("fee_rate", 0.04))

        if mode == "OURBIT_FUTURES":
            balance = float(s.get("balance", 15.0))
            leverage = int(s.get("leverage", 100))
            position_value = balance * leverage
            gold_oz = position_value / entry_price if entry_price > 0 else 0.0
            
            # کارمزد رفت و برگشت: باز کردن + بستن پوزیشن
            total_fee = position_value * (fee_rate / 100.0) * 2.0
            
            # سود ناخالص و خالص
            gross_pnl = price_diff * gold_oz
            net_pnl = gross_pnl - total_fee
            net_pct = (net_pnl / balance * 100.0) if balance > 0 else 0.0

            # فاصله تا لیکوئید شدن (با حفظ 0.5% مارجین نگهداری - Maintenance Margin)
            maint_margin = position_value * 0.005
            usable_balance = balance - total_fee - maint_margin
            liq_distance_dollars = (usable_balance / gold_oz) if gold_oz > 0 else 0.0

            return {
                "mode": mode,
                "balance": balance,
                "leverage": leverage,
                "position_value": position_value,
                "gold_oz": gold_oz,
                "fee_rate": fee_rate,
                "total_fee": round(total_fee, 2),
                "gross_pnl": round(gross_pnl, 2),
                "net_pnl": round(net_pnl, 2),
                "net_pct": round(net_pct, 1),
                "liq_distance_dollars": max(0.0, round(liq_distance_dollars, 2)),
                "used_margin": balance
            }
        else: # FOREX_MT5
            lot_size = float(s.get("lot_size", 0.01))
            gold_oz = lot_size * 100.0  # هر 0.01 لات = 1 انس طلا
            position_value = entry_price * gold_oz
            used_margin = (entry_price * gold_oz) / 1000.0 if entry_price > 0 else 0.0
            total_fee = (position_value * (fee_rate / 100.0) * 2.0) if fee_rate > 0 else 0.0
            gross_pnl = price_diff * gold_oz
            net_pnl = gross_pnl - total_fee
            net_pct = (net_pnl / used_margin * 100.0) if used_margin > 0 else 0.0

            return {
                "mode": mode,
                "lot_size": lot_size,
                "gold_oz": gold_oz,
                "position_value": position_value,
                "used_margin": round(used_margin, 2),
                "fee_rate": fee_rate,
                "total_fee": round(total_fee, 2),
                "gross_pnl": round(gross_pnl, 2),
                "net_pnl": round(net_pnl, 2),
                "net_pct": round(net_pct, 1),
                "liq_distance_dollars": 0.0,
                "balance": float(s.get("balance", 15.0))
            }

    # ════════════════════ دیتابیس سیگنال‌ها و تاریخچه ════════════════════

    def _determine_counter(self) -> int:
        max_num = 0
        for t in self.trade_history:
            num = t.get("number", 0)
            if num > max_num:
                max_num = num
        if self.active_signal:
            num = self.active_signal.get("number", 0)
            if num > max_num:
                max_num = num
        return max_num

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

    def _load_active_signal(self) -> Optional[Dict[str, Any]]:
        if os.path.exists(self.active_file):
            try:
                with open(self.active_file, "r", encoding="utf-8") as f:
                    sig = json.load(f)
                    if sig and not sig.get("is_closed"):
                        if time.time() - sig.get("created_at", 0) < 10800:
                            logger.info(f"♻️ سیگنال فعال #{sig.get('number')} از دیتابیس بازیابی شد.")
                            return sig
            except Exception as e:
                logger.error(f"خطا در بازیابی سیگنال فعال: {e}")
        return None

    def _save_active_signal(self):
        try:
            if self.active_signal and not self.active_signal.get("is_closed"):
                saved_copy = self.active_signal.copy()
                if "profit_alerted_levels" in saved_copy and isinstance(saved_copy["profit_alerted_levels"], set):
                    saved_copy["profit_alerted_levels"] = list(saved_copy["profit_alerted_levels"])
                with open(self.active_file, "w", encoding="utf-8") as f:
                    json.dump(saved_copy, f, ensure_ascii=False, indent=2)
            else:
                if os.path.exists(self.active_file):
                    os.remove(self.active_file)
        except Exception as e:
            logger.error(f"خطا در ذخیره سیگنال فعال: {e}")

    def has_active_trade(self) -> bool:
        """بررسی وجود سیگنال باز و فعال در سیستم"""
        if not self.active_signal:
            self.active_signal = self._load_active_signal()
        return bool(self.active_signal and not self.active_signal.get("is_closed"))

    # ════════════════════ ثبت و مانیتورینگ سیگنال ════════════════════

    def register_entry(self, direction: str, entry_raw: str, current_price: Optional[float]) -> Tuple[int, str]:
        if self.active_signal and not self.active_signal.get("is_closed"):
            self.close_trade(
                outcome="EXPIRED",
                reason="سیگنال جدید صادر شد و معامله قبلی جایگزین گردید.",
                exit_price=current_price
            )

        self.signal_counter += 1
        sig_num = self.signal_counter

        entry_min, entry_max = self._parse_entry_range(entry_raw, current_price)
        mid_entry = (entry_min + entry_max) / 2 if (entry_min and entry_max) else (current_price or 0.0)
        dir_clean = "BUY" if ("buy" in direction.lower() or "بای" in direction.lower()) else "SELL"

        default_sl = round(mid_entry - 3.0, 2) if dir_clean == "BUY" else round(mid_entry + 3.0, 2)

        # اسنپ‌شات تنظیمات فعلی معامله
        sig_settings = self.settings.copy()
        init_metrics = self.calculate_trade_metrics(mid_entry, 0.0, sig_settings)

        self.active_signal = {
            "id": int(time.time()),
            "number": sig_num,
            "direction": dir_clean,
            "entry_min": entry_min,
            "entry_max": entry_max,
            "entry_price": mid_entry,
            "entry_raw": entry_raw,
            "stop_loss": default_sl,
            "is_default_sl": True,
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

        self._save_active_signal()
        logger.info(f"✅ سیگنال ورود #{sig_num} با استاپ موقت {default_sl} ثبت شد.")
        return sig_num, self.evaluate_signal_status(current_price)

    def register_stop(self, stop_val_str: str, current_price: Optional[float]) -> Tuple[str, Optional[str]]:
        try:
            sl = float(stop_val_str)
        except ValueError:
            return "", None

        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if self.active_signal and not self.active_signal.get("is_closed"):
            # اگر استاپ بر حسب پیپ باشد (زیر ۵۰۰ مانند 90 پیپ)، به قیمت طلا تبدیلش کن
            if sl < 500:
                d = self.active_signal["direction"]
                entry = self.active_signal["entry_price"]
                sl_dollars = sl / 10.0
                sl = round(entry + sl_dollars, 2) if d == "SELL" else round(entry - sl_dollars, 2)

            self.active_signal["stop_loss"] = sl
            self.active_signal["is_default_sl"] = False
            self._save_active_signal()
            logger.info(f"✅ حد ضرر سیگنال #{self.active_signal['number']} به عدد {sl} آپدیت شد.")

            if current_price and not self.active_signal.get("is_win") and not self.active_signal.get("target_hit"):
                d = self.active_signal["direction"]
                is_hit = (d == "BUY" and current_price <= sl) or (d == "SELL" and current_price >= sl)
                if is_hit:
                    outcome_report = self.close_trade("LOSS", f"استاپ‌لاس اعلامی ({sl}) بلافاصله در قیمت {current_price:.2f} لمس شد.", current_price)
                    return f"🛑 <b>حد ضرر لمس شد:</b> <code>{sl}</code>", outcome_report

            return self.evaluate_signal_status(current_price), None
        else:
            logger.warning("پیام Stop دریافت شد اما سیگنال بازی یافت نشد.")
            return f"🛑 <b>حد ضرر اعلامی:</b> <code>{sl}</code> (سیگنال بازی برای اتصال یافت نشد)", None

    def register_risk_free(self) -> Tuple[bool, str]:
        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if self.active_signal and not self.active_signal.get("is_closed"):
            sig = self.active_signal
            sig["is_risk_free"] = True
            sig["is_win"] = True
            sig["stop_loss"] = sig["entry_price"]
            self._save_active_signal()

            msg = (
                f"🛡 <b>معامله سیگنال #{sig['number']} ریسک‌فری شد!</b>\n\n"
                f"📌 حد ضرر (SL) دقیقاً به نقطه ورود (<code>{sig['entry_price']:.2f}</code>) منتقل شد.\n"
                f"در صورت برگشت قیمت، معامله سر‌به‌سر (فقط با کسر کارمزد صرافی) بسته می‌شود."
            )
            return True, msg
        return False, "⚠️ سیگنال فعالی برای ریسک‌فری یافت نشد."

    def register_manual_close(self, current_price: Optional[float], reason: str = "دستور بستن (ببند / فول کلوز) توسط ادمین") -> Tuple[bool, str, Optional[str]]:
        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if not self.active_signal or self.active_signal.get("is_closed"):
            return False, "⚠️ سیگنال بازی برای بستن یافت نشد.", None

        sig = self.active_signal
        exit_p = current_price or sig["entry_price"]
        direction = sig["direction"]
        entry = sig["entry_price"]

        pnl_points = (exit_p - entry) if direction == "BUY" else (entry - exit_p)
        pips = int(pnl_points * 10)
        outcome = "WIN" if pnl_points >= 0 else "LOSS"

        outcome_report = self.close_trade(
            outcome=outcome,
            reason=f"{reason} در قیمت {exit_p:.2f} ({'+' if pnl_points>=0 else ''}{pnl_points:.2f}$ / {pips} پیپ)",
            exit_price=exit_p
        )
        return True, f"🔒 <b>سیگنال #{sig['number']} با موفقیت بسته شد.</b>", outcome_report

    def register_break_even(self, current_price: Optional[float]) -> Optional[str]:
        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if self.active_signal and not self.active_signal.get("is_closed"):
            max_p = self.active_signal.get("max_profit", 0.0)
            reason = f"سیگنال پس از ثبت بیشینه سود {max_p:.1f}$ (+{int(max_p*10)} پیپ)، در نقطه ورود بسته شد."
            return self.close_trade("BREAK_EVEN_WIN", reason, current_price)
        return None

    def register_stop_hit_message(self, current_price: Optional[float]) -> Optional[str]:
        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if self.active_signal and not self.active_signal.get("is_closed"):
            if self.active_signal.get("target_hit"):
                return self.close_trade("PARTIAL_WIN_THEN_SL", "ادمین اعلام استاپ کرد، اما تارگت سود قبلاً محقق شده بود و معامله با سود تارگت بسته شد.", current_price)
            if self.active_signal.get("is_win") or self.active_signal.get("is_risk_free"):
                return self.close_trade("BREAK_EVEN_WIN", "ادمین اعلام استاپ کرد اما معامله ریسک‌فری شده بود و معامله در نقطه ورود بسته شد.", current_price)
            return self.close_trade("LOSS", "ادمین کانال اعلام کرد حد ضرر (استاپ) تاچ شد.", current_price)
        return None

    def close_trade(self, outcome: str, reason: str, exit_price: Optional[float]) -> str:
        if not self.active_signal:
            return ""

        sig = self.active_signal
        sig_settings = sig.get("settings", self.settings)
        entry = sig["entry_price"]
        exit_p = exit_price or entry
        direction = sig["direction"]

        # محافظت بحرانی: اگر به تارگت رسیده باشد نباید باخت شود
        if (sig.get("is_win") or sig.get("target_hit") or sig.get("is_risk_free")) and outcome == "LOSS":
            if sig.get("target_hit"):
                outcome = "PARTIAL_WIN_THEN_SL"
                reason = f"سیگنال ابتدا به تارگت سود (+{sig.get('max_profit', 0.0):.1f}$ / +{int(sig.get('max_profit', 0.0)*10)} پیپ) رسید و در برگشت استاپ خورد."
            else:
                outcome = "BREAK_EVEN_WIN"
                reason = f"سیگنال قبلاً به سود +{sig.get('max_profit', 0.0):.1f}$ (+{int(sig.get('max_profit', 0.0)*10)} پیپ) رسیده بود و در نقطه ورود سر‌به‌سر شد."

        sig["is_closed"] = True
        sig["outcome"] = outcome
        sig["outcome_reason"] = reason
        sig["exit_price"] = exit_p
        sig["closed_at"] = time.time()

        # محاسبه سود و زیان دقیق بر اساس پلتفرم و کارمزد
        max_p = sig.get("max_profit", 0.0)

        if outcome == "BREAK_EVEN_WIN":
            # در ریسک‌فری: سود چارت 0.0 است ولی کارمزد صرافی کسر می‌شود!
            m = self.calculate_trade_metrics(entry, 0.0, sig_settings)
            gross_pnl = 0.0
            total_fee = m["total_fee"]
            net_pnl = -total_fee
            net_pct = round((net_pnl / m["balance"] * 100.0), 1) if m["balance"] > 0 else 0.0

        elif outcome in ["WIN", "PARTIAL_WIN_THEN_SL"]:
            # سود بر اساس بیشینه حرکت به سمت تارگت
            profit_points = max_p if max_p > 0 else abs(exit_p - entry)
            m = self.calculate_trade_metrics(entry, profit_points, sig_settings)
            gross_pnl = m["gross_pnl"]
            total_fee = m["total_fee"]
            net_pnl = m["net_pnl"]
            net_pct = m["net_pct"]

        elif outcome == "LOSS":
            sl = sig.get("stop_loss")
            sl_dist = abs(entry - sl) if sl else 3.0
            m = self.calculate_trade_metrics(entry, -sl_dist, sig_settings)
            gross_pnl = m["gross_pnl"]
            total_fee = m["total_fee"]
            # در باخت، اگر کل مارجین از دست برود:
            net_pnl = max(-m["balance"], m["net_pnl"])
            net_pct = -100.0

        else: # EXPIRED
            m = self.calculate_trade_metrics(entry, 0.0, sig_settings)
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

        self.active_signal = None
        if os.path.exists(self.active_file):
            try:
                os.remove(self.active_file)
            except Exception:
                pass

        return self._format_outcome_report(saved_copy)

    def _format_outcome_report(self, sig: Dict[str, Any]) -> str:
        sig_num = sig.get("number", 1)
        outcome = sig["outcome"]
        direction = sig["direction"]
        entry = sig["entry_price"]
        exit_p = sig.get("exit_price", entry)
        max_p = sig.get("max_profit", 0.0)
        pips = int(max_p * 10)
        
        s = sig.get("settings", self.settings)
        mode = s.get("mode", "OURBIT_FUTURES")
        balance = float(s.get("balance", 15.0))
        lev = int(s.get("leverage", 100))
        pos_val = balance * lev
        fee_rate = float(s.get("fee_rate", 0.04))

        gross_pnl = sig.get("realized_gross_pnl", 0.0)
        total_fee = sig.get("total_fee", 0.0)
        net_pnl = sig.get("realized_pnl_usd", 0.0)
        net_pct = sig.get("realized_pnl_pct", 0.0)

        stats = self.get_stats_summary()

        # تنظیم سربرگ و اطلاعات پلتفرم
        if mode == "OURBIT_FUTURES":
            platform_bar = f"⚙️ <b>حالت:</b> Ourbit | <b>سرمایه:</b> ${balance:.2f} | <b>اهرم:</b> {lev}x (ارزش پوزیشن: ${pos_val:,.0f})"
        else:
            lot = s.get("lot_size", 0.01)
            platform_bar = f"⚙️ <b>حالت:</b> Forex MT5 | <b>حجم:</b> {lot} Lot ({lot*100:.1f} انس)"

        gross_symbol = "+" if gross_pnl >= 0 else ""
        net_symbol = "+" if net_pnl >= 0 else ""

        if outcome == "WIN":
            header = f"🏆 <b>نتیجه نهایی سیگنال #{sig_num}: درست درآمد (WIN) ✅</b>"
            badge = "🟢 <b>موفق (سودده)</b>"
            pnl_details = (
                f"📈 <b>سود ناخالص چارت:</b> <code>+{gross_pnl:.2f}$</code>\n"
                f"💸 <b>کارمزد صرافی ({fee_rate}%):</b> <code>-${total_fee:.2f}</code>\n"
                f"💰 <b>سود خالص دریافتی شما:</b> <code>+{net_pnl:.2f}$</code> (<b>+{net_pct:.0f}%</b>) 🚀"
            )
        elif outcome == "PARTIAL_WIN_THEN_SL":
            header = f"🏆 <b>نتیجه نهایی سیگنال #{sig_num}: تارگت محقق شده (سپس استاپ) ✅</b>"
            badge = "🟡 <b>تارگت اول زده شد (Partial Win)</b>"
            pnl_details = (
                f"📈 <b>سود ناخالص تارگت:</b> <code>+{gross_pnl:.2f}$</code>\n"
                f"💸 <b>کارمزد صرافی ({fee_rate}%):</b> <code>-${total_fee:.2f}</code>\n"
                f"💰 <b>سود خالص شما:</b> <code>+{net_pnl:.2f}$</code> (<b>+{net_pct:.0f}%</b>)\n"
                f"⚠️ <i>معامله ابتدا به تارگت رسید و سود خود را ثبت کرد، سپس با بازگشت بازار استاپ خورد.</i>"
            )
        elif outcome == "BREAK_EVEN_WIN":
            header = f"🏆 <b>نتیجه نهایی سیگنال #{sig_num}: خروج در نقطه ورود (Risk-Free)</b>"
            badge = "🟡 <b>ریسک‌فری (خروج بدون سود چارت)</b>"
            pnl_details = (
                f"🟡 <b>بسته شدن در نقطه ورود (فری):</b> سود چارت <code>$0.00</code> | کسر کارمزد صرافی: <code>-${total_fee:.2f}</code> (<b>ضرر خالص: <code>-${total_fee:.2f}</code></b>)\n"
                f"💸 <b>تغییر خالص موجودی شما:</b> <code>-${total_fee:.2f}</code> (کسر کارمزد رفت‌وبرگشت پوزیشن)"
            )
        elif outcome == "LOSS":
            header = f"🚨 <b>نتیجه نهایی سیگنال #{sig_num}: اشتباه درآمد (LOSS) ❌</b>"
            badge = "🔴 <b>ناموفق (استاپ خورد)</b>"
            pnl_details = (
                f"📉 <b>ضرر ناخالص استاپ:</b> <code>{gross_symbol}${gross_pnl:.2f}</code>\n"
                f"💸 <b>کارمزد صرافی ({fee_rate}%):</b> <code>-${total_fee:.2f}</code>\n"
                f"💸 <b>مجموع زیان خالص این معامله:</b> <code>-${abs(net_pnl):.2f}</code>"
            )
        else:
            header = f"⚪️ <b>نتیجه نهایی سیگنال #{sig_num}: پایان معامله</b>"
            badge = "⚪️ <b>بدون سود و ضرر</b>"
            pnl_details = f"💵 <b>تغییر موجودی شما:</b> <code>$0.00</code>"

        report = (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{platform_bar}\n"
            f"🔸 <b>شماره سیگنال:</b> #{sig_num}\n"
            f"🔸 <b>نماد:</b> XAUUSD (طلا)\n"
            f"🔸 <b>نوع سیگنال:</b> {direction}\n"
            f"🔸 <b>نقطه ورود:</b> <code>{sig['entry_raw']}</code> (~{entry:.2f})\n"
            f"🔸 <b>خروج در:</b> <code>{exit_p:.2f}</code>\n"
            f"🔸 <b>بیشترین حرکت طلا:</b> <code>+{max_p:.1f}$</code> (+{pips} پیپ)\n"
            f"🔸 <b>وضعیت:</b> {badge}\n\n"
            f"{pnl_details}\n\n"
            f"📝 <b>دلیل و شرح:</b>\n<i>{sig['outcome_reason']}</i>\n\n"
            f"📊 <b>کارنامه کل سیگنال‌ها:</b>\n{stats}"
        )
        return report

    def get_stats_summary(self) -> str:
        if not self.trade_history:
            return f"<i>هنوز سابقه‌ای ثبت نشده است. (سرمایه مبنا: ${self.trade_budget:.2f})</i>"

        wins = sum(1 for t in self.trade_history if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN", "PARTIAL_WIN_THEN_SL"])
        losses = sum(1 for t in self.trade_history if t.get("outcome") == "LOSS")
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0

        total_gross = sum(t.get("realized_gross_pnl", 0.0) for t in self.trade_history)
        total_fees = sum(t.get("total_fee", 0.0) for t in self.trade_history)
        total_net = sum(t.get("realized_pnl_usd", 0.0) for t in self.trade_history)

        gross_symbol = "+" if total_gross >= 0 else ""
        net_symbol = "+" if total_net >= 0 else ""

        return (
            f"• کل سیگنال‌ها: <b>{len(self.trade_history)}</b> (برد: <b>{wins} ✅</b> | باخت: <b>{losses} ❌</b>)\n"
            f"• نرخ موفقیت (Win Rate): <b>{win_rate:.0f}%</b>\n"
            f"• 📈 <b>جمع سود/زیان ناخالص معاملات:</b> <code>{gross_symbol}${total_gross:.2f}</code>\n"
            f"• 💸 <b>کل کارمزد پرداختی به صرافی:</b> <code>-${total_fees:.2f}</code>\n"
            f"• 💰 <b>سود/زیان خالص نهایی حساب:</b> <code>{net_symbol}${total_net:.2f}</code>"
        )

    def _parse_entry_range(self, entry_raw: str, current_price: Optional[float]) -> Tuple[float, float]:
        import re
        nums = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', entry_raw)]
        if len(nums) >= 2:
            return min(nums[0], nums[1]), max(nums[0], nums[1])
        elif len(nums) == 1:
            return nums[0] - 0.5, nums[0] + 0.5
        elif current_price:
            return current_price - 0.5, current_price + 0.5
        else:
            return 0.0, 0.0

    def evaluate_signal_status(self, current_price: Optional[float]) -> str:
        if not self.active_signal or not current_price:
            return "⏳ <i>قیمت لحظه‌ای بازار در دسترس نیست</i>"

        sig = self.active_signal
        direction = sig["direction"]
        e_min = sig["entry_min"]
        e_max = sig["entry_max"]
        entry = sig["entry_price"]
        sl = sig.get("stop_loss")
        
        s = sig.get("settings", self.settings)
        mode = s.get("mode", "OURBIT_FUTURES")
        balance = float(s.get("balance", 15.0))
        fee_rate = float(s.get("fee_rate", 0.04))

        # متریک‌های پوزیشن
        m_zero = self.calculate_trade_metrics(entry, 0.0, s)
        total_fee = m_zero["total_fee"]

        # پیش‌بینی سود تارگت‌ها با کسر کارمزد
        m_tp1 = self.calculate_trade_metrics(entry, 2.0, s)   # +20 pips = $2.0
        m_tp2 = self.calculate_trade_metrics(entry, 3.5, s)   # +35 pips = $3.5
        sl_dist = abs(entry - sl) if sl else 3.0
        m_sl = self.calculate_trade_metrics(entry, -sl_dist, s)

        status_lines = []

        # سربرگ تنظیمات فعال
        if mode == "OURBIT_FUTURES":
            lev = int(s.get("leverage", 100))
            pos_val = balance * lev
            status_lines.append(f"⚙️ <b>حالت:</b> Ourbit | <b>سرمایه:</b> ${balance:.2f} | <b>اهرم:</b> {lev}x (ارزش: ${pos_val:,.0f})")
            if m_zero["liq_distance_dollars"] > 0:
                liq_price = entry - m_zero["liq_distance_dollars"] if direction == "BUY" else entry + m_zero["liq_distance_dollars"]
                status_lines.append(f"☠️ <b>قیمت تخمینی لیکوئید:</b> <code>${liq_price:.2f}</code> (فاصله: <code>{m_zero['liq_distance_dollars']:.2f}$</code>)")
        else:
            lot = s.get("lot_size", 0.01)
            status_lines.append(f"⚙️ <b>حالت:</b> Forex MT5 | <b>حجم:</b> {lot} Lot ({lot*100:.1f} انس) | <b>مارجین:</b> ~${m_zero['used_margin']:.2f}")

        status_lines.append(f"💸 <b>کارمزد رفت‌وبرگشت ({fee_rate}%):</b> <code>-${total_fee:.2f}</code>")
        status_lines.append(f"💵 <b>قیمت لحظه‌ای طلا (XAUUSD):</b> <code>${current_price:.2f}</code>")

        if direction == "BUY":
            if e_min <= current_price <= e_max:
                status_lines.append("🟢 <b>وضعیت ورود:</b> <b>عالی (در محدوده خرید)</b> ✅")
            elif current_price > e_max:
                diff = current_price - e_max
                status_lines.append(f"🟡 <b>وضعیت ورود:</b> <code>+{diff:.2f}$</code> بالاتر از زون")
            else:
                diff = e_min - current_price
                status_lines.append(f"🔵 <b>وضعیت ورود:</b> <code>{diff:.2f}$</code> پایین‌تر از زون")

            if sl:
                dist_sl = current_price - sl
                status_lines.append(f"🛑 <b>حد ضرر:</b> <code>{sl:.2f}</code> (فاصله: <code>{dist_sl:.2f}$</code>)")
        else:
            if e_min <= current_price <= e_max:
                status_lines.append("🟢 <b>وضعیت ورود:</b> <b>عالی (در محدوده فروش)</b> ✅")
            elif current_price < e_min:
                diff = e_min - current_price
                status_lines.append(f"🟡 <b>وضعیت ورود:</b> <code>-{diff:.2f}$</code> ریخته")
            else:
                diff = current_price - e_max
                status_lines.append(f"🔵 <b>وضعیت ورود:</b> <code>{diff:.2f}$</code> بالاتر از زون")

            if sl:
                dist_sl = sl - current_price
                status_lines.append(f"🛑 <b>حد ضرر:</b> <code>{sl:.2f}</code> (فاصله: <code>{dist_sl:.2f}$</code>)")

        status_lines.append("")
        status_lines.append(f"💰 <b>پیش‌بینی سود و زیان (با کسر کارمزد ${total_fee:.2f}):</b>")
        status_lines.append(f"• تارگت اول (+۲۰ پیپ): ناخالص: <code>+${m_tp1['gross_pnl']:.2f}</code> | <b>خالص: <code>{'+' if m_tp1['net_pnl']>=0 else ''}${m_tp1['net_pnl']:.2f}</code></b>")
        status_lines.append(f"• تارگت دوم (+۳۵ پیپ): ناخالص: <code>+${m_tp2['gross_pnl']:.2f}</code> | <b>خالص: <code>{'+' if m_tp2['net_pnl']>=0 else ''}${m_tp2['net_pnl']:.2f}</code></b>")
        status_lines.append(f"• در صورت استاپ: ناخالص: <code>-${abs(m_sl['gross_pnl']):.2f}</code> | <b>خالص با کارمزد: <code>-${abs(m_sl['net_pnl']):.2f}</code></b>")

        return "\n".join(status_lines)

    def check_live_status_change(self, current_price: float) -> Optional[str]:
        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if not self.active_signal or self.active_signal.get("is_closed") or not current_price:
            return None

        sig = self.active_signal
        sig_num = sig.get("number", 1)
        direction = sig["direction"]
        e_min = sig["entry_min"]
        e_max = sig["entry_max"]
        entry = sig["entry_price"]
        sl = sig.get("stop_loss")
        s = sig.get("settings", self.settings)

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

        # ۱. رسیدن به تارگت سود (سود ۲ دلار یا ۲۰ پیپ به بالا):
        if cur_profit >= 2.0 and not sig.get("target_hit"):
            sig["target_hit"] = True
            sig["is_win"] = True
            self._save_active_signal()

            m_cur = self.calculate_trade_metrics(entry, cur_profit, s)
            sl_info = f"<code>{sl:.2f}</code>" if sl else "استاپ اولیه"
            net_sign = "+" if m_cur["net_pnl"] >= 0 else ""

            return (
                f"🎯 <b>تارگت سیگنال #{sig_num} محقق شد! (+{cur_profit:.1f}$)</b>\n\n"
                f"طلا به سود <b>+{int(cur_profit*10)} پیپ</b> رسید! 🚀\n"
                f"💵 قیمت لحظه‌ای: <code>${current_price:.2f}</code>\n"
                f"📈 <b>سود ناخالص:</b> <code>+{m_cur['gross_pnl']:.2f}$</code> | 💸 <b>کارمزد:</b> <code>-${m_cur['total_fee']:.2f}</code>\n"
                f"💰 <b>سود خالص شما:</b> <code>{net_sign}${m_cur['net_pnl']:.2f}</code> (<b>+{m_cur['net_pct']:.0f}%</b>)\n\n"
                f"✅ تارگت اول محقق شد و معامله به عنوان برد (WIN) ثبت گردید.\n"
                f"📌 حد ضرر روی استاپ اصلی ادمین ({sl_info}) حفظ شده و با ارسال دستور «فری کن» در کانال به نقطه ورود منتقل خواهد شد."
            )

        # ۲. بررسی بازگشت قیمت به نقطه ورود (فقط در صورتی که ادمین معامله را ریسک‌فری کرده باشد):
        if sig.get("is_risk_free"):
            is_returned_to_entry = (direction == "BUY" and current_price <= entry) or (direction == "SELL" and current_price >= entry)
            if is_returned_to_entry:
                return self.close_trade("BREAK_EVEN_WIN", "سیگنال پس از ریسک‌فری، در نقطه ورود سر‌به‌سر بسته شد.", current_price)

        # ۳. لمس حد ضرر:
        if sl:
            is_stopped = (direction == "BUY" and current_price <= sl) or (direction == "SELL" and current_price >= sl)
            if is_stopped:
                if sig.get("target_hit"):
                    return self.close_trade(
                        "PARTIAL_WIN_THEN_SL",
                        f"سیگنال ابتدا تارگت اول (+{sig['max_profit']:.1f}$ / +{int(sig['max_profit']*10)} پیپ) را تاچ کرد و در بازگشت بازار، حد ضرر ({sl:.2f}) لمس شد.",
                        current_price
                    )
                elif sig.get("is_risk_free") or sig.get("is_win"):
                    return self.close_trade("BREAK_EVEN_WIN", f"حد ضرر ریسک‌فری ({sl:.2f}) لمس شد.", current_price)
                else:
                    return self.close_trade("LOSS", f"قیمت طلا به {current_price:.2f} رسید و حد ضرر ({sl:.2f}) لمس شد.", current_price)

        # ۴. ورود به محدوده
        if not sig["entered_zone_alerted"] and (e_min <= current_price <= e_max):
            sig["entered_zone_alerted"] = True
            self._save_active_signal()
            return (
                f"🎯 <b>سیگنال #{sig_num}: طلا وارد زون ورود شد!</b>\n\n"
                f"جهت: <b>{direction}</b> | قیمت: <code>${current_price:.2f}</code>\n"
                f"محدوده ورود: <code>{sig['entry_raw']}</code>\n"
                f"⚡️ پوزیشن با سرمایه تنظیمی آماده است."
            )

        # ۵. منقضی کردن بعد از ۴۵ دقیقه
        if time.time() - sig["created_at"] > 2700:
            if sig.get("is_win") or sig["max_profit"] >= 2.0:
                return self.close_trade("WIN", f"سیگنال پس از ثبت بیشینه سود +{sig['max_profit']:.1f}$ به پایان رسید.", current_price)
            else:
                return self.close_trade("EXPIRED", "سیگنال پس از ۴۵ دقیقه به پایان رسید.", current_price)

        return None

    def mark_user_participation(self, signal_number: int, entered: bool) -> str:
        if self.active_signal and self.active_signal.get("number") == signal_number:
            self.active_signal["user_entered"] = entered
            self._save_active_signal()

        for t in self.trade_history:
            if t.get("number") == signal_number:
                t["user_entered"] = entered
                self._save_history()
                break

        if entered:
            return f"✅ سیگنال #{signal_number} در کارنامه شخصی شما ثبت شد."
        else:
            return f"⏭ سیگنال #{signal_number} از کارنامه شخصی شما رد شد."

    def get_daily_summary(self) -> str:
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=3, minutes=30))
        now = datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")

        today_trades = []
        for t in self.trade_history:
            t_time = datetime.fromtimestamp(t.get("closed_at", t.get("created_at", 0)), tz)
            if t_time.strftime("%Y-%m-%d") == today_str:
                today_trades.append(t)

        active_note = ""
        if self.active_signal and not self.active_signal.get("is_closed"):
            active_note = f"\n⚡️ <i>سیگنال #{self.active_signal['number']} هنوز باز است و در حال رصد می‌باشد.</i>\n"

        if not today_trades and not self.active_signal:
            return f"🌙 <b>گزارش پایان روز ({today_str}):</b>\n\nامروز هیچ سیگنالی بسته نشده است."

        wins = sum(1 for t in today_trades if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN", "PARTIAL_WIN_THEN_SL"])
        losses = sum(1 for t in today_trades if t.get("outcome") == "LOSS")
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        
        total_gross = sum(t.get("realized_gross_pnl", 0.0) for t in today_trades)
        total_fees = sum(t.get("total_fee", 0.0) for t in today_trades)
        total_net = sum(t.get("realized_pnl_usd", 0.0) for t in today_trades)
        total_pips = sum(int(t.get("max_profit", 0.0) * 10) for t in today_trades if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN", "PARTIAL_WIN_THEN_SL"])

        my_trades = [t for t in today_trades if t.get("user_entered") is True]
        my_wins = sum(1 for t in my_trades if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN", "PARTIAL_WIN_THEN_SL"])
        my_losses = sum(1 for t in my_trades if t.get("outcome") == "LOSS")
        my_net = sum(t.get("realized_pnl_usd", 0.0) for t in my_trades)

        gross_sign = "+" if total_gross >= 0 else ""
        net_sign = "+" if total_net >= 0 else ""
        my_sign = "+" if my_net >= 0 else ""

        summary = (
            f"🌙 <b>گزارش روزانه عملکرد سیگنال‌های طلا</b> 🌙\n"
            f"📅 تاریخ: <code>{today_str}</code> | ساعت: <code>{now.strftime('%H:%M')}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 <b>آمار کل کانال امروز:</b>\n"
            f"• تعداد سیگنال‌ها: <b>{len(today_trades)}</b>\n"
            f"• بردها: <b>{wins} ✅</b> | باخت‌ها: <b>{losses} ❌</b>\n"
            f"• نرخ موفقیت: <b>{win_rate:.0f}%</b> | مجموع پیپ: <b>+{total_pips} پیپ</b>\n"
            f"• 📈 <b>جمع سود/زیان ناخالص:</b> <code>{gross_sign}${total_gross:.2f}</code>\n"
            f"• 💸 <b>کل کارمزد صرافی:</b> <code>-${total_fees:.2f}</code>\n"
            f"• 💰 <b>سود/زیان خالص نهایی کانال:</b> <code>{net_sign}${total_net:.2f}</code>\n\n"
        )

        if my_trades:
            summary += (
                f"👤 <b>کارنامه معاملات شخصی شما امروز:</b>\n"
                f"• معاملات بازشده توسط شما: <b>{len(my_trades)}</b> (برد: {my_wins} | باخت: {my_losses})\n"
                f"• 💰 <b>سود/زیان خالص حساب شما:</b> <code>{my_sign}${my_net:.2f}</code> 🚀\n\n"
            )

        summary += (
            f"{active_note}"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>مدیریت تنظیمات و سرمایه با دکمه</i> <code>⚙️ تنظیمات معامله</code>"
        )
        return summary

evaluator = SignalEvaluator()
