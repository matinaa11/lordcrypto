import re
from typing import Optional, Any, List

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
        obj.symbol = kwargs.get("symbol", "XAUUSD")
        obj.market_type = kwargs.get("market_type", "GOLD") # "GOLD" یا "CRYPTO"
        obj.direction = kwargs.get("direction")
        obj.entry_raw = kwargs.get("entry_raw")
        obj.entry_price = kwargs.get("entry_price")
        obj.entry_min = kwargs.get("entry_min")
        obj.entry_max = kwargs.get("entry_max")
        obj.stop_loss = kwargs.get("stop_loss")
        obj.sl_pips = kwargs.get("sl_pips")
        obj.leverage = kwargs.get("leverage")
        obj.targets = kwargs.get("targets", [])
        obj.tp_percentages = kwargs.get("tp_percentages", [])
        obj.tp1_price = kwargs.get("tp1_price")
        obj.tp1_pips = kwargs.get("tp1_pips")
        obj.tp2_price = kwargs.get("tp2_price")
        obj.tp2_pips = kwargs.get("tp2_pips")
        obj.risk_percent = kwargs.get("risk_percent")
        obj.channel_title = kwargs.get("channel_title", "")
        obj.channel_username = kwargs.get("channel_username", "")
        obj.extra = kwargs
        return obj


def parse_channel_message(text: str, channel_title: str = "", channel_name: str = "") -> Optional[ParsedResult]:
    """
    تحلیل پیام‌های کانال‌های طلا و کریپتو (شامل @lordxau و @lordcryptovip و سایر کانال‌ها)
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()
    lower = cleaned.lower()

    # فیلتر پیام‌های تبلیغاتی و بازخوردها
    noise_keywords = [
        "الترا", "عضوگیری", "میلیون سود", "پشتیبانی", "خداروشکر", 
        "به پول ایران", "حقوق کارگری", "ربات پشتیبانی", "@lordcrypto",
        "ترید خدمت کرد", "سرمایه شروع کردم", "استارت شغلی", "وی آی پی سیگنال هارو قرار میدیم"
    ]
    if any(k in lower for k in noise_keywords):
        return None

    channel_header = f"📢 <b>کانال:</b> {channel_title}\n\n" if channel_title else ""

    # ════════════════════ ۱. سیگنال ورود به معامله طلا (XAUT / GOLD) ════════════════════
    has_gold_symbol = bool(re.search(r'\b(?:gold|xau|xauusd|xaut|xautusdt)\b|طلا', lower))
    gold_dir_match = re.search(r'\b(?:gold|xau|xauusd|xaut|xautusdt|طلا)\s*[-:\s]*\b(buy|sell|بای|سل)\b', lower)
    has_buy = bool(re.search(r'\b(?:buy|بای)\b', lower))
    has_sell = bool(re.search(r'\b(?:sell|سل)\b', lower))
    has_gold_direction = bool(gold_dir_match) or has_buy or has_sell

    enter_kw_match = re.search(r'(?:enter|ورود)\s*[:=]?\s*([0-9/\.\-\s]+)', lower)
    range_match = re.search(r'\b([2-6]\d{3}(?:\.\d+)?)\s*(?:[-/]|(?:\bto\b))\s*([2-6]\d{3}(?:\.\d+)?)\b', lower)

    is_gold_entry = False
    if has_gold_symbol and has_gold_direction and (enter_kw_match or range_match):
        is_gold_entry = True
    elif (enter_kw_match or range_match) and (gold_dir_match or (has_gold_symbol and has_gold_direction)):
        is_gold_entry = True
    elif has_gold_symbol and has_gold_direction and (re.search(r'(?i)\btp[_:\s-]*\d+', cleaned) or re.search(r'(?i)\bsl[_:\s-]*\d+', cleaned)):
        is_gold_entry = True
    elif ("xau" in lower or "gold" in lower or "xaut" in lower) and ("enter" in lower or "ورود" in lower):
        is_gold_entry = True

    if is_gold_entry:
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

        sl_price = None
        sl_pips = None
        sl_match = re.search(r'(?i)\b(?:sl|stop|استاپ)[_:\s-]*(\d+(?:\.\d+)?)\s*(?:pip|pips|پیپ)?\b', cleaned)
        if sl_match:
            val = float(sl_match.group(1))
            if val < 500:
                sl_pips = val
                sl_dollars = sl_pips / 10.0
                if entry_price > 0:
                    sl_price = round(entry_price + sl_dollars, 2) if direction_code == "SELL" else round(entry_price - sl_dollars, 2)
            else:
                sl_price = val
                if entry_price > 0:
                    sl_pips = round(abs(sl_price - entry_price) * 10, 1)

        tp1_price = None
        tp1_pips = None
        tp2_price = None
        tp2_pips = None

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

        lines = [
            f"{channel_header}⚡️ <b>سیگنال ورود جدید طلا (TradingView)</b> ⚡️\n",
            f"🔸 <b>جهت معامله:</b> {direction_badge}",
            f"🔸 <b>نماد:</b> <code>XAU/USD (TradingView)</code>",
            f"🪙 <b>قرارداد معادل Ourbit:</b> <code>GOLD(XAUT)USDT</code>",
            f"🔸 <b>محدوده ورود:</b> <code>{entry_raw}</code>" + (f" (~{entry_price:.2f})" if entry_price > 0 else "")
        ]
        if tp1_price:
            lines.append(f"🎯 <b>تارگت اول:</b> <code>{tp1_price:.2f}</code>" + (f" (+{int(tp1_pips)} پیپ)" if tp1_pips else ""))
        else:
            lines.append("🎯 <b>تارگت اول:</b> <code>طبق تنظیمات ربات</code>")

        if tp2_price:
            lines.append(f"🎯 <b>تارگت دوم:</b> <code>{tp2_price:.2f}</code>" + (f" (+{int(tp2_pips)} پیپ)" if tp2_pips else ""))

        if sl_price:
            lines.append(f"🛑 <b>حد ضرر:</b> <code>{sl_price:.2f}</code>" + (f" ({int(sl_pips)} پیپ استاپ)" if sl_pips else ""))
        else:
            lines.append("🛑 <b>حد ضرر:</b> <code>طبق تنظیمات ربات</code>")

        lines.append(f"\n📝 <b>متن اصلی سیگنال:</b>\n<code>{cleaned}</code>")
        msg = "\n".join(lines)

        return ParsedResult(
            "SIGNAL_ENTRY",
            f"سیگنال طلا {direction_badge}",
            msg,
            True,
            symbol="XAUUSD",
            market_type="GOLD",
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
            tp2_pips=tp2_pips,
            channel_title=channel_title,
            channel_username=channel_name
        )

    # ════════════════════ ۲. سیگنال ورود به معامله کریپتو (CRYPTO FUTURES) ════════════════════
    # الگوهای کوین و جهت: مانند DUSK SHORT یا ALLO LONG یا BTCUSDT Long
    crypto_dir_match = re.search(r'(?i)(?:🟠|🟢|🔴|🔵|✨|#|\b)([A-Z0-9]{2,10})\s*(?:/\s*USDT|\s*USDT)?\s*(SHORT|LONG|BUY|SELL|شورت|لانگ)\b', cleaned)
    crypto_pair_match = re.search(r'(?i)#?([A-Z0-9]{2,10})USDT\s*(?:[-:\s]*(LONG|SHORT|BUY|SELL|شورت|لانگ))?', cleaned)

    is_crypto_candidate = False
    crypto_coin = ""
    crypto_dir = ""

    if crypto_dir_match:
        matched_coin = crypto_dir_match.group(1).upper()
        if matched_coin not in ["GOLD", "XAU", "TP", "SL", "LV"]:
            is_crypto_candidate = True
            crypto_coin = matched_coin
            d_str = crypto_dir_match.group(2).upper()
            crypto_dir = "BUY" if d_str in ["LONG", "BUY", "لانگ"] else "SELL"
    elif crypto_pair_match and (re.search(r'(?i)\btp\b', cleaned) or re.search(r'(?i)\bsl\b', cleaned)):
        matched_coin = crypto_pair_match.group(1).upper()
        if matched_coin not in ["GOLD", "XAU"]:
            is_crypto_candidate = True
            crypto_coin = matched_coin
            d_str = (crypto_pair_match.group(2) or "").upper()
            crypto_dir = "BUY" if d_str in ["LONG", "BUY", "لانگ"] else "SELL"

    # استخراج حد ضرر
    c_sl_m = re.search(r'(?i)(?:sl|stop|استاپ)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)', cleaned)
    crypto_sl = float(c_sl_m.group(1)) if c_sl_m else None

    # قانون کلیدی: فقط پیامی که حد ضرر (SL) و (نحوه ورود یا تارگت) داشته باشد به عنوان باز کردن سیگنال ورود پردازش می‌شود.
    has_market_or_tp = bool(re.search(r'(?i)\b(?:market|entry|ورود|tp|تارگت)\b', cleaned))
    is_full_crypto_signal = is_crypto_candidate and (crypto_sl is not None) and has_market_or_tp

    if is_full_crypto_signal:
        base_coin = crypto_coin[:-4] if crypto_coin.endswith("USDT") else crypto_coin
        dir_badge = "🟢 LONG (خرید)" if crypto_dir == "BUY" else "🔴 SHORT (فروش)"
        symbol_pair = f"{base_coin}USDT"

        # نحوه ورود (Market یا قیمت)
        entry_raw = "MARKET" if "market" in lower else ""
        if not entry_raw:
            c_entry_m = re.search(r'(?i)(?:entry|ورود)\s*[:=]?\s*([0-9\.\-\s/]+)', cleaned)
            entry_raw = c_entry_m.group(1).strip() if c_entry_m else "MARKET"

        # اهرم معامله (در صورت نبودن، پیش‌فرض ۲۰ طبق درخواست کاربر)
        lev_m = re.search(r'(?i)(?:lv|leverage|لورج|اهرم)\s*[:=]?\s*(\d+)', cleaned)
        leverage_val = int(lev_m.group(1)) if lev_m else 20

        # استخراج درصدهای اسپات تارگت‌ها (مانند 1%spot, 4%spot, 7%spot)
        tp_spot_matches = re.findall(r'(?i)tp\s*\d*\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%\s*(?:spot)?', cleaned)
        if tp_spot_matches:
            tp_percentages = [float(x) for x in tp_spot_matches]
        else:
            tp_percentages = [1.0, 4.0, 7.0]

        crypto_tps_raw = re.findall(r'(?i)(?:tp\s*\d*|تارگت\s*\d*)\s*[:=]?\s*([^\n]+)', cleaned)

        # درصد ریسک کیف پول (پیش‌فرض ۵ درصد)
        risk_m = re.search(r'(?i)(?:risk|ریسک)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%', cleaned)
        risk_percent = float(risk_m.group(1)) if risk_m else 5.0
        risk_val = f"{risk_percent:g}% wallet"

        lines = [
            f"{channel_header}⚡️ <b>سیگنال ورود جدید کریپتو ({symbol_pair})</b> ⚡️\n",
            f"🔸 <b>ارز دیجیتال:</b> <code>{base_coin} / USDT</code>",
            f"🔸 <b>جهت پوزیشن:</b> {dir_badge}",
            f"🔹 <b>نحوه ورود:</b> <code>{entry_raw}</code>",
            f"⚡️ <b>اهرم پیشنهادی:</b> <code>{leverage_val}x</code>"
        ]
        if crypto_tps_raw:
            tp_str = " | ".join([f"TP{i+1}: {t.strip()}" for i, t in enumerate(crypto_tps_raw[:4])])
            lines.append(f"🎯 <b>تارگت‌ها:</b> <code>{tp_str}</code>")
        elif tp_percentages:
            tp_str = " | ".join([f"TP{i+1}: {p:g}% Spot" for i, p in enumerate(tp_percentages[:3])])
            lines.append(f"🎯 <b>تارگت‌ها:</b> <code>{tp_str}</code>")

        lines.append(f"🛑 <b>حد ضرر (SL):</b> <code>{crypto_sl}</code>")
        lines.append(f"💰 <b>مدیریت ریسک:</b> <code>{risk_val}</code>")
        lines.append(f"\n📝 <b>متن اصلی سیگنال:</b>\n<code>{cleaned}</code>")
        msg = "\n".join(lines)

        return ParsedResult(
            "SIGNAL_ENTRY",
            f"سیگنال {base_coin} {dir_badge}",
            msg,
            True,
            symbol=symbol_pair,
            market_type="CRYPTO",
            direction=crypto_dir,
            entry_raw=entry_raw,
            stop_loss=crypto_sl,
            leverage=leverage_val,
            tp_percentages=tp_percentages,
            targets=crypto_tps_raw,
            risk_percent=risk_percent,
            channel_title=channel_title,
            channel_username=channel_name
        )

    # ════════════════════ ۳. هشدارهای اقدام سریع (مانند ALLO لانگ کنید / DUSK شورت کنید) ════════════════════
    quick_m = re.search(r'(?i)\b([A-Z0-9]{2,10})\b[^\n]*\n*.*?(لانگ|شورت|خرید|فروش)\s*کنید', cleaned)
    quick_coin = None
    quick_dir = None

    if quick_m and quick_m.group(1).upper() not in ["GOLD", "XAU"]:
        quick_coin = quick_m.group(1).upper()
        quick_dir = "BUY" if quick_m.group(2) in ["لانگ", "خرید"] else "SELL"
    elif is_crypto_candidate and not is_full_crypto_signal:
        quick_coin = crypto_coin
        quick_dir = crypto_dir

    if quick_coin:
        base_quick = quick_coin[:-4] if quick_coin.endswith("USDT") else quick_coin
        lev_m = re.search(r'(?:لورج|اهرم|lv)\s*[:=]?\s*(\d+)', cleaned, re.I)
        lev = int(lev_m.group(1)) if lev_m else 20
        dir_badge = "🟢 خرید (LONG)" if quick_dir == "BUY" else "🔴 فروش (SHORT)"
        lev_note = f" (اهرم: <code>{lev}x</code>)"

        msg = (
            f"{channel_header}⚡️ <b>هشدار اقدام فوری و آماده‌باش ({base_quick}/USDT)</b> ⚡️\n\n"
            f"🔸 <b>جهت:</b> {dir_badge}{lev_note}\n"
            f"⏳ <i>سیگنال کامل با حد ضرر و تارگت‌ها به زودی ارسال می‌شود...</i>\n\n"
            f"📝 <i>متن ادمین:</i> <code>{cleaned}</code>"
        )
        return ParsedResult(
            "ACTION_QUICK_SIGNAL", 
            f"هشدار فوری {base_quick}", 
            msg, 
            True, 
            symbol=f"{base_quick}USDT", 
            market_type="CRYPTO",
            direction=quick_dir, 
            leverage=lev, 
            channel_title=channel_title,
            channel_username=channel_name
        )

    if re.search(r'بای\s*(?:بزنید|بگیرید|کنید)', cleaned) or lower == "buy":
        msg = f"{channel_header}🟢 <b>هشدار خرید فوری (BUY)</b> 🟢\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("ACTION_BUY", "خرید فوری طلا", msg, True, symbol="XAUUSD", direction="BUY", channel_title=channel_title)

    if re.search(r'سل\s*(?:بزنید|بگیرید|کنید)', cleaned) or lower == "sell":
        msg = f"{channel_header}🔴 <b>هشدار فروش فوری (SELL)</b> 🔴\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("ACTION_SELL", "فروش فوری طلا", msg, True, symbol="XAUUSD", direction="SELL", channel_title=channel_title)

    if "اماده سیگنال" in cleaned or "آماده سیگنال" in cleaned:
        msg = f"{channel_header}⏳ <b>آماده‌باش برای دریافت سیگنال</b> ⏳\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("ALERT_READY", "آماده‌باش سیگنال", msg, True, channel_title=channel_title)

    # ════════════════════ ۴. مدیریت پوزیشن و دستورات ادمین ════════════════════
    negative_command_keywords = [
        "نکن", "نکنید", "نکنین", 
        "نبند", "نبندید", "نبندین", 
        "فعلا نه", "فعلاً نه", "دست نزن", "دست نزنید"
    ]
    has_negation = any(k in cleaned for k in negative_command_keywords)
    if has_negation and any(k in cleaned for k in ["ببند", "کلوز", "فری", "خروج", "استاپ", "سل", "بای"]):
        return None

    words_count = len(cleaned.split())
    is_short_command = (words_count <= 8 and len(cleaned) <= 60)

    # ریسک‌فری
    if is_short_command and not has_negation and re.search(r'(?:فری\s*(?:ش?\s*کن(?:ید)?|زد|شد|کنیم|بزنید)|ریسک\s*فری)', cleaned):
        msg = (
            f"{channel_header}🛡 <b>دستور ریسک‌فری (Risk Free)</b> 🛡\n\n"
            f"📌 استاپ‌لاس فوراً به نقطه ورود منتقل شد تا معامله بدون ریسک ادامه یابد.\n\n"
            f"📝 <i>متن ادمین:</i> <code>{cleaned}</code>"
        )
        return ParsedResult("ACTION_RISKFREE", "ریسک‌فری کنید", msg, True, channel_title=channel_title)

    # خروج و کلوز کامل
    if is_short_command and not has_negation and re.search(r'(?:خارج\s*شید|خارج\s*بشید|ببند(?:ید)?|فول\s*کلوز|کامل\s*ببند(?:ید)?|خروج\s*کامل|سیو\s*سود\s*کامل|خروج\s*بزنید|ببندیم|کلوز\s*کنید)', cleaned):
        msg = (
            f"{channel_header}🚨 <b>دستور خروج و بستن کامل معامله (Close)</b> 🚨\n\n"
            f"📌 معامله را فوراً در قیمت فعلی بازار ببندید.\n\n"
            f"📝 <i>متن ادمین:</i> <code>{cleaned}</code>"
        )
        return ParsedResult("ACTION_CLOSE", "بستن کامل معامله", msg, True, channel_title=channel_title)

    # تحقق تارگت‌ها (Target Hit)
    if is_short_command and not has_negation and re.search(r'(?:تارگت\s*(?:اول|دوم|سوم|چهارم)?\s*(?:داد|زد|تاچ|شد)?|فول\s*تارگت)', cleaned):
        msg = (
            f"{channel_header}🎯 <b>اعلام تحقق تارگت توسط ادمین</b> 🎯\n\n"
            f"📝 <i>متن ادمین:</i> <code>{cleaned}</code>"
        )
        return ParsedResult("ACTION_TARGET_HIT", "تارگت محقق شد", msg, True, channel_title=channel_title)

    # استاپ تاچ شد
    if "استاپ تاچ کرد" in cleaned or "استاپ خورد" in cleaned:
        msg = f"{channel_header}⚠️ <b>حد ضرر لمس شد (Stop Hit)</b> ⚠️\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("ACTION_STOP_HIT", "استاپ تاچ شد", msg, True, channel_title=channel_title)

    # ════════════════════ ۵. تعیین حد ضرر جداگانه ════════════════════
    sl_alone_match = re.search(r'(?i)\b(?:stop|استاپ|sl)[_:\s-]*(\d+(?:\.\d+)?)\s*(?:pip|pips|پیپ)?\b', cleaned)
    if sl_alone_match:
        val = float(sl_alone_match.group(1))
        if val < 500:
            msg = (
                f"{channel_header}🛑 <b>حد ضرر معامله (Stop Loss)</b> 🛑\n\n"
                f"🔻 <b>استاپ لاس:</b> <code>{int(val)} پیپ</code> ({val/10:.1f}$ فاصله)\n\n"
                f"📝 <i>متن اصلی:</i> <code>{cleaned}</code>"
            )
            return ParsedResult("SIGNAL_STOP", "حد ضرر مشخص شد", msg, True, stop_loss=val, sl_pips=val, channel_title=channel_title)
        else:
            msg = (
                f"{channel_header}🛑 <b>حد ضرر معامله (Stop Loss)</b> 🛑\n\n"
                f"🔻 <b>استاپ لاس:</b> <code>{val:g}</code>\n\n"
                f"📝 <i>متن اصلی:</i> <code>{cleaned}</code>"
            )
            return ParsedResult("SIGNAL_STOP", "حد ضرر مشخص شد", msg, True, stop_loss=val, channel_title=channel_title)

    # ════════════════════ ۶. قیمت لحظه‌ای / تارگت‌های خروج ════════════════════
    price_match = re.search(r'(?:xau|xaut)\s*[:=]\s*([0-9\.]+)', lower)
    if price_match:
        price_val = price_match.group(1)
        msg = f"{channel_header}📊 <b>گزارش قیمت طلا (TradingView)</b>\n\nقیمت اعلامی: <code>{price_val}</code>\n<i>متن:</i> <code>{cleaned}</code>"
        return ParsedResult("PRICE_UPDATE", "قیمت لحظه‌ای طلا", msg, True, symbol="XAUUSD", channel_title=channel_title)

    target_match = re.search(r'تا\s*([0-9\.]+)\s*(?:میریزه|میره|میاد)', cleaned)
    if target_match:
        target_val = target_match.group(1)
        msg = f"{channel_header}🎯 <b>تارگت پیش‌بینی‌شده طلا</b>\n\nتارگت: <code>{target_val}</code>\n<i>متن:</i> <code>{cleaned}</code>"
        return ParsedResult("TARGET_UPDATE", "تارگت اعلام شد", msg, True, symbol="XAUUSD", channel_title=channel_title)

    # ════════════════════ ۷. پیام‌های تکمیلی مدیریت معامله ════════════════════
    if any(k in cleaned for k in ["فری خورد", "مدیریت بکنید", "تی پی", "برگشت ورود", "برگشت به ورود", "فری شد"]):
        msg = f"{channel_header}ℹ️ <b>دستور مدیریتی معامله</b>\n\n<i>متن ادمین:</i> <code>{cleaned}</code>"
        return ParsedResult("MANAGEMENT_INFO", "مدیریت پوزیشن", msg, True, channel_title=channel_title)

    return None

# نام مستعار برای سازگاری ۱۰۰٪ با کدهای قبلی
parse_lordxau_message = lambda text: parse_channel_message(text, channel_title="LORD XAU (TradingView)", channel_name="lordxau")
