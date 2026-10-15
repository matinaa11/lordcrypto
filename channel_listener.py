import asyncio
import logging
import time
import re
from html.parser import HTMLParser
import aiohttp
from typing import Callable, Coroutine, Any, Dict, Optional

logger = logging.getLogger("ChannelListener")


def _normalize(text: str) -> str:
    """نرمال‌سازی متن برای جلوگیری از تشخیص کاذب ادیت به خاطر فاصله/خط‌شکست اضافه"""
    return re.sub(r'\s+', ' ', text).strip()


class TelegramWebParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.messages = []  # list of (msg_id, text)
        self.current_id = None
        self.in_text = False
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if "data-post" in attrs_dict:
            self.current_id = attrs_dict["data-post"].split("/")[-1]
            
        cls = attrs_dict.get("class", "")
        # فقط متن اصلی پیام (js-message_text) را بردار و نقل‌قول ریپلای (js-message_reply_text) را فیلتر کن
        if tag == "div" and "js-message_text" in cls and "js-message_reply_text" not in cls:
            self.in_text = True
            self.current_text = []
        elif self.in_text and tag == "br":
            self.current_text.append("\n")

    def handle_endtag(self, tag):
        if self.in_text and tag == "div":
            self.in_text = False
            text = "".join(self.current_text).strip()
            if self.current_id and text:
                try:
                    num_id = int(self.current_id)
                except ValueError:
                    num_id = self.current_id
                for idx, (existing_id, _) in enumerate(self.messages):
                    if existing_id == num_id:
                        self.messages[idx] = (num_id, text)
                        break
                else:
                    self.messages.append((num_id, text))

    def handle_data(self, data):
        if self.in_text:
            self.current_text.append(data)


class WebChannelListener:
    def __init__(self, channel_name: str = "lordxau", poll_interval: float = 1.8):
        self.channel_name = channel_name.replace("@", "").strip()
        self.poll_interval = poll_interval
        self._msg_text_cache: Dict[Any, str] = {}    # message_id -> normalized text
        self.seen_messages = self._msg_text_cache    # alias for backward compatibility
        self.recently_alerted: Dict[Any, float] = {} # msg_id -> timestamp آخرین alert
        self.edit_cooldown: float = 30.0             # ثانیه؛ هر msg_id حداکثر هر ۳۰ثانیه یک‌بار trigger می‌شود
        self.is_running = False
        self.on_new_message: Callable[[int, str], Coroutine[Any, Any, None]] = None
        self.on_edited_message: Callable[[int, str], Coroutine[Any, Any, None]] = None

    def _can_alert(self, mid: Any) -> bool:
        """
        چک می‌کند آیا این msg_id در بازه cooldown است.
        اگر می‌تواند alert بفرستد → True برمی‌گرداند و timestamp را ثبت می‌کند.
        اگر نه → False برمی‌گرداند (تکراری است).
        """
        now = time.time()
        last = self.recently_alerted.get(mid)
        if last is not None and (now - last) < self.edit_cooldown:
            return False
        self.recently_alerted[mid] = now
        return True

    def _cleanup_cooldown(self):
        """حذف ورودی‌های قدیمی‌تر برای جلوگیری از memory leak"""
        now = time.time()
        cutoff = now - (self.edit_cooldown * 4)
        stale = [k for k, v in self.recently_alerted.items() if v < cutoff]
        for k in stale:
            del self.recently_alerted[k]
        if stale:
            logger.debug(f"🧹 cleanup: {len(stale)} ورودی قدیمی از cooldown cache حذف شدند")

        if len(self._msg_text_cache) > 1000:
            keys = list(self._msg_text_cache.keys())[:-300]
            for k in keys:
                self._msg_text_cache.pop(k, None)

    async def fetch_messages(self, session: aiohttp.ClientSession):
        url = f"https://t.me/s/{self.channel_name}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with session.get(url, headers=headers, timeout=6) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    parser = TelegramWebParser()
                    parser.feed(html)
                    return parser.messages
                else:
                    logger.warning(f"کد وضعیت وب تلگرام: {resp.status}")
                    return []
        except Exception as e:
            logger.debug(f"خطای موقت در دریافت وب: {e}")
            return []

    async def start(self):
        self.is_running = True
        logger.info(f"🌐 رصدگر نسخه وب کانال @{self.channel_name} فعال شد (فاصله هر {self.poll_interval} ثانیه)...")

        async with aiohttp.ClientSession() as session:
            # بار اول: پیام‌های موجود را ذخیره کن تا پیام‌های قدیمی فوروارد نشوند
            initial_msgs = await self.fetch_messages(session)
            for mid, txt in initial_msgs:
                self._msg_text_cache[mid] = _normalize(txt)

            logger.info(f"✅ تعداد {len(self._msg_text_cache)} پیام اخیر کانال شناسایی شدند. رصد پیام‌های جدید آغاز شد...")

            poll_count = 0
            while self.is_running:
                try:
                    msgs = await self.fetch_messages(session)

                    for mid, txt in msgs:
                        norm = _normalize(txt)

                        # ── ۱. پیام کاملاً جدید (قبلاً در کش نبوده است) ──
                        if mid not in self._msg_text_cache:
                            self._msg_text_cache[mid] = norm
                            if not self._can_alert(mid):
                                logger.debug(f"⏭️ پیام جدید {mid} در cooldown، رد شد")
                                continue
                            logger.info(f"📩 پیام جدید (ID: {mid}): {txt[:60]}...")
                            if self.on_new_message:
                                await self.on_new_message(mid, txt)

                        # ── ۲. پیام قبلاً در کش بوده (بررسی دقیق تغییر متن) ──
                        else:
                            cached_text = self._msg_text_cache.get(mid)
                            # اگر متن نرمالایزشده جدید با کش یکسان است، بدون هیچ لاگی نادیده بگیر
                            if norm == cached_text:
                                continue

                            # متن واقعاً تغییر کرده است
                            self._msg_text_cache[mid] = norm
                            if not self._can_alert(mid):
                                logger.debug(f"⏭️ ادیت {mid} در cooldown (30s)، رد شد — جلوگیری از spam")
                                continue

                            logger.info(f"✏️ ادیت پیام (ID: {mid}): {txt[:60]}...")
                            if self.on_edited_message:
                                await self.on_edited_message(mid, txt)

                    # هر ۵۰ poll (~۹۰ ثانیه) حافظه را پاک‌سازی کن
                    poll_count += 1
                    if poll_count % 50 == 0:
                        self._cleanup_cooldown()

                except Exception as e:
                    logger.error(f"خطا در حلقه رصد وب: {e}")

                await asyncio.sleep(self.poll_interval)


# نام مستعار برای سازگاری کامل
ChannelListener = WebChannelListener
