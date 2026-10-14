import re

def parse_lordxau_message(text: str):
    """
    پیام‌های کانال @lordxau را تحلیل و دسته‌بندی می‌کند.
    خروجی:
        tuple: (category, title, formatted_html, should_alert) یا None در صورت پیام اسپم/نامربوط
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

    # ۱. سیگنال ورود به معامله (مثال: Xau \n Buy \n Enter:4168/4167)
    if "xau" in lower and ("enter" in lower or "ورود" in lower):
        direction = "🟢 BUY (خرید)" if ("buy" in lower or "بای" in lower) else ("🔴 SELL (فروش)" if ("sell" in lower or "سل" in lower) else "🔔 معامله")
        enter_match = re.search(r'(?:enter|ورود)\s*[:=]?\s*([0-9/\.\-]+)', lower)
        enter_val = enter_match.group(1) if enter_match else "مشخص نشده"
        
        msg = (
            f"⚡️ <b>سیگنال ورود جدید طلا (XAUUSD)</b> ⚡️\n\n"
            f"🔸 <b>جهت معامله:</b> {direction}\n"
            f"🔸 <b>محدوده ورود:</b> <code>{enter_val}</code>\n\n"
            f"📝 <b>متن اصلی سیگنال:</b>\n<code>{cleaned}</code>"
        )
        return ("SIGNAL_ENTRY", f"سیگنال {direction}", msg, True)

    # ۲. تعیین حد ضرر (مثال: Stop:4165)
    stop_match = re.search(r'(?:stop|استاپ|sl)\s*[:=]?\s*([0-9\.]+)', lower)
    if stop_match:
        stop_val = stop_match.group(1)
        msg = (
            f"🛑 <b>حد ضرر معامله (Stop Loss)</b> 🛑\n\n"
            f"🔻 <b>استاپ لاس:</b> <code>{stop_val}</code>\n\n"
            f"📝 <i>متن اصلی:</i> <code>{cleaned}</code>"
        )
        return ("SIGNAL_STOP", "حد ضرر مشخص شد", msg, True)

    # ۳. هشدارهای اقدام فوری (مثال: بای بزنید / سل بگیرید)
    if re.search(r'بای\s*(?:بزنید|بگیرید|کنید)', cleaned) or lower == "buy":
        msg = f"🟢 <b>هشدار خرید فوری (BUY)</b> 🟢\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ("ACTION_BUY", "خرید فوری طلا", msg, True)

    if re.search(r'سل\s*(?:بزنید|بگیرید|کنید)', cleaned) or lower == "sell":
        msg = f"🔴 <b>هشدار فروش فوری (SELL)</b> 🔴\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ("ACTION_SELL", "فروش فوری طلا", msg, True)

    if "اماده سیگنال" in cleaned or "آماده سیگنال" in cleaned:
        msg = f"⏳ <b>آماده‌باش برای دریافت سیگنال طلا</b> ⏳\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ("ALERT_READY", "آماده‌باش سیگنال", msg, True)

    # ۴. مدیریت پوزیشن (ریسک‌فری / بستن معامله / استاپ تاچ)
    # دستور فری کن / ریسک فری
    if re.search(r'(?:فری\s*(?:ش?\s*کن(?:ید)?|زد|شد|کنیم|بزنید)|ریسک\s*فری)', cleaned):
        msg = (
            f"🛡 <b>ریسک‌فری معامله (Risk Free)</b> 🛡\n\n"
            f"📌 حد ضرر (SL) فوراً به نقطه ورود منتقل و معامله ریسک‌فری شد.\n\n"
            f"📝 <i>متن ادمین:</i> <code>{cleaned}</code>"
        )
        return ("ACTION_RISKFREE", "ریسک‌فری کنید", msg, True)

    # دستور ببند / فول کلوز
    if re.search(r'(?:ببند(?:ید)?|فول\s*کلوز|کامل\s*ببند(?:ید)?|خروج\s*کامل|سیو\s*سود\s*کامل|خروج\s*بزنید|ببندیم|کلوز\s*کنید)', cleaned):
        msg = (
            f"🚨 <b>دستور خروج و بستن معامله (Full Close)</b> 🚨\n\n"
            f"📌 معامله را فوراً در قیمت فعلی بازار ببندید.\n\n"
            f"📝 <i>متن ادمین:</i> <code>{cleaned}</code>"
        )
        return ("ACTION_CLOSE", "بستن کامل معامله", msg, True)

    if "استاپ تاچ کرد" in cleaned or "استاپ خورد" in cleaned:
        msg = f"⚠️ <b>حد ضرر لمس شد (Stop Hit)</b> ⚠️\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ("ACTION_STOP_HIT", "استاپ تاچ شد", msg, True)

    # ۵. قیمت لحظه‌ای / تارگت‌های خروج
    price_match = re.search(r'xau\s*[:=]\s*([0-9\.]+)', lower)
    if price_match:
        price_val = price_match.group(1)
        msg = f"📊 <b>گزارش قیمت طلا (XAUUSD)</b>\n\nقیمت اعلامی: <code>{price_val}</code>\n<i>متن:</i> <code>{cleaned}</code>"
        return ("PRICE_UPDATE", "قیمت لحظه‌ای طلا", msg, True)

    target_match = re.search(r'تا\s*([0-9\.]+)\s*(?:میریزه|میره|میاد)', cleaned)
    if target_match:
        target_val = target_match.group(1)
        msg = f"🎯 <b>تارگت پیش‌بینی‌شده طلا</b>\n\nتارگت: <code>{target_val}</code>\n<i>متن:</i> <code>{cleaned}</code>"
        return ("TARGET_UPDATE", "تارگت اعلام شد", msg, True)

    # ۶. پیام‌های تکمیلی مدیریت معامله
    if any(k in cleaned for k in ["فری خورد", "مدیریت بکنید", "تی پی", "برگشت ورود", "برگشت به ورود", "فری شد"]):
        msg = f"ℹ️ <b>دستور مدیریتی معامله</b>\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ("MANAGEMENT_INFO", "مدیریت پوزیشن", msg, True)

    # سایر پیام‌ها (اسپم یا گپ متفرقه) نادیده گرفته می‌شوند
    return None
