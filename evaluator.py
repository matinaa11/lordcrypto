import logging
import time
import json
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger("Evaluator")

class SignalEvaluator:
    def __init__(self, history_file: str = "trade_history.json", default_budget: float = 2.0):
        self.history_file = history_file
        self.trade_budget: float = default_budget  # مبلغ معامله هر روز/هر سیگنال به دلار
        self.active_signal: Optional[Dict[str, Any]] = None
        self.trade_history: List[Dict[str, Any]] = self._load_history()
        # شمارنده شماره سیگنال‌ها (ادامه‌دار از تاریخچه)
        self.signal_counter: int = len(self.trade_history)

    def set_budget(self, new_budget: float) -> str:
        """
        تغییر مبلغ سرمایه معامله توسط کاربر
        """
        if new_budget <= 0:
            return "❌ مبلغ باید بزرگتر از صفر باشد."
        self.trade_budget = round(new_budget, 2)
        return f"✅ مبلغ سرمایه هر معامله با موفقیت به <b>${self.trade_budget:.2f}</b> تنظیم شد."

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

    def register_entry(self, direction: str, entry_raw: str, current_price: Optional[float]) -> tuple[int, str]:
        """
        ثبت سیگنال جدید با شماره‌گذاری متوالی و تحلیل موقعیت بازار
        خروجی: (شماره سیگنال, متن تحلیل)
        """
        if self.active_signal and not self.active_signal.get("is_closed"):
            self.close_trade(
                outcome="EXPIRED",
                reason="سیگنال جدید صادر شد و سیگنال قبلی جایگزین گردید.",
                exit_price=current_price
            )

        self.signal_counter += 1
        sig_num = self.signal_counter

        entry_min, entry_max = self._parse_entry_range(entry_raw, current_price)
        mid_entry = (entry_min + entry_max) / 2 if (entry_min and entry_max) else (current_price or 0.0)

        self.active_signal = {
            "id": int(time.time()),
            "number": sig_num,
            "direction": "BUY" if "buy" in direction.lower() or "خرید" in direction.lower() else "SELL",
            "entry_min": entry_min,
            "entry_max": entry_max,
            "entry_price": mid_entry,
            "entry_raw": entry_raw,
            "stop_loss": None,
            "budget": self.trade_budget,
            "created_at": time.time(),
            "max_profit": 0.0,
            "max_drawdown": 0.0,
            "is_risk_free": False,
            "entered_zone_alerted": False,
            "profit_alerted_levels": [],
            "is_closed": False,
            "outcome": None,
            "outcome_reason": "",
            "realized_pnl_usd": 0.0
        }

        return sig_num, self.evaluate_signal_status(current_price)

    def register_stop(self, stop_val_str: str, current_price: Optional[float]) -> str:
        """
        ثبت حد ضرر برای سیگنال فعال
        """
        try:
            sl = float(stop_val_str)
        except ValueError:
            return ""

        if self.active_signal:
            self.active_signal["stop_loss"] = sl
            # بررسی لمس فوری
            if current_price:
                d = self.active_signal["direction"]
                if (d == "BUY" and current_price <= sl) or (d == "SELL" and current_price >= sl):
                    return self.close_trade("LOSS", f"استاپ لاس بلافاصله در قیمت {current_price:.2f} لمس شد.", current_price)

        return self.evaluate_signal_status(current_price)

    def register_risk_free(self) -> Optional[str]:
        if self.active_signal and not self.active_signal.get("is_closed"):
            self.active_signal["is_risk_free"] = True
            self.active_signal["stop_loss"] = self.active_signal["entry_price"]
            return "🛡 <b>معامله ریسک‌فری شد</b> (استاپ لاس به نقطه ورود منتقل شد و خطر ضرر صفر شد)."
        return None

    def register_break_even(self, current_price: Optional[float]) -> Optional[str]:
        if self.active_signal and not self.active_signal.get("is_closed"):
            max_p = self.active_signal.get("max_profit", 0.0)
            if max_p >= 1.5:
                reason = f"سیگنال ابتدا تا {max_p:.1f}$ سود رفت (+{int(max_p*10)} پیپ) و سپس در نقطه ورود سر‌به‌سر بسته شد."
                return self.close_trade("BREAK_EVEN_WIN", reason, current_price)
            else:
                reason = "سیگنال در نقطه ورود بدون ضرر خروج داده شد."
                return self.close_trade("BREAK_EVEN", reason, current_price)
        return None

    def register_stop_hit_message(self, current_price: Optional[float]) -> Optional[str]:
        if self.active_signal and not self.active_signal.get("is_closed"):
            return self.close_trade("LOSS", "ادمین کانال اعلام کرد حد ضرر (استاپ) تاچ شد.", current_price)
        return None

    def calculate_dollar_pnl(self, profit_dollars_gold: float, sl_distance: Optional[float], budget: float) -> tuple[float, float]:
        """
        محاسبه سود یا ضرر دلاری کاربر بر اساس سرمایه ورودی
        خروجی: (سود دلاری, درصد بازدهی)
        """
        # اگر فاصله استاپ مشخص باشد، محاسبه بر مبنای مدیریت سرمایه استاندارد (Risk-to-Reward)
        if sl_distance and sl_distance > 0:
            ratio = profit_dollars_gold / sl_distance
            pnl_usd = round(ratio * budget, 2)
            pct = round(ratio * 100, 1)
            return pnl_usd, pct
        else:
            # تخمین بر مبنای حرکت هر ۱ دلار طلا = ۵۰٪ سود با اهرم استاندارد روی ۲ دلار
            ratio = profit_dollars_gold / 2.5
            pnl_usd = round(ratio * budget, 2)
            pct = round(ratio * 100, 1)
            return pnl_usd, pct

    def close_trade(self, outcome: str, reason: str, exit_price: Optional[float]) -> str:
        if not self.active_signal:
            return ""

        sig = self.active_signal
        sig["is_closed"] = True
        sig["outcome"] = outcome
        sig["outcome_reason"] = reason
        sig["exit_price"] = exit_price or sig["entry_price"]
        sig["closed_at"] = time.time()

        budget = sig.get("budget", self.trade_budget)
        entry = sig["entry_price"]
        sl = sig.get("stop_loss")
        sl_dist = abs(entry - sl) if sl else 2.5

        # محاسبه سود یا ضرر دلاری نهایی
        if outcome in ["WIN", "BREAK_EVEN_WIN"]:
            max_p = sig.get("max_profit", 0.0)
            pnl_usd, pnl_pct = self.calculate_dollar_pnl(max_p, sl_dist, budget)
            sig["realized_pnl_usd"] = pnl_usd
            sig["realized_pnl_pct"] = pnl_pct
        elif outcome == "LOSS":
            sig["realized_pnl_usd"] = -budget
            sig["realized_pnl_pct"] = -100.0
        else:
            sig["realized_pnl_usd"] = 0.0
            sig["realized_pnl_pct"] = 0.0

        saved_copy = sig.copy()
        if "profit_alerted_levels" in saved_copy and isinstance(saved_copy["profit_alerted_levels"], set):
            saved_copy["profit_alerted_levels"] = list(saved_copy["profit_alerted_levels"])
        self.trade_history.append(saved_copy)
        self._save_history()

        return self._format_outcome_report(sig)

    def _format_outcome_report(self, sig: Dict[str, Any]) -> str:
        sig_num = sig.get("number", 1)
        outcome = sig["outcome"]
        direction = sig["direction"]
        entry = sig["entry_price"]
        exit_p = sig.get("exit_price", entry)
        max_p = sig.get("max_profit", 0.0)
        pips = int(max_p * 10)
        budget = sig.get("budget", self.trade_budget)
        pnl_usd = sig.get("realized_pnl_usd", 0.0)
        pnl_pct = sig.get("realized_pnl_pct", 0.0)

        stats = self.get_stats_summary()

        if outcome in ["WIN", "BREAK_EVEN_WIN"]:
            header = f"🏆 <b>نتیجه نهایی سیگنال #{sig_num}: درست درآمد (WIN) ✅</b>"
            badge = "🟢 <b>موفق (سودده)</b>"
            pnl_text = f"💰 <b>سود خالص شما با سرمایه ${budget:.2f}:</b> <code>+${pnl_usd:.2f}</code> (<b>+{pnl_pct:.0f}%</b>) 🚀"
        elif outcome == "LOSS":
            header = f"🚨 <b>نتیجه نهایی سیگنال #{sig_num}: اشتباه درآمد (LOSS) ❌</b>"
            badge = "🔴 <b>ناموفق (استاپ خورد)</b>"
            pnl_text = f"💸 <b>ضرر این معامله با سرمایه ${budget:.2f}:</b> <code>-${budget:.2f}</code> (-100%)"
        else:
            header = f"⚪️ <b>نتیجه نهایی سیگنال #{sig_num}: خروج سر‌به‌سر (Break-Even)</b>"
            badge = "⚪️ <b>بدون سود و ضرر</b>"
            pnl_text = f"💵 <b>تغییر موجودی شما:</b> <code>$0.00</code> (سرمایه ${budget:.2f} بدون تغییر حفظ شد)"

        report = (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔸 <b>شماره سیگنال:</b> #{sig_num}\n"
            f"🔸 <b>نماد:</b> XAUUSD (طلا)\n"
            f"🔸 <b>نوع سیگنال:</b> {direction}\n"
            f"🔸 <b>نقطه ورود:</b> <code>{sig['entry_raw']}</code> (~{entry:.2f})\n"
            f"🔸 <b>خروج در:</b> <code>{exit_p:.2f}</code>\n"
            f"🔸 <b>بیشترین حرکت طلا:</b> <code>+{max_p:.1f}$</code> (+{pips} پیپ)\n"
            f"🔸 <b>وضعیت:</b> {badge}\n\n"
            f"{pnl_text}\n\n"
            f"📝 <b>دلیل و شرح:</b>\n<i>{sig['outcome_reason']}</i>\n\n"
            f"📊 <b>کارنامه کل سیگنال‌ها:</b>\n{stats}"
        )
        return report

    def get_stats_summary(self) -> str:
        if not self.trade_history:
            return f"<i>هنوز سابقه‌ای ثبت نشده است. (سرمایه هر معامله: ${self.trade_budget:.2f})</i>"

        wins = sum(1 for t in self.trade_history if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN"])
        losses = sum(1 for t in self.trade_history if t.get("outcome") == "LOSS")
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0

        # محاسبه مجموع سود دلاری کاربر
        total_pnl = sum(t.get("realized_pnl_usd", 0.0) for t in self.trade_history)
        pnl_symbol = "+" if total_pnl >= 0 else ""

        return (
            f"• کل سیگنال‌ها: <b>{len(self.trade_history)}</b> (برد: <b>{wins} ✅</b> | باخت: <b>{losses} ❌</b>)\n"
            f"• نرخ موفقیت (Win Rate): <b>{win_rate:.0f}%</b>\n"
            f"• <b>سود/زیان کل حساب با سرمایه ${self.trade_budget:.2f}:</b> <code>{pnl_symbol}${total_pnl:.2f}</code>"
        )

    def _parse_entry_range(self, entry_raw: str, current_price: Optional[float]) -> tuple[float, float]:
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
        sl = sig.get("stop_loss")
        budget = sig.get("budget", self.trade_budget)

        status_lines = []
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
                status_lines.append(f"🛑 <b>فاصله تا استاپ لاس:</b> <code>{dist_sl:.2f}$</code>")
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
                status_lines.append(f"🛑 <b>فاصله تا استاپ لاس:</b> <code>{dist_sl:.2f}$</code>")

        # برآورد سود با سرمایه کاربر
        sl_dist = abs(sig["entry_price"] - sl) if sl else 2.5
        profit_estimate_1, _ = self.calculate_dollar_pnl(2.0, sl_dist, budget)
        profit_estimate_2, _ = self.calculate_dollar_pnl(3.5, sl_dist, budget)

        status_lines.append("")
        status_lines.append(f"💰 <b>پیش‌بینی سود با سرمایه ${budget:.2f} شما در این سیگنال:</b>")
        status_lines.append(f"• تارگت اول (+۲۰ پیپ): <code>+${profit_estimate_1:.2f} سود</code>")
        status_lines.append(f"• تارگت دوم (+۳۵ پیپ): <code>+${profit_estimate_2:.2f} سود</code>")
        status_lines.append(f"• در صورت استاپ: <code>-${budget:.2f} ضرر</code>")

        return "\n".join(status_lines)

    def check_live_status_change(self, current_price: float) -> Optional[str]:
        if not self.active_signal or self.active_signal.get("is_closed") or not current_price:
            return None

        sig = self.active_signal
        sig_num = sig.get("number", 1)
        direction = sig["direction"]
        e_min = sig["entry_min"]
        e_max = sig["entry_max"]
        entry = sig["entry_price"]
        sl = sig.get("stop_loss")
        budget = sig.get("budget", self.trade_budget)

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

        # ۱. لمس استاپ لاس
        if sl:
            is_stopped = (direction == "BUY" and current_price <= sl) or (direction == "SELL" and current_price >= sl)
            if is_stopped:
                return self.close_trade("LOSS", f"قیمت طلا به {current_price:.2f} رسید و حد ضرر لمس شد.", current_price)

        # ۲. رسیدن به تارگت سود
        sl_dist = abs(entry - sl) if sl else 2.5
        pnl_usd, pnl_pct = self.calculate_dollar_pnl(cur_profit, sl_dist, budget)

        if cur_profit >= 3.0 and "profit_3" not in sig["profit_alerted_levels"]:
            sig["profit_alerted_levels"].append("profit_3")
            return (
                f"🎯 <b>تارگت سیگنال #{sig_num} محقق شد! (+{cur_profit:.1f}$)</b>\n\n"
                f"طلا به سود <b>+{int(cur_profit*10)} پیپ</b> رسید!\n"
                f"💵 قیمت لحظه‌ای: <code>${current_price:.2f}</code>\n"
                f"💰 <b>سود شما تا الان با سرمایه ${budget:.2f}:</b> <code>+${pnl_usd:.2f}</code> (<b>+{pnl_pct:.0f}%</b>) 🚀"
            )

        # ۳. ورود به محدوده
        if not sig["entered_zone_alerted"] and (e_min <= current_price <= e_max):
            sig["entered_zone_alerted"] = True
            return (
                f"🎯 <b>سیگنال #{sig_num}: طلا وارد زون ورود شد!</b>\n\n"
                f"جهت: <b>{direction}</b> | قیمت: <code>${current_price:.2f}</code>\n"
                f"محدوده ورود: <code>{sig['entry_raw']}</code>\n"
                f"⚡️ اکنون پوزیشن با ${budget:.2f} آماده است."
            )

        # ۴. منقضی کردن بعد از ۴۵ دقیقه
        if time.time() - sig["created_at"] > 2700:
            if sig["max_profit"] >= 2.0:
                return self.close_trade("WIN", f"سیگنال پس از ثبت بیشینه سود +{sig['max_profit']:.1f}$ به پایان رسید.", current_price)
            else:
                return self.close_trade("EXPIRED", "سیگنال پس از ۴۵ دقیقه به پایان رسید.", current_price)

        return None

    def mark_user_participation(self, signal_number: int, entered: bool) -> str:
        """
        ثبت اینکه کاربر واقعاً وارد این معامله شده یا آن را رد کرده است
        """
        if self.active_signal and self.active_signal.get("number") == signal_number:
            self.active_signal["user_entered"] = entered

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
        """
        محاسبه کارنامه و بیلان روزانه عملکرد سیگنال‌های طلا (ساعت ۲۳:۰۰ یا دستی)
        """
        from datetime import datetime, timezone, timedelta
        # ساعت رسمی ایران (UTC+3:30)
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

        wins = sum(1 for t in today_trades if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN"])
        losses = sum(1 for t in today_trades if t.get("outcome") == "LOSS")
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        total_pnl = sum(t.get("realized_pnl_usd", 0.0) for t in today_trades)
        total_pips = sum(int(t.get("max_profit", 0.0) * 10) for t in today_trades if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN"])

        # معاملات شخصی کاربر
        my_trades = [t for t in today_trades if t.get("user_entered") is True]
        my_wins = sum(1 for t in my_trades if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN"])
        my_losses = sum(1 for t in my_trades if t.get("outcome") == "LOSS")
        my_pnl = sum(t.get("realized_pnl_usd", 0.0) for t in my_trades)

        sign = "+" if total_pnl >= 0 else ""
        my_sign = "+" if my_pnl >= 0 else ""

        summary = (
            f"🌙 <b>گزارش روزانه عملکرد سیگنال‌های طلا</b> 🌙\n"
            f"📅 تاریخ: <code>{today_str}</code> | ساعت: <code>{now.strftime('%H:%M')}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 <b>آمار کل کانال امروز:</b>\n"
            f"• تعداد سیگنال‌ها: <b>{len(today_trades)}</b>\n"
            f"• بردها: <b>{wins} ✅</b> | باخت‌ها: <b>{losses} ❌</b>\n"
            f"• نرخ موفقیت کانال: <b>{win_rate:.0f}%</b>\n"
            f"• مجموع پیپ مثبت: <b>+{total_pips} پیپ</b>\n"
            f"• سود/زیان تئوری کل کانال: <code>{sign}${total_pnl:.2f}</code>\n\n"
        )

        if my_trades:
            summary += (
                f"👤 <b>کارنامه معاملات شخصی شما امروز:</b>\n"
                f"• معاملات بازشده توسط شما: <b>{len(my_trades)}</b> (برد: {my_wins} | باخت: {my_losses})\n"
                f"• 💰 <b>سود/زیان خالص حساب شما:</b> <code>{my_sign}${my_pnl:.2f}</code> 🚀\n\n"
            )

        summary += (
            f"{active_note}"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>تنظیم سرمایه برای فردا با دستور:</i> <code>/budget [مبلغ]</code>"
        )
        return summary

default_trade_budget = float(os.getenv("TRADE_BUDGET_USD", "2.0"))
evaluator = SignalEvaluator(default_budget=default_trade_budget)
