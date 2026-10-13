import logging
import aiohttp
from typing import Optional, Dict, Any

logger = logging.getLogger("Notifier")

async def send_telegram_alert(
    bot_token: str, 
    chat_id: str, 
    html_message: str, 
    reply_markup: Optional[Dict[str, Any]] = None
) -> Optional[int]:
    """
    ارسال پیام HTML با اولویت بالا به بات تلگرام شخصی.
    در صورت موفقیت، message_id پیام را بازمی‌گرداند.
    """
    if not bot_token or not chat_id:
        logger.error("BOT_TOKEN یا USER_CHAT_ID تنظیم نشده است.")
        return None

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": html_message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": False
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    msg_id = data.get("result", {}).get("message_id")
                    logger.info(f"نوتیفیکیشن ارسال شد (Message ID: {msg_id})")
                    return msg_id
                else:
                    err = await resp.text()
                    logger.error(f"خطا در ارسال پیام به تلگرام (کد {resp.status}): {err}")
                    return None
    except Exception as e:
        logger.error(f"خطای ارتباط با سرور تلگرام: {e}")
        return None

async def answer_callback_query(
    bot_token: str, 
    callback_query_id: str, 
    text: Optional[str] = None, 
    show_alert: bool = False
) -> bool:
    """
    پاسخ به کلیک روی دکمه‌های شیشه‌ای تلگرام (Callback Query)
    """
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert
    }
    if text:
        payload["text"] = text

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=8) as resp:
                return resp.status == 200
    except Exception as e:
        logger.error(f"خطا در پاسخ به callback_query: {e}")
        return False

async def edit_message_reply_markup(
    bot_token: str, 
    chat_id: str, 
    message_id: int, 
    reply_markup: Optional[Dict[str, Any]] = None
) -> bool:
    """
    ویرایش دکمه‌های شیشه‌ای یک پیام ارسال‌شده
    """
    url = f"https://api.telegram.org/bot{bot_token}/editMessageReplyMarkup"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": reply_markup or {"inline_keyboard": []}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=8) as resp:
                return resp.status == 200
    except Exception as e:
        logger.error(f"خطا در ویرایش دکمه‌های پیام: {e}")
        return False
