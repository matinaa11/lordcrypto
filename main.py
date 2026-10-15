import os
import sys
import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
import aiohttp
from dotenv import load_dotenv

from config import (
    BOT_TOKEN, 
    USER_CHAT_ID, 
    load_channels, 
    save_channels, 
    add_channel, 
    remove_channel, 
    toggle_channel, 
    get_active_channels
)
from parser import parse_channel_message, parse_lordxau_message
from notifier import (
    send_telegram_alert, 
    answer_callback_query, 
    edit_message_reply_markup
)
from price_fetcher import price_fetcher, gold_tracker
from evaluator import evaluator
from channel_listener import MultiChannelListener, WebChannelListener

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("LordGoldBot")

def check_env():
    missing = []
    if not BOT_TOKEN: missing.append("BOT_TOKEN")
    if not USER_CHAT_ID: missing.append("USER_CHAT_ID")

    if missing:
        logger.error(f"❌ متغیرهای ضروری تنظیم نشده‌اند: {', '.join(missing)}")
        logger.error("تنها به BOT_TOKEN و USER_CHAT_ID نیاز دارید.")
        sys.exit(1)

# نمونه شنودگر چند کاناله سراسری
multi_listener = MultiChannelListener()

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
                {"text": "📡 مدیریت کانال‌های رصد", "callback_data": "channels_menu"}
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

def get_channels_menu_keyboard():
    channels = load_channels()
    buttons = []
    for c in channels:
        status_icon = "🟢" if c.get("enabled", True) else "🔴"
        title = c.get("title", f"@{c['username']}")
        u = c["username"]
        buttons.append([
            {"text": f"{status_icon} {title}", "callback_data": f"toggle_ch_{u}"},
            {"text": "🗑 حذف", "callback_data": f"remove_ch_{u}"}
        ])
    buttons.append([
        {"text": "➕ راهنمای افزودن کانال جدید", "callback_data": "add_channel_prompt"}
    ])
    buttons.append([
        {"text": "🔙 بازگشت به تنظیمات", "callback_data": "settings_main"}
    ])
    return {"inline_keyboard": buttons}

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
                {"text": "0.01 Lot", "callback_data": "set_lot_0.01"},
                {"text": "0.02 Lot", "callback_data": "set_lot_0.02"},
                {"text": "0.05 Lot", "callback_data": "set_lot_0.05"}
            ],
            [
                {"text": "0.10 Lot", "callback_data": "set_lot_0.10"},
                {"text": "0.20 Lot", "callback_data": "set_lot_0.20"}
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
                {"text": "0.04% (مارکت / Taker)", "callback_data": "set_fee_market"},
                {"text": "0.02% (لیمیت / Maker)", "callback_data": "set_fee_limit"}
            ],
            [
                {"text": "0.06% (استاندارد)", "callback_data": "set_fee_0.06"},
                {"text": "0.00% (بدون کارمزد)", "callback_data": "set_fee_0.00"}
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
                {"text": "✅ من هم وارد این معامله شدم", "callback_data": f"enter_sig_{sig_num}"},
                {"text": "❌ رد کردن این معامله", "callback_data": f"skip_sig_{sig_num}"}
            ]
        ]
    }

# ==================== دریافت دستورات و دکمه‌ها ====================

async def bot_command_listener():
    logger.info("🤖 شنودگر دستورات و دکمه‌های تلگرام فعال شد...")
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

                                if sender_id != str(USER_CHAT_ID):
                                    await answer_callback_query(BOT_TOKEN, cb_id, "دسترسی غیرمجاز")
                                    continue

                                if cb_data == "noop":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    continue

                                elif cb_data == "check_price":
                                    price = price_fetcher.get_price("XAUUSD")
                                    p_str = f"${price:.2f}" if price else "در حال دریافت..."
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"قیمت طلا: {p_str}", show_alert=True)

                                elif cb_data == "check_stats":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    stats = evaluator.get_stats_summary()
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        stats, 
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

                                # ── مدیریت کانال‌ها ──
                                elif cb_data == "channels_menu":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    msg = "📡 <b>مدیریت کانال‌های تحت رصد:</b>\nبرای فعال/غیرفعال کردن هر کانال روی آن کلیک کنید:"
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, msg, reply_markup=get_channels_menu_keyboard())

                                elif cb_data.startswith("toggle_ch_"):
                                    u = cb_data.replace("toggle_ch_", "")
                                    ok, msg, state = toggle_channel(u)
                                    multi_listener.sync_channels(load_channels())
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"وضعیت @{u} تغییر یافت")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, msg, reply_markup=get_channels_menu_keyboard())

                                elif cb_data.startswith("remove_ch_"):
                                    u = cb_data.replace("remove_ch_", "")
                                    ok, msg = remove_channel(u)
                                    multi_listener.sync_channels(load_channels())
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"کانال @{u} حذف شد")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, msg, reply_markup=get_channels_menu_keyboard())

                                elif cb_data == "add_channel_prompt":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    prompt_msg = (
                                        "➕ <b>افزودن کانال جدید برای رصد همزمان:</b>\n\n"
                                        "کافیست دستور زیر را به همراه یوزرنیم یا لینک کانال ارسال کنید:\n"
                                        "<code>/add_channel @Username</code>\n"
                                        "یا\n"
                                        "<code>/add_channel https://t.me/Username</code>\n\n"
                                        "همچنین برای حذف کانال:\n"
                                        "<code>/remove_channel @Username</code>"
                                    )
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, prompt_msg, reply_markup=get_channels_menu_keyboard())

                                # ── تنظیمات سرمایه و کارمزد ──
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

                                elif cb_data in ["settings_menu_balance", "menu_budget"]:
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"💰 سرمایه اولیه مد نظر برای ورود به هر معامله را انتخاب کنید (فعلی: ${evaluator.trade_budget:.2f}):\nیا با دستور `/balance 25` عدد دلخواه وارد کنید.",
                                        reply_markup=get_balance_selection_keyboard()
                                    )

                                elif cb_data.startswith("set_balance_"):
                                    val = float(cb_data.replace("set_balance_", ""))
                                    res = evaluator.set_balance(val)
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"سرمایه به {val}$ تنظیم شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"{res}\n\n{evaluator.get_settings_summary_text()}",
                                        reply_markup=get_settings_menu_keyboard(cur_mode)
                                    )

                                elif cb_data == "settings_menu_leverage":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    cur_lev = evaluator.settings.get("leverage", 100)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"⚡ اهرم مورد نظر برای فیوچرز Ourbit را انتخاب کنید (فعلی: {cur_lev}x):\nیا با دستور `/leverage 75` اهرم دلخواه وارد کنید.",
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
                                    cur_lot = evaluator.settings.get("lot_size", 0.01)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"📊 حجم معامله به لات برای Forex MT5 را انتخاب کنید (فعلی: {cur_lot} Lot):\nیا با دستور `/lot 0.03` حجم دلخواه وارد کنید.",
                                        reply_markup=get_lot_selection_keyboard()
                                    )

                                elif cb_data.startswith("set_lot_"):
                                    lot_val = float(cb_data.replace("set_lot_", ""))
                                    res = evaluator.set_lot_size(lot_val)
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"حجم به {lot_val} لات تنظیم شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"{res}\n\n{evaluator.get_settings_summary_text()}",
                                        reply_markup=get_settings_menu_keyboard(cur_mode)
                                    )

                                elif cb_data == "settings_menu_fee":
                                    await answer_callback_query(BOT_TOKEN, cb_id)
                                    cur_fee = evaluator.settings.get("fee_rate", 0.04)
                                    await send_telegram_alert(
                                        BOT_TOKEN, USER_CHAT_ID, 
                                        f"💸 نرخ کارمزد صرافی در هر طرف معامله (فعلی: {cur_fee}%):\nیا با دستور `/fee 0.05` درصد دلخواه وارد کنید.",
                                        reply_markup=get_fee_selection_keyboard()
                                    )

                                elif cb_data == "set_fee_market":
                                    res = evaluator.set_order_type("MARKET")
                                    await answer_callback_query(BOT_TOKEN, cb_id, "کارمزد مارکت 0.04% فعال شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"{res}\n\n{evaluator.get_settings_summary_text()}", reply_markup=get_settings_menu_keyboard(cur_mode))

                                elif cb_data == "set_fee_limit":
                                    res = evaluator.set_order_type("LIMIT")
                                    await answer_callback_query(BOT_TOKEN, cb_id, "کارمزد لیمیت 0.02% فعال شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"{res}\n\n{evaluator.get_settings_summary_text()}", reply_markup=get_settings_menu_keyboard(cur_mode))

                                elif cb_data.startswith("set_fee_"):
                                    f_val = float(cb_data.replace("set_fee_", ""))
                                    res = evaluator.set_fee_rate(f_val)
                                    await answer_callback_query(BOT_TOKEN, cb_id, f"کارمزد به {f_val}% تنظیم شد")
                                    cur_mode = evaluator.settings.get("mode", "OURBIT_FUTURES")
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, f"{res}\n\n{evaluator.get_settings_summary_text()}", reply_markup=get_settings_menu_keyboard(cur_mode))

                                elif cb_data.startswith("enter_sig_"):
                                    sig_num = int(cb_data.split("_")[-1])
                                    res = evaluator.mark_user_participation(sig_num, True)
                                    await answer_callback_query(BOT_TOKEN, cb_id, res)

                                elif cb_data.startswith("skip_sig_"):
                                    sig_num = int(cb_data.split("_")[-1])
                                    res = evaluator.mark_user_participation(sig_num, False)
                                    await answer_callback_query(BOT_TOKEN, cb_id, res)

                            # ۲. دریافت پیام‌های متنی کاربر
                            message = update.get("message")
                            if message:
                                sender_id = str(message.get("from", {}).get("id"))
                                text = message.get("text", "").strip()

                                if sender_id != str(USER_CHAT_ID):
                                    continue

                                # دستورات مدیریت کانال‌ها
                                if text.startswith("/add_channel"):
                                    parts = text.split(maxsplit=1)
                                    if len(parts) >= 2:
                                        ok, res = add_channel(parts[1])
                                        if ok:
                                            multi_listener.sync_channels(load_channels())
                                        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, res, reply_markup=get_channels_menu_keyboard())
                                    else:
                                        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, "❌ لطفاً نام کاربری یا لینک کانال را وارد کنید:\nمثال: <code>/add_channel @lordcryptovip</code>")

                                elif text.startswith("/remove_channel"):
                                    parts = text.split(maxsplit=1)
                                    if len(parts) >= 2:
                                        ok, res = remove_channel(parts[1])
                                        if ok:
                                            multi_listener.sync_channels(load_channels())
                                        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, res, reply_markup=get_channels_menu_keyboard())
                                    else:
                                        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, "❌ لطفاً نام کاربری کانال را وارد کنید:\nمثال: <code>/remove_channel @lordcryptovip</code>")

                                elif text in ["/channels", "کانال‌ها", "کانال ها"]:
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, "📡 <b>مدیریت کانال‌های تحت رصد:</b>", reply_markup=get_channels_menu_keyboard())

                                # تغییر سرمایه
                                elif re.search(r'(?:/balance|/budget|سرمایه|بودجه)\s*([0-9\.]+)', text):
                                    bud_match = re.search(r'(?:/balance|/budget|سرمایه|بودجه)\s*([0-9\.]+)', text)
                                    new_b = float(bud_match.group(1))
                                    res = evaluator.set_balance(new_b)
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
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, stats, reply_markup=get_main_menu_keyboard())

                                elif text in ["/today", "گزارش امروز", "امروز"]:
                                    digest = evaluator.get_daily_summary()
                                    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, digest, reply_markup=get_main_menu_keyboard())

                                elif text in ["/start", "/help", "منو", "راهنما"]:
                                    guide = (
                                        f"👋 <b>کنترل پنل هوشمند رصد سیگنال طلا و کریپتو</b>\n\n"
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

# ==================== مانیتورینگ زنده موقعیت معامله (همه کانال‌ها) ====================

async def monitor_position_live_loop():
    logger.info("⚡️ حلقه بررسی ثانیه‌ای موقعیت سیگنال‌ها (همه کانال‌ها) فعال شد.")
    while True:
        try:
            alerts = evaluator.check_live_status_change(price_fetcher.get_price)
            for alert in alerts:
                logger.info("🔔 پیام وضعیت / نتیجه سیگنال صادر شد.")
                await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, alert, reply_markup=get_main_menu_keyboard())
        except Exception as e:
            logger.error(f"خطا در حلقه بررسی موقعیت: {e}")

        await asyncio.sleep(2.0)

# ==================== پردازش پیام‌های دریافتی از کانال‌ها (کاملاً ایزوله) ====================

async def handle_channel_message(msg_id: int, raw_text: str, channel_name: str = "lordxau", channel_title: str = "LORD XAU"):
    parsed = parse_channel_message(raw_text, channel_title=channel_title, channel_name=channel_name)
    if not parsed:
        logger.info(f"ℹ️ پیام نویز یا نامربوط از @{channel_name} فیلتر شد.")
        return

    cat, title, formatted_html, should_alert = parsed

    # جلوگیری از ارسال دستورات کنترلی در صورت عدم وجود معامله فعال در این کانال
    control_categories = ["ACTION_RISKFREE", "ACTION_CLOSE", "SIGNAL_STOP", "ACTION_STOP_HIT", "ACTION_TARGET_HIT"]
    if cat in control_categories and not evaluator.has_active_trade(source_channel=channel_name):
        logger.info(f"ℹ️ دستور کنترلی از @{channel_name} نادیده گرفته شد (معامله فعالی در این کانال وجود ندارد).")
        return

    symbol = getattr(parsed, "symbol", "XAUUSD")
    current_price = price_fetcher.get_price(symbol)
    extra_analysis = ""
    outcome_report = None
    reply_markup = None

    if cat == "SIGNAL_ENTRY":
        dir_clean = getattr(parsed, "direction", "BUY")
        enter_raw = getattr(parsed, "entry_raw", "")

        # ثبت معامله منحصراً برای همین کانال (ایزولاسیون کامل)
        sig_num, analysis = evaluator.register_entry(
            direction=dir_clean,
            entry_raw=enter_raw,
            current_price=current_price,
            source_channel=channel_name,
            channel_title=channel_title,
            symbol=symbol
        )

        parsed_sl = getattr(parsed, "stop_loss", None)
        if parsed_sl:
            sl_analysis, sl_outcome = evaluator.register_stop(str(parsed_sl), current_price, source_channel=channel_name)
            if sl_analysis:
                analysis = sl_analysis
            if sl_outcome:
                outcome_report = sl_outcome

        price_note = f"${current_price:.2f}" if current_price else "در حال بارگذاری..."
        extra_analysis = f"\n\n━━━━━━━━━━━━━━━\n📊 <b>تحلیل وضعیت ورود:</b>\n{analysis}\n💵 <i>قیمت لحظه‌ای {symbol}: {price_note}</i>"
        reply_markup = get_signal_action_keyboard(sig_num)

    elif cat == "SIGNAL_STOP":
        parsed_sl = getattr(parsed, "stop_loss", None)
        stop_val = str(parsed_sl) if parsed_sl else ""
        if not stop_val:
            stop_match = re.search(r'(?:stop|استاپ|sl)[_:\s-]*([0-9\.]+)', raw_text.lower())
            stop_val = stop_match.group(1) if stop_match else ""

        if stop_val:
            analysis, sl_outcome = evaluator.register_stop(stop_val, current_price, source_channel=channel_name)
            extra_analysis = f"\n\n━━━━━━━━━━━━━━━\n📊 <b>وضعیت حد ضرر:</b>\n{analysis}"
            if sl_outcome:
                outcome_report = sl_outcome

    elif cat == "ACTION_RISKFREE":
        success, rf_msg = evaluator.register_risk_free(source_channel=channel_name)
        if not success:
            logger.info(f"ℹ️ دستور ریسک‌فری از @{channel_name} نادیده گرفته شد (معامله فعالی نیست).")
            return
        extra_analysis = f"\n\n{rf_msg}"

    elif cat == "ACTION_CLOSE":
        success, close_notice, close_outcome = evaluator.register_manual_close(current_price, source_channel=channel_name)
        if not success:
            logger.info(f"ℹ️ دستور کلوز از @{channel_name} نادیده گرفته شد (معامله فعالی نیست).")
            return
        extra_analysis = f"\n\n{close_notice}"
        if close_outcome:
            outcome_report = close_outcome

    elif cat == "ACTION_STOP_HIT":
        outcome_report = evaluator.register_stop_hit_message(current_price, source_channel=channel_name)

    elif cat == "ACTION_TARGET_HIT":
        extra_analysis = f"\n\n🎯 <i>ادمین کانال اعلام کرد تارگت سود محقق گردید.</i>"

    final_message = formatted_html + extra_analysis
    logger.info(f"🎯 ارسال سیگنال به کاربر از کانال {channel_title}: [{cat}]")
    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, final_message, reply_markup=reply_markup)

    if outcome_report:
        logger.info(f"🏁 ارسال کارنامه نتیجه نهایی سیگنال ({channel_title}) به کاربر...")
        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, outcome_report, reply_markup=get_main_menu_keyboard())

async def handle_channel_edited_message(msg_id: int, raw_text: str, channel_name: str = "lordxau", channel_title: str = "LORD XAU"):
    parsed = parse_channel_message(raw_text, channel_title=channel_title, channel_name=channel_name)
    if parsed:
        cat, title, formatted_html, should_alert = parsed
        control_categories = ["ACTION_RISKFREE", "ACTION_CLOSE", "SIGNAL_STOP", "ACTION_STOP_HIT"]
        if cat in control_categories and not evaluator.has_active_trade(source_channel=channel_name):
            logger.info(f"ℹ️ دستور کنترلی ادیت از @{channel_name} نادیده گرفته شد.")
            return

        symbol = getattr(parsed, "symbol", "XAUUSD")
        current_price = price_fetcher.get_price(symbol)
        price_note = f"\n\n💵 <b>قیمت فعلی {symbol}:</b> <code>${current_price:.2f}</code>" if current_price else ""
        edit_notice = f"⚠️ <b>(پیام ویرایش شد)</b>\n\n" + formatted_html + price_note
        await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, edit_notice)

# ==================== تابع اصلی ====================

async def main():
    check_env()

    # استارت تسک‌های موازی
    asyncio.create_task(price_fetcher.run_loop())
    asyncio.create_task(monitor_position_live_loop())
    asyncio.create_task(bot_command_listener())
    asyncio.create_task(daily_digest_scheduler())

    await asyncio.sleep(2.0)
    initial_gold_price = price_fetcher.get_price("XAUUSD")
    price_str = f"${initial_gold_price:.2f}" if initial_gold_price else "در حال بارگذاری..."

    s = evaluator.settings
    mode_str = "Ourbit فیوچرز" if s.get("mode") == "OURBIT_FUTURES" else "Forex MT5"

    active_chs = get_active_channels()
    ch_names_str = "\n".join([f"• <b>{c.get('title', c['username'])}</b> (<code>@{c['username']}</code>)" for c in active_chs])

    startup_msg = (
        "🚀 <b>ربات هوشمند رصد چندکاناله طلا و کریپتو فعال شد!</b>\n\n"
        f"📡 <b>کانال‌های فعال تحت رصد:</b>\n{ch_names_str}\n\n"
        f"💵 <b>قیمت لحظه‌ای طلا (XAUUSD):</b> <code>{price_str}</code>\n"
        f"📊 <b>پلتفرم معاملاتی:</b> <code>{mode_str}</code>\n"
        f"💰 <b>سرمایه مارجین:</b> <code>${evaluator.trade_budget:.2f}</code> | ⚡️ <b>اهرم:</b> <code>{s.get('leverage', 100)}x</code>\n"
        f"💸 <b>نرخ کارمزد صرافی:</b> <code>{s.get('fee_rate', 0.04)}%</code> ({s.get('order_type', 'MARKET')})\n\n"
        "✨ <b>معاملات هر کانال به صورت کاملاً ایزوله رصد و کارنامه آن‌ها تفکیک خواهد شد.</b>\n"
        "برای مدیریت از دکمه‌های زیر استفاده کنید:"
    )
    await send_telegram_alert(BOT_TOKEN, USER_CHAT_ID, startup_msg, reply_markup=get_main_menu_keyboard())

    multi_listener.on_new_message = handle_channel_message
    multi_listener.on_edited_message = handle_channel_edited_message

    await multi_listener.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("ربات متوقف شد.")
