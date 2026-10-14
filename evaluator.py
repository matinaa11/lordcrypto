import logging
import time
import json
import os
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("Evaluator")

class SignalEvaluator:
    def __init__(self, history_file: str = "trade_history.json", active_file: str = "active_signal.json", default_budget: float = 2.0):
        self.history_file = history_file
        self.active_file = active_file
        self.trade_budget: float = default_budget
        self.trade_history: List[Dict[str, Any]] = self._load_history()
        self.active_signal: Optional[Dict[str, Any]] = self._load_active_signal()
        self.signal_counter: int = self._determine_counter()

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

    def set_budget(self, new_budget: float) -> str:
        if new_budget <= 0:
            return "❌ مبلغ باید بزرگتر از صفر باشد."
        self.trade_budget = round(new_budget, 2)
        if self.active_signal and not self.active_signal.get("is_closed"):
            self.active_signal["budget"] = self.trade_budget
            self._save_active_signal()
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

    def _load_active_signal(self) -> Optional[Dict[str, Any]]:
        if os.path.exists(self.active_file):
            try:
                with open(self.active_file, "r", encoding="utf-8") as f:
                    sig = json.load(f)
                    if sig and not sig.get("is_closed"):
                        # اگر کمتر از ۳ ساعت گذشته باشد هنوز معتبر است
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

    def register_entry(self, direction: str, entry_raw: str, current_price: Optional[float]) -> Tuple[int, str]:
        """
        ثبت سیگنال جدید در حافظه و دیتابیس با استاپ‌پیش‌فرض
        """
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

        # استاپ‌لاس موقت پیش‌فرض (۳ دلار فاصله) تا زمانی که ادمین عدد Stop: را بفرستد
        default_sl = round(mid_entry - 3.0, 2) if dir_clean == "BUY" else round(mid_entry + 3.0, 2)

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
            "budget": self.trade_budget,
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
            "realized_pnl_usd": 0.0
        }

        self._save_active_signal()
        logger.info(f"✅ سیگنال ورود #{sig_num} با استاپ موقت {default_sl} در دیتابیس ثبت شد.")
        return sig_num, self.evaluate_signal_status(current_price)

    def register_stop(self, stop_val_str: str, current_price: Optional[float]) -> Tuple[str, Optional[str]]:
        """
        لینک کردن قطعی پیام Stop Loss به سیگنال فعال و ذخیره در دیتابیس
        """
        try:
            sl = float(stop_val_str)
        except ValueError:
            return "", None

        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if self.active_signal and not self.active_signal.get("is_closed"):
            self.active_signal["stop_loss"] = sl
            self.active_signal["is_default_sl"] = False
            self._save_active_signal()
            logger.info(f"✅ حد ضرر سیگنال #{self.active_signal['number']} به عدد {sl} در دیتابیس لینک و آپدیت شد.")

            # اگر همین لحظه قیمت به استاپ برخورد کرده باشد (تنها اگر قبلاً تارگت نزده باشد)
            if current_price and not self.active_signal.get("is_win") and not self.active_signal.get("target_hit"):
                d = self.active_signal["direction"]
                is_hit = (d == "BUY" and current_price <= sl) or (d == "SELL" and current_price >= sl)
                if is_hit:
                    outcome_report = self.close_trade("LOSS", f"استاپ‌لاس اعلامی ({sl}) بلافاصله در قیمت {current_price:.2f} لمس شد.", current_price)
                    return f"🛑 <b>حد ضرر لمس شد:</b> <code>{sl}</code>", outcome_report

            return self.evaluate_signal_status(current_price), None
        else:
            logger.warning("پیام Stop دریافت شد اما سیگنال بازی در دیتابیس یافت نشد.")
            return f"🛑 <b>حد ضرر اعلامی:</b> <code>{sl}</code> (سیگنال بازی برای اتصال یافت نشد)", None

    def register_risk_free(self) -> Tuple[bool, str]:
        """
        دستور «فری کن / ریسک فری»: انتقال قطعی استاپ به نقطه ورود و فعال‌سازی پرچم برد
        """
        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if self.active_signal and not self.active_signal.get("is_closed"):
            sig = self.active_signal
            sig["is_risk_free"] = True
            sig["is_win"] = True  # از این لحظه معامله برد تضمین شده است
            sig["stop_loss"] = sig["entry_price"]  # استاپ به نقطه ورود منتقل شد
            self._save_active_signal()

            msg = (
                f"🛡 <b>معامله سیگنال #{sig['number']} ریسک‌فری شد!</b>\n\n"
                f"📌 حد ضرر (SL) دقیقاً به نقطه ورود (<code>{sig['entry_price']:.2f}</code>) منتقل شد.\n"
                f"خطر ضرر صفر شد و در صورت برگشت قیمت، معامله سر‌به‌سر بسته می‌شود."
            )
            return True, msg
        return False, "⚠️ سیگنال فعالی برای ریسک‌فری یافت نشد."

    def register_manual_close(self, current_price: Optional[float], reason: str = "دستور بستن (ببند / فول کلوز) توسط ادمین") -> Tuple[bool, str, Optional[str]]:
        """
        دستور «ببند / فول کلوز»: بستن فوری سیگنال فعال با قیمت لحظه‌ای بازار
        """
        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if not self.active_signal or self.active_signal.get("is_closed"):
            return False, "⚠️ سیگنال بازی برای بستن یافت نشد.", None

        sig = self.active_signal
        exit_p = current_price or sig["entry_price"]
        direction = sig["direction"]
        entry = sig["entry_price"]

        # محاسبه سود یا ضرر لحظه‌ای
        if direction == "BUY":
            pnl_points = exit_p - entry
        else:
            pnl_points = entry - exit_p

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
            reason = f"سیگنال پس از ثبت بیشینه سود {max_p:.1f}$ (+{int(max_p*10)} پیپ)، در نقطه ورود سر‌به‌سر بسته شد."
            return self.close_trade("BREAK_EVEN_WIN", reason, current_price)
        return None

    def register_stop_hit_message(self, current_price: Optional[float]) -> Optional[str]:
        if not self.active_signal:
            self.active_signal = self._load_active_signal()

        if self.active_signal and not self.active_signal.get("is_closed"):
            # اگر قبلاً تارگت زده بود، حتی اگر استاپ بخورد نباید باخت شود
            if self.active_signal.get("is_win") or self.active_signal.get("target_hit"):
                return self.close_trade("BREAK_EVEN_WIN", "ادمین اعلام استاپ کرد اما تارگت قبلاً محقق شده بود و معامله بدون ضرر بسته شد.", current_price)
            return self.close_trade("LOSS", "ادمین کانال اعلام کرد حد ضرر (استاپ) تاچ شد.", current_price)
        return None

    def calculate_dollar_pnl(self, profit_dollars_gold: float, sl_distance: Optional[float], budget: float) -> Tuple[float, float]:
        if sl_distance and sl_distance > 0:
            ratio = profit_dollars_gold / sl_distance
            pnl_usd = round(ratio * budget, 2)
            pct = round(ratio * 100, 1)
            return pnl_usd, pct
        else:
            ratio = profit_dollars_gold / 2.5
            pnl_usd = round(ratio * budget, 2)
            pct = round(ratio * 100, 1)
            return pnl_usd, pct

    def close_trade(self, outcome: str, reason: str, exit_price: Optional[float]) -> str:
        if not self.active_signal:
            return ""

        sig = self.active_signal

        # محافظت بحرانی: اگر سیگنال به تارگت سود رسیده باشد یا ریسک‌فری شده باشد، هرگز باخت (-100%) نمی‌خورد!
        if (sig.get("is_win") or sig.get("target_hit") or sig.get("is_risk_free")) and outcome == "LOSS":
            outcome = "BREAK_EVEN_WIN"
            reason = f"سیگنال قبلاً به سود +{sig.get('max_profit', 0.0):.1f}$ (+{int(sig.get('max_profit', 0.0)*10)} پیپ) رسیده بود و در نقطه ورود سر‌به‌سر بسته شد."

        sig["is_closed"] = True
        sig["outcome"] = outcome
        sig["outcome_reason"] = reason
        sig["exit_price"] = exit_price or sig["entry_price"]
        sig["closed_at"] = time.time()

        budget = sig.get("budget", self.trade_budget)
        entry = sig["entry_price"]
        sl = sig.get("stop_loss")
        sl_dist = abs(entry - sl) if sl else 2.5

        if outcome in ["WIN", "BREAK_EVEN_WIN"]:
            max_p = sig.get("max_profit", 0.0)
            if outcome == "BREAK_EVEN_WIN" and max_p < 2.0:
                pnl_usd = 0.0
                pnl_pct = 0.0
            else:
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

        # پاک کردن سیگنال فعال از فایل
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
        budget = sig.get("budget", self.trade_budget)
        pnl_usd = sig.get("realized_pnl_usd", 0.0)
        pnl_pct = sig.get("realized_pnl_pct", 0.0)

        stats = self.get_stats_summary()

        if outcome == "WIN":
            header = f"🏆 <b>نتیجه نهایی سیگنال #{sig_num}: درست درآمد (WIN) ✅</b>"
            badge = "🟢 <b>موفق (سودده)</b>"
            pnl_text = f"💰 <b>سود خالص شما با سرمایه ${budget:.2f}:</b> <code>+${pnl_usd:.2f}</code> (<b>+{pnl_pct:.0f}%</b>) 🚀"
        elif outcome == "BREAK_EVEN_WIN":
            header = f"🏆 <b>نتیجه نهایی سیگنال #{sig_num}: موفق / سر‌به‌سر (WIN) ✅</b>"
            badge = "🟢 <b>موفق (ریسک‌فری شد)</b>"
            pnl_text = f"💰 <b>تغییر موجودی شما:</b> <code>+${pnl_usd:.2f}</code> (سرمایه حفظ شد و خطر صفر گردید)"
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

        total_pnl = sum(t.get("realized_pnl_usd", 0.0) for t in self.trade_history)
        pnl_symbol = "+" if total_pnl >= 0 else ""

        return (
            f"• کل سیگنال‌ها: <b>{len(self.trade_history)}</b> (برد: <b>{wins} ✅</b> | باخت: <b>{losses} ❌</b>)\n"
            f"• نرخ موفقیت (Win Rate): <b>{win_rate:.0f}%</b>\n"
            f"• <b>سود/زیان کل حساب با سرمایه ${self.trade_budget:.2f}:</b> <code>{pnl_symbol}${total_pnl:.2f}</code>"
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
        """
        پایش ثانیه‌ای:
        - اگر قیمت به تارگت رسید: بلافاصله استاپ به نقطه ورود منتقل و is_win فعال می‌شود.
        - اگر قیمت به استاپ بخورد، فقط زمانی LOSS می‌شود که قبلاً تارگت نزده باشد.
        """
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

        # ۱. رسیدن به تارگت سود (مثلاً سود ۲ دلار یا ۲۰ پیپ به بالا):
        # با رسیدن به تارگت، بلافاصله استاپ به نقطه ورود منتقل و معامله برد تثبیت می‌شود!
        if cur_profit >= 2.0 and not sig.get("target_hit"):
            sig["target_hit"] = True
            sig["is_win"] = True
            sig["is_risk_free"] = True
            sig["stop_loss"] = entry  # استاپ به نقطه ورود منتقل شد
            self._save_active_signal()

            sl_dist = abs(entry - sl) if sl else 2.5
            pnl_usd, pnl_pct = self.calculate_dollar_pnl(cur_profit, sl_dist, budget)

            return (
                f"🎯 <b>تارگت سیگنال #{sig_num} محقق شد! (+{cur_profit:.1f}$)</b>\n\n"
                f"طلا به سود <b>+{int(cur_profit*10)} پیپ</b> رسید!\n"
                f"💵 قیمت لحظه‌ای: <code>${current_price:.2f}</code>\n"
                f"💰 <b>سود شما تا الان با سرمایه ${budget:.2f}:</b> <code>+${pnl_usd:.2f}</code> (<b>+{pnl_pct:.0f}%</b>) 🚀\n\n"
                f"🛡 <b>حد ضرر به صورت خودکار به نقطه ورود ({entry:.2f}) منتقل و معامله ریسک‌فری شد.</b>\n"
                f"✅ این معامله به عنوان برد (WIN) تثبیت شد و دیگر امکان باخت ندارد."
            )

        # ۲. بررسی بازگشت قیمت به نقطه ورود پس از تاچ تارگت یا ریسک‌فری:
        if sig.get("target_hit") or sig.get("is_risk_free"):
            is_returned_to_entry = (direction == "BUY" and current_price <= entry) or (direction == "SELL" and current_price >= entry)
            if is_returned_to_entry:
                return self.close_trade("BREAK_EVEN_WIN", f"سیگنال پس از تاچ تارگت (+{sig['max_profit']:.1f}$)، در نقطه ورود سر‌به‌سر بسته شد.", current_price)

        # ۳. لمس استاپ‌لاس اصلی (فقط در صورتی که تارگت نزده باشد):
        if sl and not sig.get("is_win") and not sig.get("target_hit"):
            is_stopped = (direction == "BUY" and current_price <= sl) or (direction == "SELL" and current_price >= sl)
            if is_stopped:
                return self.close_trade("LOSS", f"قیمت طلا به {current_price:.2f} رسید و حد ضرر ({sl}) لمس شد.", current_price)

        # ۴. ورود به محدوده
        if not sig["entered_zone_alerted"] and (e_min <= current_price <= e_max):
            sig["entered_zone_alerted"] = True
            self._save_active_signal()
            return (
                f"🎯 <b>سیگنال #{sig_num}: طلا وارد زون ورود شد!</b>\n\n"
                f"جهت: <b>{direction}</b> | قیمت: <code>${current_price:.2f}</code>\n"
                f"محدوده ورود: <code>{sig['entry_raw']}</code>\n"
                f"⚡️ اکنون پوزیشن با ${budget:.2f} آماده است."
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

        wins = sum(1 for t in today_trades if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN"])
        losses = sum(1 for t in today_trades if t.get("outcome") == "LOSS")
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        total_pnl = sum(t.get("realized_pnl_usd", 0.0) for t in today_trades)
        total_pips = sum(int(t.get("max_profit", 0.0) * 10) for t in today_trades if t.get("outcome") in ["WIN", "BREAK_EVEN_WIN"])

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
