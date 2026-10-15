import re
from typing import Optional, Any

class ParsedResult(tuple):
    """
    شیء خروجی پارسر که هم به عنوان یک تاپل ۴ تایی رفتار می‌کند:
        (category, title, formatted_html, should_alert)
    و هم ویژگی‌های ساختاریافته (direction, entry_raw, entry_price, stop_loss, tp1_price, ...) را در خود دارد.
    """
    def __new__(cls, category: str, title: str, formatted_html: str, should_alert: bool, **kwargs):
        obj = super().__new__(cls, (category, title, formatted_html, should_alert))
        obj.category = category
        obj.title = title
        obj.formatted_html = formatted_html
        obj.should_alert = should_alert
        obj.direction = kwargs.get("direction")
        obj.entry_raw = kwargs.get("entry_raw")
        obj.entry_price = kwargs.get("entry_price")
        obj.entry_min = kwargs.get("entry_min")
        obj.entry_max = kwargs.get("entry_max")
        obj.stop_loss = kwargs.get("stop_loss")
        obj.sl_pips = kwargs.get("sl_pips")
        obj.tp1_price = kwargs.get("tp1_price")
        obj.tp1_pips = kwargs.get("tp1_pips")
        obj.tp2_price = kwargs.get("tp2_price")
        obj.tp2_pips = kwargs.get("tp2_pips")
        obj.extra = kwargs
        return obj


def parse_lordxau_message(text: str) -> Optional[ParsedResult]:
    """
    پیام‌های کانال @lordxau را تحلیل و دسته‌بندی می‌کند.
    پشتیبانی هم‌زمان از فرمت‌های کلاسیک (Xau Buy Enter:4168/4167)
    و فرمت جدید:
        GOLD sell / buy
        4146 - 4151
        Tp60pip - 100pip
        Sl___90pip
    خروجی:
        ParsedResult (سازگار با تاپل ۴ تایی): (category, title, formatted_html, should_alert) یا None
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()
    lower = cleaned.lower()

    # فیلتر پیام‌های تبلیغاتی، بازخوردها و نویز کانال
    noise_keywords = [
        "الترا", "عضوگیری", "میلیون سود", "پشتیبانی", "خداروشکر", 
        "به پول ایران", "حقوق کارگری", "ربات پشتیبانی", "@lordcrypto",
        "ترید خدمت کرد", "سرمایه شروع کردم", "استارت شغلی"
    ]
    if any(k in lower for k in noise_keywords):
        return None

    # ── ۱. سیگنال ورود به معامله (SIGNAL_ENTRY) ──
    # نماد طلا: XAU, XAUUSD, GOLD, طلا
    has_gold_symbol = bool(re.search(r'\b(?:gold|xau|xauusd)\b|طلا', lower))

    # جهت معامله (BUY / SELL)
    gold_dir_match = re.search(r'\b(?:gold|xau|xauusd|طلا)\s*[-:\s]*\b(buy|sell|بای|سل)\b', lower)
    has_buy = bool(re.search(r'\b(?:buy|بای)\b', lower))
    has_sell = bool(re.search(r'\b(?:sell|سل)\b', lower))
    has_direction = bool(gold_dir_match) or has_buy or has_sell

    # محدوده ورود:
    # الف) با کلمه Enter یا ورود (مثل Enter:4168/4167 یا ورود: 4168 - 4167)
    enter_kw_match = re.search(r'(?:enter|ورود)\s*[:=]?\s*([0-9/\.\-\s]+)', lower)
    # ب) بدون کلمه Enter: دو عدد ۴ رقمی بین ۲۰۰۰ تا ۶۹۹۹ جدا شده با - یا / یا to (مثل 4146 - 4151)
    range_match = re.search(r'\b([2-6]\d{3}(?:\.\d+)?)\s*(?:[-/]|(?:\bto\b))\s*([2-6]\d{3}(?:\.\d+)?)\b', lower)

    # آیا پیام سیگنال ورود است؟
    is_entry = False
    if has_gold_symbol and has_direction and (enter_kw_match or range_match):
        is_entry = True
    elif (enter_kw_match or range_match) and (gold_dir_match or (has_gold_symbol and has_direction)):
        is_entry = True
    elif has_gold_symbol and has_direction and (re.search(r'(?i)\btp[_:\s-]*\d+', cleaned) or re.search(r'(?i)\bsl[_:\s-]*\d+', cleaned)):
        is_entry = True
    elif ("xau" in lower or "gold" in lower) and ("enter" in lower or "ورود" in lower):
        is_entry = True

    if is_entry:
        # تعیین جهت دقیق معامله
        if gold_dir_match:
            d_word = gold_dir_match.group(1).lower()
            direction_code = "BUY" if d_word in ["buy", "بای"] else "SELL"
        elif has_buy and not has_sell:
            direction_code = "BUY"
        elif has_sell and not has_buy:
            direction_code = "SELL"
        else:
            direction_code = "BUY" if ("buy" in lower or "بای" in lower) else "SELL"

        direction_badge = "🟢 BUY (خرید)" if direction_code == "BUY" else "🔴 SELL (فروش)"

        # استخراج محدوده ورود و میانگین قیمت
        entry_raw = ""
        entry_price = 0.0
        entry_min = 0.0
        entry_max = 0.0

        if range_match:
            n1 = float(range_match.group(1))
            n2 = float(range_match.group(2))
            entry_min, entry_max = min(n1, n2), max(n1, n2)
            entry_price = round((entry_min + entry_max) / 2.0, 2)
            entry_raw = f"{range_match.group(1)} - {range_match.group(2)}"
        elif enter_kw_match:
            raw_val = enter_kw_match.group(1).strip()
            nums = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', raw_val)]
            if len(nums) >= 2:
                entry_min, entry_max = min(nums[0], nums[1]), max(nums[0], nums[1])
                entry_price = round((entry_min + entry_max) / 2.0, 2)
                entry_raw = f"{nums[0]:g}/{nums[1]:g}"
            elif len(nums) == 1:
                entry_min = entry_max = entry_price = nums[0]
                entry_raw = f"{nums[0]:g}"
            else:
                entry_raw = raw_val

        # استخراج و محاسبه حد ضرر (Stop Loss)
        sl_price = None
        sl_pips = None

        # الف) استاپ پیپ‌محور: Sl___90pip یا SL: 90 pip یا Stop 90pips
        sl_pip_match = re.search(r'(?i)\b(?:sl|stop|استاپ)[_:\s-]*(\d+)\s*(?:pip|pips|پیپ)\b', cleaned)
        if sl_pip_match:
            sl_pips = float(sl_pip_match.group(1))
            sl_dollars = sl_pips / 10.0
            if entry_price > 0:
                if direction_code == "SELL":
                    sl_price = round(entry_price + sl_dollars, 2)
                else:
                    sl_price = round(entry_price - sl_dollars, 2)
        else:
            # ب) استاپ با قیمت طلا: Stop: 4165 یا SL 4165
            sl_price_match = re.search(r'(?i)\b(?:sl|stop|استاپ)[_:\s-]*([2-6]\d{3}(?:\.\d+)?)\b', cleaned)
            if sl_price_match:
                sl_price = float(sl_price_match.group(1))
                if entry_price > 0:
                    sl_pips = round(abs(sl_price - entry_price) * 10, 1)

        # استخراج و محاسبه تارگت‌ها (Take Profit)
        tp1_price = None
        tp1_pips = None
        tp2_price = None
        tp2_pips = None

        # بررسی وجود چند خط مجزای TP (مانند TP 4149 و خط بعد TP 4159) یا الگوی بازه‌ای (Tp60pip - 100pip)
        tp_range_match = re.search(r'(?i)\btp[_:\s-]*(\d+)\s*(?:pip|pips|پیپ)?\s*[-/]\s*(\d+)\s*(?:pip|pips|پیپ)?', cleaned)
        if tp_range_match:
            val1 = float(tp_range_match.group(1))
            val2 = float(tp_range_match.group(2))
        else:
            all_tp = re.findall(r'(?i)\btp[12]?[_:\s-]+([0-9\.]+)', cleaned)
            val1 = float(all_tp[0]) if len(all_tp) >= 1 else None
            val2 = float(all_tp[1]) if len(all_tp) >= 2 else None

        if val1 is not None:
            if val1 > 1000:
                tp1_price = val1
                if entry_price > 0:
                    tp1_pips = round(abs(tp1_price - entry_price) * 10, 1)
            else:
                tp1_pips = val1
                tp1_dollars = tp1_pips / 10.0
                if entry_price > 0:
                    tp1_price = round(entry_price - tp1_dollars, 2) if direction_code == "SELL" else round(entry_price + tp1_dollars, 2)

        if val2 is not None:
            if val2 > 1000:
                tp2_price = val2
                if entry_price > 0:
                    tp2_pips = round(abs(tp2_price - entry_price) * 10, 1)
            else:
                tp2_pips = val2
                tp2_dollars = tp2_pips / 10.0
                if entry_price > 0:
                    tp2_price = round(entry_price - tp2_dollars, 2) if direction_code == "SELL" else round(entry_price + tp2_dollars, 2)

        # ساخت پیام خروجی با فرمت HTML
        lines = [
            "⚡️ <b>سیگنال ورود جدید طلا (XAUUSD)</b> ⚡️\n",
            f"🔸 <b>جهت معامله:</b> {direction_badge}",
            f"🔸 <b>محدوده ورود:</b> <code>{entry_raw}</code>" + (f" (~{entry_price:.2f})" if entry_price > 0 else "")
        ]
        if tp1_price:
            t1_str = f"<code>{tp1_price:.2f}</code>" + (f" (+{int(tp1_pips)} پیپ)" if tp1_pips else "")
            lines.append(f"🎯 <b>تارگت اول:</b> {t1_str}")
        if tp2_price:
            t2_str = f"<code>{tp2_price:.2f}</code>" + (f" (+{int(tp2_pips)} پیپ)" if tp2_pips else "")
            lines.append(f"🎯 <b>تارگت دوم:</b> {t2_str}")
        if sl_price:
            sl_str = f"<code>{sl_price:.2f}</code>" + (f" ({int(sl_pips)} پیپ استاپ)" if sl_pips else "")
            lines.append(f"🛑 <b>حد ضرر:</b> {sl_str}")

        lines.append(f"\n📝 <b>متن اصلی سیگنال:</b>\n<code>{cleaned}</code>")
        msg = "\n".join(lines)

        return ParsedResult(
            "SIGNAL_ENTRY",
            f"سیگنال {direction_badge}",
            msg,
            True,
            direction=direction_code,
            entry_raw=entry_raw,
            entry_price=entry_price,
            entry_min=entry_min,
            entry_max=entry_max,
            stop_loss=sl_price,
            sl_pips=sl_pips,
            tp1_price=tp1_price,
            tp1_pips=tp1_pips,
            tp2_price=tp2_price,
            tp2_pips=tp2_pips
        )

    # ── ۲. تعیین حد ضرر جداگانه (مثال: Stop:4165 یا Sl___90pip) ──
    sl_alone_pip = re.search(r'(?i)\b(?:stop|استاپ|sl)[_:\s-]*(\d+)\s*(?:pip|pips|پیپ)\b', cleaned)
    sl_alone_price = re.search(r'(?i)\b(?:stop|استاپ|sl)[_:\s-]*([0-9\.]+)', cleaned)

    if sl_alone_pip:
        pips = float(sl_alone_pip.group(1))
        msg = (
            f"🛑 <b>حد ضرر معامله (Stop Loss)</b> 🛑\n\n"
            f"🔻 <b>استاپ لاس:</b> <code>{int(pips)} پیپ</code> ({pips/10:.1f}$ فاصله)\n\n"
            f"📝 <i>متن اصلی:</i> <code>{cleaned}</code>"
        )
        return ParsedResult("SIGNAL_STOP", "حد ضرر مشخص شد", msg, True, stop_loss=pips, sl_pips=pips)
    elif sl_alone_price:
        stop_val = sl_alone_price.group(1)
        msg = (
            f"🛑 <b>حد ضرر معامله (Stop Loss)</b> 🛑\n\n"
            f"🔻 <b>استاپ لاس:</b> <code>{stop_val}</code>\n\n"
            f"📝 <i>متن اصلی:</i> <code>{cleaned}</code>"
        )
        try:
            val_flt = float(stop_val)
        except ValueError:
            val_flt = None
        return ParsedResult("SIGNAL_STOP", "حد ضرر مشخص شد", msg, True, stop_loss=val_flt)

    # ── ۳. هشدارهای اقدام فوری (مثال: بای بزنید / سل بگیرید) ──
    if re.search(r'بای\s*(?:بزنید|بگیرید|کنید)', cleaned) or lower == "buy":
        msg = f"🟢 <b>هشدار خرید فوری (BUY)</b> 🟢\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("ACTION_BUY", "خرید فوری طلا", msg, True, direction="BUY")

    if re.search(r'سل\s*(?:بزنید|بگیرید|کنید)', cleaned) or lower == "sell":
        msg = f"🔴 <b>هشدار فروش فوری (SELL)</b> 🔴\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("ACTION_SELL", "فروش فوری طلا", msg, True, direction="SELL")

    if "اماده سیگنال" in cleaned or "آماده سیگنال" in cleaned:
        msg = f"⏳ <b>آماده‌باش برای دریافت سیگنال طلا</b> ⏳\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("ALERT_READY", "آماده‌باش سیگنال", msg, True)

    # ── ۴. مدیریت پوزیشن (ریسک‌فری / بستن معامله / استاپ تاچ) ──
    negative_command_keywords = [
        "نکن", "نکنید", "نکنین", 
        "نبند", "نبندید", "نبندین", 
        "فعلا نه", "فعلاً نه", "دست نزن", "دست نزنید"
    ]
    has_negation = any(k in cleaned for k in negative_command_keywords)

    if has_negation and any(k in cleaned for k in ["ببند", "کلوز", "فری", "خروج", "استاپ", "سل", "بای"]):
        return None

    words_count = len(cleaned.split())
    is_short_command = (words_count <= 5 and len(cleaned) <= 35)

    if is_short_command and not has_negation and re.search(r'(?:فری\s*(?:ش?\s*کن(?:ید)?|زد|شد|کنیم|بزنید)|ریسک\s*فری)', cleaned):
        msg = (
            f"🛡 <b>ریسک‌فری معامله (Risk Free)</b> 🛡\n\n"
            f"📌 حد ضرر (SL) فوراً به نقطه ورود منتقل و معامله ریسک‌فری شد.\n\n"
            f"📝 <i>متن ادمین:</i> <code>{cleaned}</code>"
        )
        return ParsedResult("ACTION_RISKFREE", "ریسک‌فری کنید", msg, True)

    if is_short_command and not has_negation and re.search(r'(?:ببند(?:ید)?|فول\s*کلوز|کامل\s*ببند(?:ید)?|خروج\s*کامل|سیو\s*سود\s*کامل|خروج\s*بزنید|ببندیم|کلوز\s*کنید)', cleaned):
        msg = (
            f"🚨 <b>دستور خروج و بستن معامله (Full Close)</b> 🚨\n\n"
            f"📌 معامله را فوراً در قیمت فعلی بازار ببندید.\n\n"
            f"📝 <i>متن ادمین:</i> <code>{cleaned}</code>"
        )
        return ParsedResult("ACTION_CLOSE", "بستن کامل معامله", msg, True)

    if "استاپ تاچ کرد" in cleaned or "استاپ خورد" in cleaned:
        msg = f"⚠️ <b>حد ضرر لمس شد (Stop Hit)</b> ⚠️\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("ACTION_STOP_HIT", "استاپ تاچ شد", msg, True)

    # ── ۵. قیمت لحظه‌ای / تارگت‌های خروج ──
    price_match = re.search(r'xau\s*[:=]\s*([0-9\.]+)', lower)
    if price_match:
        price_val = price_match.group(1)
        msg = f"📊 <b>گزارش قیمت طلا (XAUUSD)</b>\n\nقیمت اعلامی: <code>{price_val}</code>\n<i>متن:</i> <code>{cleaned}</code>"
        return ParsedResult("PRICE_UPDATE", "قیمت لحظه‌ای طلا", msg, True)

    target_match = re.search(r'تا\s*([0-9\.]+)\s*(?:میریزه|میره|میاد)', cleaned)
    if target_match:
        target_val = target_match.group(1)
        msg = f"🎯 <b>تارگت پیش‌بینی‌شده طلا</b>\n\nتارگت: <code>{target_val}</code>\n<i>متن:</i> <code>{cleaned}</code>"
        return ParsedResult("TARGET_UPDATE", "تارگت اعلام شد", msg, True)

    # ── ۶. پیام‌های تکمیلی مدیریت معامله ──
    if any(k in cleaned for k in ["فری خورد", "مدیریت بکنید", "تی پی", "برگشت ورود", "برگشت به ورود", "فری شد"]):
        msg = f"ℹ️ <b>دستور مدیریتی معامله</b>\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("MANAGEMENT_INFO", "مدیریت پوزیشن", msg, True)

    return None
