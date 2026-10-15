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
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("LordGoldBot")

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
USER_CHAT_ID = os.getenv("USER_CHAT_ID")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "lordxau").strip()

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
                {"text": "⚙️ تنظیمات معامله و کارمزد", "callback_data": "settings_main"},
                {"text": "🌙 گزارش امروز", "callback_data": "today_digest"}
            ]
        ]
    }

def get_settings_menu_keyboard(mode: str = "OURBIT_FUTURES"):
    mode_btn_text = "🔄 سوییچ به Forex MT5 (لات)" if mode == "OURBIT_FUTURES" else "🔄 سوییچ به Ourbit (اهرم)"
    return {
        "inline_keyboard": [
            [
                {"text": mode_btn_text, "callback_data": "settings_toggle_mode"}
            ],
            [
                {"text": "💰 تغییر سرمایه ($)", "callback_data": "settings_menu_balance"},
                {"text": "⚡ تغییر اهرم (Leverage)", "callback_data": "settings_menu_leverage"}
            ],
            [
                {"text": "📊 تغییر حجم لات (Lot)", "callback_data": "settings_menu_lot"},
                {"text": "💸 تغییر کارمزد (Fee %)", "callback_data": "settings_menu_fee"}
            ],
            [
                {"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}
            ]
        ]
    }

def get_balance_selection_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "5$", "callback_data": "set_balance_5"},
                {"text": "10$", "callback_data": "set_balance_10"},
                {"text": "15$", "callback_data": "set_balance_15"},
                {"text": "50$", "callback_data": "set_balance_50"}
            ],
            [
                {"text": "100$", "callback_data": "set_balance_100"},
                {"text": "200$", "callback_data": "set_balance_200"}
            ],
            [
                {"text": "🔙 بازگشت به تنظیمات", "callback_data": "settings_main"}
            ]
        ]
    }

def get_leverage_selection_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "20x", "callback_data": "set_leverage_20"},
                {"text": "50x", "callback_data": "set_leverage_50"},
                {"text": "100x", "callback_data": "set_leverage_100"}
            ],
            [
                {"text": "200x", "callback_data": "set_leverage_200"},
                {"text": "500x", "callback_data": "set_leverage_500"}
            ],
            [
                {"text": "🔙 بازگشت به تنظیمات", "callback_data": "settings_main"}
            ]
        ]
    }

def get_lot_selection_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "0.01 لات", "callback_data": "set_lot_0.01"},
                {"text": "0.02 لات", "callback_data": "set_lot_0.02"}
            ],
            [
                {"text": "0.05 لات", "callback_data": "set_lot_0.05"},
                {"text": "0.10 لات", "callback_data": "set_lot_0.10"}
            ],
            [
                {"text": "🔙 بازگشت به تنظیمات", "callback_data": "settings_main"}
            ]
        ]
    }

def get_fee_selection_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "0.04% (Market / Taker Ourbit)", "callback_data": "set_fee_market"}
            ],
            [
                {"text": "0.02% (Limit / Maker Ourbit)", "callback_data": "set_fee_limit"}
            ],
            [
                {"text": "0% (بدون کارمزد / فارکس خام)", "callback_data": "set_fee_zero"}
            ],
            [
                {"text": "🔙 بازگشت به تنظیمات", "callback_data": "settings_main"}
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

                                elif cb_data == "main_menu":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        "منوی اصلی کنترل ربات:", 
                                        reply_markup=get_main_menu_keyboard()
                                    )

                                # ── منوی تنظیمات معامله و کارمزد ──
                                elif cb_data == "settings_main":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    text = evaluator.get_settings_summary_text()
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        text, 
                                        reply_markup=get_settings_menu_keyboard(cur_mode)
                                    )

                                elif cb_data == "settings_toggle_mode":
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    new_mode = "FOREX_MT5" if cur_mode == "OURBIT_FUTURES" else "OURBIT_FUTURES"
                                    res = evaluator.set_mode(new_mode)
                                    await answer_callback_query(BOT_TOKEN, cb_id, "پلتفرم با موفقیت تغییر یافت")
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"{res}\n\n{evaluator.get_settings_summary_text()}",
                                        reply_markup=get_settings_menu_keyboard(new_mode)
                                    )

                                elif cb_data == "settings_menu_balance" or cb_data == "menu_budget":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"💰 <b>سرمایه مارجین فعلی: ${evaluator.trade_budget:.2f}</b>\n\nمبلغ دلخواه را انتخاب کنید یا دستور <code>/balance [عدد]</code> را بفرستید:",
                                        reply_markup=get_balance_selection_keyboard()
                                    )

                                elif cb_data.startswith("set_balance_") or cb_data.startswith("set_budget_"):
                                    amount = float(cb_data.replace("set_balance_", "").replace("set_budget_", ""))
                                    res = evaluator.set_balance(amount)
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"سرمایه به ${amount:.2f} تغییر یافت")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"{res}\n\n{evaluator.get_settings_summary_text()}", 
                                        reply_markup=get_settings_menu_keyboard(cur_mode)
                                    )

                                elif cb_data == "settings_menu_leverage":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"⚡️ <b>اهرم فعلی فیوچرز: {evaluator.settings.get('leverage', 100)}x</b>\n\nضریب اهرم جدید را انتخاب کنید یا دستور <code>/leverage [عدد]</code> را بفرستید:",
                                        reply_markup=get_leverage_selection_keyboard()
                                    )

                                elif cb_data.startswith("set_leverage_"):
                                    lev = int(cb_data.replace("set_leverage_", ""))
                                    res = evaluator.set_leverage(lev)
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"اهرم به {lev}x تنظیم شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"{res}\n\n{evaluator.get_settings_summary_text()}", 
                                        reply_markup=get_settings_menu_keyboard(cur_mode)
                                    )

                                elif cb_data == "settings_menu_lot":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"📊 <b>حجم فعلی معامله فارکس: {evaluator.settings.get('lot_size', 0.01)} Lot</b>\n\nحجم جدید را انتخاب کنید یا دستور <code>/lot [عدد]</code> را بفرستید:",
                                        reply_markup=get_lot_selection_keyboard()
                                    )

                                elif cb_data.startswith("set_lot_"):
                                    lot = float(cb_data.replace("set_lot_", ""))
                                    res = evaluator.set_lot_size(lot)
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"حجم به {lot} Lot تنظیم شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"{res}\n\n{evaluator.get_settings_summary_text()}", 
                                        reply_markup=get_settings_menu_keyboard(cur_mode)
                                    )

                                elif cb_data == "settings_menu_fee":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"💸 <b>کارمزد فعلی: {evaluator.settings.get('fee_rate', 0.04)}% ({evaluator.settings.get('order_type', 'MARKET')})</b>\n\nنرخ کارمزد صرافی را انتخاب کنید یا دستور <code>/fee [درصد]</code> را بفرستید:",
                                        reply_markup=get_fee_selection_keyboard()
                                    )

                                elif cb_data == "set_fee_market":
                                    res = evaluator.set_order_type("MARKET")
                                    await answer_callback_query(BOT_TOKEN, cb_id, "کارمزد 0.04% مارکت تنظیم شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"{res}\n\n{evaluator.get_settings_summary_text()}", reply_markup=get_settings_menu_keyboard(cur_mode))

                                elif cb_data == "set_fee_limit":
                                    res = evaluator.set_order_type("LIMIT")
                                    await answer_callback_query(BOT_TOKEN, cb_id, "کارمزد 0.02% لیمیت تنظیم شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"{res}\n\n{evaluator.get_settings_summary_text()}", reply_markup=get_settings_menu_keyboard(cur_mode))

                                elif cb_data == "set_fee_zero":
                                    res = evaluator.set_order_type("ZERO")
                                    await answer_callback_query(BOT_TOKEN, cb_id, "کارمزد صفر تنظیم شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"{res}\n\n{evaluator.get_settings_summary_text()}", reply_markup=get_settings_menu_keyboard(cur_mode))

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

                                # تغییر سرمایه / بالانس
                                balance_match = re.search(r'(?:/balance|/budget|سرمایه|بالانس|بودجه)\s*([0-9\.]+)', text)
                                if balance_match:
                                    new_val = float(balance_match.group(1))
                                    res = evaluator.set_balance(new_val)
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    reply = f"{res}\n\n{evaluator.get_settings_summary_text()}"
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, reply, reply_markup=get_settings_menu_keyboard(cur_mode))

                                # تغییر اهرم
                                elif re.search(r'(?:/leverage|اهرم|لوریج)\s*([0-9]+)', text):
                                    lev_match = re.search(r'(?:/leverage|اهرم|لوریج)\s*([0-9]+)', text)
                                    new_lev = int(lev_match.group(1))
                                    res = evaluator.set_leverage(new_lev)
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    reply = f"{res}\n\n{evaluator.get_settings_summary_text()}"
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, reply, reply_markup=get_settings_menu_keyboard(cur_mode))

                                # تغییر حجم لات
                                elif re.search(r'(?:/lot|لات|حجم)\s*([0-9\.]+)', text):
                                    lot_match = re.search(r'(?:/lot|لات|حجم)\s*([0-9\.]+)', text)
                                    new_lot = float(lot_match.group(1))
                                    res = evaluator.set_lot_size(new_lot)
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    reply = f"{res}\n\n{evaluator.get_settings_summary_text()}"
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, reply, reply_markup=get_settings_menu_keyboard(cur_mode))

                                # تغییر درصد کارمزد
                                elif re.search(r'(?:/fee|کارمزد)\s*([0-9\.]+)', text):
                                    fee_match = re.search(r'(?:/fee|کارمزد)\s*([0-9\.]+)', text)
                                    new_fee = float(fee_match.group(1))
                                    res = evaluator.set_fee_rate(new_fee)
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    reply = f"{res}\n\n{evaluator.get_settings_summary_text()}"
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, reply, reply_markup=get_settings_menu_keyboard(cur_mode))

                                # سوییچ پلتفرم
                                elif text.startswith("/mode") or text.startswith("حالت"):
                                    parts = text.split()
                                    if len(parts) >= 2:
                                        m_name = parts[1]
                                        res = evaluator.set_mode(m_name)
                                        cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"{res}\n\n{evaluator.get_settings_summary_text()}", reply_markup=get_settings_menu_keyboard(cur_mode))
                                    else:
                                        cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, evaluator.get_settings_summary_text(), reply_markup=get_settings_menu_keyboard(cur_mode))

                                elif text in ["/settings", "تنظیمات"]:
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, evaluator.get_settings_summary_text(), reply_markup=get_settings_menu_keyboard(cur_mode))

                                elif text in ["/stats", "آمار", "کارنامه"]:
                                    stats = evaluator.get_stats_summary()
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"📊 <b>کارنامه معاملات:</b>\n\n{stats}", reply_markup=get_main_menu_keyboard())

                                elif text in ["/today", "گزارش امروز", "امروز"]:
                                    digest = evaluator.get_daily_summary()
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, digest, reply_markup=get_main_menu_keyboard())

                                elif text in ["/start", "/help", "منو", "راهنما"]:
                                    guide = (
                                        f"👋 <b>کنترل پنل هوشمند رصد سیگنال طلا</b>\n\n"
                                        f"{evaluator.get_settings_summary_text()}"
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

    # جلوگیری از ارسال دستورات کنترلی (ریسک‌فری / کلوز / استاپ) وقتی سیگنال فعالی وجود ندارد
    control_categories = ["ACTION_RISKFREE", "ACTION_CLOSE", "SIGNAL_STOP", "ACTION_STOP_HIT"]
    if cat in control_categories and not evaluator.has_active_trade():
        logger.info("ℹ️ دستور کنترلی نادیده گرفته شد (معامله فعالی وجود ندارد).")
        return

    current_price = gold_tracker.get_price()
    extra_analysis = ""
    outcome_report = None
    reply_markup = None

    if cat == "SIGNAL_ENTRY":
        direction = getattr(parsed, "direction", None)
        if not direction:
            direction = "BUY" if ("buy" in raw_text.lower() or "بای" in raw_text.lower()) else "SELL"
        
        enter_raw = getattr(parsed, "entry_raw", None)
        if not enter_raw:
            enter_match = re.search(r'(?:enter|ورود)\s*[:=]?\s*([0-9/\.\-]+)', raw_text.lower())
            enter_raw = enter_match.group(1) if enter_match else ""
        
        sig_num, analysis = evaluator.register_entry(direction, enter_raw, current_price)

        # اگر در همان پیام سیگنال، استاپ‌لاس هم مشخص شده باشد، بلافاصله آن را متصل کن
        parsed_sl = getattr(parsed, "stop_loss", None)
        if parsed_sl:
            sl_analysis, sl_outcome = evaluator.register_stop(str(parsed_sl), current_price)
            if sl_analysis:
                analysis = sl_analysis
            if sl_outcome:
                outcome_report = sl_outcome

        formatted_html = formatted_html.replace("⚡️ <b>سیگنال ورود جدید طلا (XAUUSD)</b> ⚡️", f"⚡️ <b>سیگنال شماره #{sig_num} طلا (XAUUSD)</b> ⚡️")
        extra_analysis = f"\n\n━━━━━━━━━━━━━━━\n📊 <b>تحلیل آنی موقعیت بازار:</b>\n{analysis}"
        reply_markup = get_signal_action_keyboard(sig_num)

    elif cat == "SIGNAL_STOP":
        parsed_sl = getattr(parsed, "stop_loss", None)
        if parsed_sl:
            stop_val = str(parsed_sl)
        else:
            stop_match = re.search(r'(?:stop|استاپ|sl)[_:\s-]*([0-9\.]+)', raw_text.lower())
            stop_val = stop_match.group(1) if stop_match else ""

        if stop_val:
            analysis, sl_outcome = evaluator.register_stop(stop_val, current_price)
            extra_analysis = f"\n\n━━━━━━━━━━━━━━━\n📊 <b>وضعیت حد ضرر نسبت به بازار:</b>\n{analysis}"
            if sl_outcome:
                outcome_report = sl_outcome

    elif cat == "ACTION_RISKFREE":
        success, rf_msg = evaluator.register_risk_free()
        if not success:
            logger.info("ℹ️ دستور کنترلی نادیده گرفته شد (معامله فعالی وجود ندارد).")
            return
        extra_analysis = f"\n\n{rf_msg}\n💵 <i>قیمت فعلی طلا: ${current_price:.2f}</i>" if current_price else f"\n\n{rf_msg}"

    elif cat == "ACTION_CLOSE":
        success, close_notice, close_outcome = evaluator.register_manual_close(current_price)
        if not success:
            logger.info("ℹ️ دستور کنترلی نادیده گرفته شد (معامله فعالی وجود ندارد).")
            return
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
        control_categories = ["ACTION_RISKFREE", "ACTION_CLOSE", "SIGNAL_STOP", "ACTION_STOP_HIT"]
        if cat in control_categories and not evaluator.has_active_trade():
            logger.info("ℹ️ دستور کنترلی نادیده گرفته شد (معامله فعالی وجود ندارد).")
            return

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

    s = evaluator.settings
    mode_str = "Ourbit فیوچرز" if s.get("mode") == "OURBIT_FUTURES" else "Forex MT5"

    startup_msg = (
        "🚀 <b>ربات هوشمند رصد سیگنال طلا فعال شد!</b>\n\n"
        f"📡 <b>کانال هدف:</b> <code>@{TARGET_CHANNEL}</code>\n"
        f"💵 <b>قیمت لحظه‌ای طلا (XAUUSD):</b> <code>{price_str}</code>\n"
        f"📊 <b>پلتفرم معاملاتی:</b> <code>{mode_str}</code>\n"
        f"💰 <b>سرمایه مارجین:</b> <code>${evaluator.trade_budget:.2f}</code> | ⚡️ <b>اهرم:</b> <code>{s.get('leverage', 100)}x</code>\n"
        f"💸 <b>نرخ کارمزد صرافی:</b> <code>{s.get('fee_rate', 0.04)}%</code> ({s.get('order_type', 'MARKET')})\n\n"
        "✨ <b>سیستم به صورت خودکار سود ناخالص، کارمزد صرافی و سود خالص را محاسبه می‌کند.</b>\n"
        "برای مدیریت از دکمه‌های زیر استفاده کنید:"
    )
    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, startup_msg, reply_markup=get_main_menu_keyboard())

    listener = WebChannelListener(channel_name=TARGET_CHANNEL, poll_interval=1.8)
    listener.on_new_message = handle_channel_message
    listener.on_edited_message = handle_channel_edited_message

    await listener.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("ربات متوقف شد.")
