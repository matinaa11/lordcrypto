import os
import sys
import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
import aiohttp
from dotenv import load_dotenv

from parser import parse_lordxau_message
from notifier import (
    send_telegram_alert, 
    answer_callback_query, 
    edit_message_reply_markup
)
from gold_tracker import gold_tracker
from evaluator import evaluator
from channel_listener import WebChannelListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("LordGoldBot")

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
USER_CHAT_ID = os.getenv("USER_CHAT_ID")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "lordxau").strip()
DEFAULT_BUDGET = float(os.getenv("TRADE_BUDGET_USD", "2.0"))

evaluator.set_budget(DEFAULT_BUDGET)

def check_env():
    missing = []
    if not BOT_TOKEN: missing.append("BOT_TOKEN")
    if not USER_CHAT_ID: missing.append("USER_CHAT_ID")

    if missing:
        logger.error(f"❌ متغیرهای ضروری تنظیم نشده‌اند: {', '.join(missing)}")
        logger.error("تنها به BOT_TOKEN و USER_CHAT_ID نیاز دارید.")
        sys.exit(1)

# ==================== دکمه‌های شیشه‌ای تلگرام ====================

def get_main_menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "💵 قیمت زنده طلا", "callback_data": "check_price"},
                {"text": "📊 کارنامه و آمار کل", "callback_data": "check_stats"}
            ],
            [
                {"text": "💰 تغییر سرمایه معامله", "callback_data": "menu_budget"},
                {"text": "🌙 گزارش عملکرد امروز", "callback_data": "today_digest"}
            ]
        ]
    }

def get_budget_selection_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "1$", "callback_data": "set_budget_1"},
                {"text": "2$", "callback_data": "set_budget_2"},
                {"text": "5$", "callback_data": "set_budget_5"},
                {"text": "10$", "callback_data": "set_budget_10"}
            ],
            [
                {"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}
            ]
        ]
    }

def get_signal_action_keyboard(sig_num: int):
    return {
        "inline_keyboard": [
            [
                {"text": "✅ وارد این معامله شدم", "callback_data": f"enter_trade_{sig_num}"},
                {"text": "⏭ این معامله را نگرفتم", "callback_data": f"skip_trade_{sig_num}"}
            ]
        ]
    }

def get_signal_confirmed_keyboard(sig_num: int, entered: bool):
    text = f"✅ معامله #{sig_num} در کارنامه شما ثبت شد" if entered else f"⏭ معامله #{sig_num} رد شد"
    return {
        "inline_keyboard": [
            [
                {"text": text, "callback_data": "noop"}
            ]
        ]
    }

# ==================== پردازش دستورات و کلیک‌های کاربر ====================

async def bot_command_listener():
    logger.info("🤖 شنونده دستورات تلگرامی کاربر فعال شد...")
    offset = 0
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                params = {"offset": offset, "timeout": 15}
                async with session.get(url, params=params, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1

                            # ۱. کلیک روی دکمه‌های شیشه‌ای
                            callback = update.get("callback_query")
                            if callback:
                                cb_id = callback["id"]
                                cb_data = callback.get("data", "")
                                sender_id = str(callback.get("from", {}).get("id"))
                                msg_id = callback.get("message", {}).get("message_id")

                                if sender_id != str(USER_CHAT_ID):
                                    await answer_callback_query(BOT_TOKEN, cb_id, "دسترسی غیرمجاز")
                                    continue

                                if cb_data == "noop":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    continue

                                elif cb_data == "check_price":
                                    price = gold_tracker.get_price()
                                    p_str = f"${price:.2f}" if price else "در حال دریافت..."
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"قیمت طلا: {p_str}", show_alert=True)

                                elif cb_data == "check_stats":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    stats = evaluator.get_stats_summary()
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"📊 <b>کارنامه کلی سیگنال‌ها:</b>\n\n{stats}", 
                                        reply_markup=get_main_menu_keyboard()
                                    )

                                elif cb_data == "today_digest":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    digest = evaluator.get_daily_summary()
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        digest, 
                                        reply_markup=get_main_menu_keyboard()
                                    )

                                elif cb_data == "menu_budget":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"💰 <b>سرمایه فعلی هر معامله: ${evaluator.trade_budget:.2f}</b>\n\nمبلغ جدید را انتخاب کنید:",
                                        reply_markup=get_budget_selection_keyboard()
                                    )

                                elif cb_data.startswith("set_budget_"):
                                    amount = float(cb_data.replace("set_budget_", ""))
                                    res = evaluator.set_budget(amount)
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"سرمایه به ${amount:.2f} تغییر یافت")
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"{res}\n\nاز این پس تمام سودها با سرمایه <b>${amount:.2f}</b> محاسبه می‌شوند.",
                                        reply_markup=get_main_menu_keyboard()
                                    )

                                elif cb_data == "main_menu":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        "منوی اصلی کنترل ربات:", 
                                        reply_markup=get_main_menu_keyboard()
                                    )

                                elif cb_data.startswith("enter_trade_"):
                                    sig_n = int(cb_data.replace("enter_trade_", ""))
                                    evaluator.mark_user_participation(sig_n, True)
                                    await answer_callback_query(BOT_TOKEN, cb_id, "ورود شما ثبت شد ✅")
                                    if msg_id:
                                        await edit_message_reply_markup(
                                            BOT_TOKEN, USER_CHAT_ID, msg_id, 
                                            get_signal_confirmed_keyboard(sig_n, True)
                                        )

                                elif cb_data.startswith("skip_trade_"):
                                    sig_n = int(cb_data.replace("skip_trade_", ""))
                                    evaluator.mark_user_participation(sig_n, False)
                                    await answer_callback_query(BOT_TOKEN, cb_id, "معامله رد شد ⏭")
                                    if msg_id:
                                        await edit_message_reply_markup(
                                            BOT_TOKEN, USER_CHAT_ID, msg_id, 
                                            get_signal_confirmed_keyboard(sig_n, False)
                                        )

                            # ۲. دستورات متنی
                            msg = update.get("message")
                            if msg:
                                sender_id = str(msg.get("chat", {}).get("id"))
                                if sender_id != str(USER_CHAT_ID):
                                    continue

                                text = msg.get("text", "").strip()
                                if not text:
                                    continue

                                budget_match = re.search(r'(?:/budget|بودجه|مبلغ|سرمایه)\s*([0-9\.]+)', text)
                                if budget_match:
                                    new_val = float(budget_match.group(1))
                                    res = evaluator.set_budget(new_val)
                                    reply = f"{res}\n\nمحاسبات به سرمایه <b>${new_val:.2f}</b> تغییر یافت."
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, reply, reply_markup=get_main_menu_keyboard())

                                elif text in ["/stats", "آمار", "کارنامه"]:
                                    stats = evaluator.get_stats_summary()
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"📊 <b>کارنامه معاملات:</b>\n\n{stats}", reply_markup=get_main_menu_keyboard())

                                elif text in ["/today", "گزارش امروز", "امروز"]:
                                    digest = evaluator.get_daily_summary()
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, digest, reply_markup=get_main_menu_keyboard())

                                elif text in ["/start", "/help", "منو", "راهنما"]:
                                    guide = (
                                        f"👋 <b>کنترل پنل هوشمند رصد سیگنال طلا</b>\n\n"
                                        f"💵 <b>سرمایه تنظیمی فعلی شما:</b> <code>${evaluator.trade_budget:.2f}</code>\n\n"
                                        f"برای مدیریت از دکمه‌های زیر استفاده کنید:"
                                    )
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, guide, reply_markup=get_main_menu_keyboard())

            except Exception as e:
                logger.error(f"خطا در شنود پیام‌های ربات: {e}")

            await asyncio.sleep(2.0)

# ==================== گزارش خودکار پایان روز (ساعت ۲۳:۰۰) ====================

async def daily_digest_scheduler():
    logger.info("🌙 اسکژولر گزارش خودکار پایان روز فعال شد...")
    last_sent_date = ""
    tz_iran = timezone(timedelta(hours=3, minutes=30))

    while True:
        try:
            now = datetime.now(tz_iran)
            today_str = now.strftime("%Y-%m-%d")

            if now.hour == 23 and now.minute == 0 and last_sent_date != today_str:
                logger.info(f"🌙 ارسال خودکار گزارش پایان روز ({today_str})")
                digest = evaluator.get_daily_summary()
                await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, digest, reply_markup=get_main_menu_keyboard())
                last_sent_date = today_str

        except Exception as e:
            logger.error(f"خطا در اسکژولر گزارش روزانه: {e}")

        await asyncio.sleep(30.0)

# ==================== مانیتورینگ زنده موقعیت معامله ====================

async def monitor_position_live_loop():
    logger.info("⚡️ حلقه بررسی ثانیه‌ای موقعیت سیگنال فعال شد.")
    while True:
        try:
            price = gold_tracker.get_price()
            if price:
                status_alert = evaluator.check_live_status_change(price)
                if status_alert:
                    logger.info("🔔 پیام وضعیت / نتیجه سیگنال صادر شد.")
                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, status_alert, reply_markup=get_main_menu_keyboard())
        except Exception as e:
            logger.error(f"خطا در حلقه بررسی موقعیت: {e}")

        await asyncio.sleep(2.0)

# ==================== پردازش پیام‌های دریافتی از کانال ====================

async def handle_channel_message(msg_id: int, raw_text: str):
    parsed = parse_lordxau_message(raw_text)
    if not parsed:
        logger.info("ℹ️ پیام نویز یا نامربوط بود و فیلتر شد.")
        return

    cat, title, formatted_html, should_alert = parsed
    current_price = gold_tracker.get_price()
    extra_analysis = ""
    outcome_report = None
    reply_markup = None

    if cat == "SIGNAL_ENTRY":
        direction = "BUY" if ("buy" in raw_text.lower() or "بای" in raw_text.lower()) else "SELL"
        enter_match = re.search(r'(?:enter|ورود)\s*[:=]?\s*([0-9/\.\-]+)', raw_text.lower())
        enter_raw = enter_match.group(1) if enter_match else ""
        
        sig_num, analysis = evaluator.register_entry(direction, enter_raw, current_price)
        formatted_html = formatted_html.replace("⚡️ <b>سیگنال ورود جدید طلا (XAUUSD)</b> ⚡️", f"⚡️ <b>سیگنال شماره #{sig_num} طلا (XAUUSD)</b> ⚡️")
        extra_analysis = f"\n\n━━━━━━━━━━━━━━━\n📊 <b>تحلیل آنی موقعیت بازار:</b>\n{analysis}"
        reply_markup = get_signal_action_keyboard(sig_num)

    elif cat == "SIGNAL_STOP":
        stop_match = re.search(r'(?:stop|استاپ|sl)\s*[:=]?\s*([0-9\.]+)', raw_text.lower())
        if stop_match:
            stop_val = stop_match.group(1)
            analysis, sl_outcome = evaluator.register_stop(stop_val, current_price)
            extra_analysis = f"\n\n━━━━━━━━━━━━━━━\n📊 <b>وضعیت حد ضرر نسبت به بازار:</b>\n{analysis}"
            if sl_outcome:
                outcome_report = sl_outcome

    elif cat == "ACTION_RISKFREE":
        success, rf_msg = evaluator.register_risk_free()
        extra_analysis = f"\n\n{rf_msg}\n💵 <i>قیمت فعلی طلا: ${current_price:.2f}</i>" if current_price else f"\n\n{rf_msg}"

    elif cat == "ACTION_CLOSE":
        success, close_notice, close_outcome = evaluator.register_manual_close(current_price)
        extra_analysis = f"\n\n{close_notice}\n💵 <i>قیمت لحظه‌ای طلا: ${current_price:.2f}</i>" if current_price else f"\n\n{close_notice}"
        if close_outcome:
            outcome_report = close_outcome

    elif cat == "ACTION_STOP_HIT":
        outcome_report = evaluator.register_stop_hit_message(current_price)

    elif cat == "MANAGEMENT_INFO" and any(k in raw_text for k in ["برگشت ورود", "فری شد", "فری خورد"]):
        outcome_report = evaluator.register_break_even(current_price)

    elif current_price:
        extra_analysis = f"\n\n💵 <b>قیمت لحظه‌ای طلا:</b> <code>${current_price:.2f}</code>"

    final_message = formatted_html + extra_analysis
    logger.info(f"🎯 ارسال سیگنال به کاربر: [{cat}]")
    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, final_message, reply_markup=reply_markup)

    if outcome_report:
        logger.info("🏁 ارسال کارنامه نتیجه نهایی سیگنال به کاربر...")
        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, outcome_report, reply_markup=get_main_menu_keyboard())

async def handle_channel_edited_message(msg_id: int, raw_text: str):
    parsed = parse_lordxau_message(raw_text)
    if parsed:
        cat, title, formatted_html, should_alert = parsed
        current_price = gold_tracker.get_price()
        price_note = f"\n\n💵 <b>قیمت فعلی:</b> <code>${current_price:.2f}</code>" if current_price else ""
        edit_notice = f"⚠️ <b>(پیام ویرایش شد)</b>\n\n" + formatted_html + price_note
        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, edit_notice)

# ==================== تابع اصلی ====================

async def main():
    check_env()

    # استارت تسک‌های موازی
    asyncio.create_task(gold_tracker.run_loop())
    asyncio.create_task(monitor_position_live_loop())
    asyncio.create_task(bot_command_listener())
    asyncio.create_task(daily_digest_scheduler())

    await asyncio.sleep(2.0)
    initial_gold_price = gold_tracker.get_price()
    price_str = f"${initial_gold_price:.2f}" if initial_gold_price else "در حال بارگذاری..."

    # اعلان راه‌اندازی موفق به کاربر
    startup_msg = (
        "🚀 <b>ربات هوشمند رصد سیگنال طلا فعال شد!</b>\n\n"
        f"📡 <b>کانال هدف:</b> <code>@{TARGET_CHANNEL}</code>\n"
        f"💵 <b>قیمت لحظه‌ای طلا (XAUUSD):</b> <code>{price_str}</code>\n"
        f"💰 <b>سرمایه انتخابی شما در هر معامله:</b> <code>${evaluator.trade_budget:.2f}</code>\n\n"
        "✨ <b>سیستم بدون نیاز به اکانت و به‌صورت مستقل در حال رصد ۲۴ ساعته است.</b>\n"
        "برای مدیریت از دکمه‌های زیر استفاده کنید:"
    )
    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, startup_msg, reply_markup=get_main_menu_keyboard())

    # راه‌اندازی شنونده وب کانال تلگرام
    listener = WebChannelListener(channel_name=TARGET_CHANNEL, poll_interval=1.8)
    listener.on_new_message = handle_channel_message
    listener.on_edited_message = handle_channel_edited_message

    await listener.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("ربات متوقف شد.")
