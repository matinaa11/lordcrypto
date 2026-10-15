import asyncio
import logging
import time
import re
import inspect
from html.parser import HTMLParser
import aiohttp
from typing import Callable, Coroutine, Any, Dict, Optional, List

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
    def __init__(self, channel_name: str = "lordxau", channel_title: str = "", poll_interval: float = 1.8):
        self.channel_name = channel_name.replace("@", "").strip().lower()
        self.channel_title = channel_title or f"@{self.channel_name}"
        self.poll_interval = poll_interval
        self._msg_text_cache: Dict[Any, str] = {}    # message_id -> normalized text
        self.seen_messages = self._msg_text_cache    # alias for backward compatibility
        self.recently_alerted: Dict[Any, float] = {} # msg_id -> timestamp آخرین alert
        self.edit_cooldown: float = 30.0             # ثانیه؛ هر msg_id حداکثر هر ۳۰ثانیه یک‌بار trigger می‌شود
        self.is_running = False
        self.on_new_message: Optional[Callable[..., Coroutine[Any, Any, None]]] = None
        self.on_edited_message: Optional[Callable[..., Coroutine[Any, Any, None]]] = None

    def stop(self):
        self.is_running = False

    def _can_alert(self, mid: Any) -> bool:
        now = time.time()
        last = self.recently_alerted.get(mid)
        if last is not None and (now - last) < self.edit_cooldown:
            return False
        self.recently_alerted[mid] = now
        return True

    def _cleanup_cooldown(self):
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

    async def _emit_new_message(self, mid: int, txt: str):
        if not self.on_new_message:
            return
        sig = inspect.signature(self.on_new_message)
        if len(sig.parameters) >= 4:
            await self.on_new_message(mid, txt, self.channel_name, self.channel_title)
        elif len(sig.parameters) == 3:
            await self.on_new_message(mid, txt, self.channel_name)
        else:
            await self.on_new_message(mid, txt)

    async def _emit_edited_message(self, mid: int, txt: str):
        if not self.on_edited_message:
            return
        sig = inspect.signature(self.on_edited_message)
        if len(sig.parameters) >= 4:
            await self.on_edited_message(mid, txt, self.channel_name, self.channel_title)
        elif len(sig.parameters) == 3:
            await self.on_edited_message(mid, txt, self.channel_name)
        else:
            await self.on_edited_message(mid, txt)

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
                    logger.warning(f"کد وضعیت وب تلگرام برای @{self.channel_name}: {resp.status}")
                    return []
        except Exception as e:
            logger.debug(f"خطای موقت در دریافت وب @{self.channel_name}: {e}")
            return []

    async def start(self):
        self.is_running = True
        logger.info(f"🌐 رصدگر کانال {self.channel_title} (@{self.channel_name}) فعال شد...")

        async with aiohttp.ClientSession() as session:
            initial_msgs = await self.fetch_messages(session)
            for mid, txt in initial_msgs:
                self._msg_text_cache[mid] = _normalize(txt)

            logger.info(f"✅ تعداد {len(self._msg_text_cache)} پیام اخیر کانال @{self.channel_name} شناسایی شدند.")

            poll_count = 0
            while self.is_running:
                try:
                    msgs = await self.fetch_messages(session)

                    for mid, txt in msgs:
                        norm = _normalize(txt)

                        # ۱. پیام جدید
                        if mid not in self._msg_text_cache:
                            self._msg_text_cache[mid] = norm
                            if not self._can_alert(mid):
                                continue
                            logger.info(f"📩 پیام جدید از @{self.channel_name} (ID: {mid}): {txt[:60]}...")
                            await self._emit_new_message(mid, txt)

                        # ۲. بررسی ادیت پیام
                        else:
                            cached_text = self._msg_text_cache.get(mid)
                            if norm == cached_text:
                                continue

                            self._msg_text_cache[mid] = norm
                            if not self._can_alert(mid):
                                logger.debug(f"⏭️ ادیت {mid} از @{self.channel_name} در cooldown، رد شد")
                                continue

                            logger.info(f"✏️ ادیت پیام در @{self.channel_name} (ID: {mid}): {txt[:60]}...")
                            await self._emit_edited_message(mid, txt)

                    poll_count += 1
                    if poll_count % 50 == 0:
                        self._cleanup_cooldown()

                except Exception as e:
                    logger.error(f"خطا در حلقه رصد وب @{self.channel_name}: {e}")

                await asyncio.sleep(self.poll_interval)


class MultiChannelListener:
    """
    مدیریت موازی چندین رصدگر کانال به صورت هم‌زمان با قابلیت افزودن/حذف پویا
    """
    def __init__(self, channels: Optional[List[Dict[str, Any]]] = None, poll_interval: float = 1.8):
        self.poll_interval = poll_interval
        self.listeners: Dict[str, WebChannelListener] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.is_running = False
        self.on_new_message: Optional[Callable[..., Coroutine[Any, Any, None]]] = None
        self.on_edited_message: Optional[Callable[..., Coroutine[Any, Any, None]]] = None

        if channels is None:
            try:
                from config import load_channels
                channels = load_channels()
            except ImportError:
                channels = [
                    {"username": "lordxau", "title": "LORD XAU (طلا)", "enabled": True},
                    {"username": "lordcryptovip", "title": "LORD CRYPTO VIP", "enabled": True}
                ]

        for ch in channels:
            if ch.get("enabled", True):
                self._add_listener(ch["username"], ch.get("title", f"@{ch['username']}"))

    def _add_listener(self, username: str, title: str):
        clean_u = username.lower().replace("@", "").strip()
        if clean_u in self.listeners:
            return
        l = WebChannelListener(channel_name=clean_u, channel_title=title, poll_interval=self.poll_interval)
        l.on_new_message = self._handle_new_msg
        l.on_edited_message = self._handle_edited_msg
        self.listeners[clean_u] = l
        if self.is_running:
            self.tasks[clean_u] = asyncio.create_task(l.start())
            logger.info(f"➕ کانال جدید @{clean_u} به حلقه رصد در حال اجرا اضافه شد.")

    async def _handle_new_msg(self, mid: int, txt: str, channel_name: str, channel_title: str):
        if self.on_new_message:
            await self.on_new_message(mid, txt, channel_name, channel_title)

    async def _handle_edited_msg(self, mid: int, txt: str, channel_name: str, channel_title: str):
        if self.on_edited_message:
            await self.on_edited_message(mid, txt, channel_name, channel_title)

    def add_channel(self, username: str, title: Optional[str] = None):
        t = title or f"@{username}"
        self._add_listener(username, t)

    def remove_channel(self, username: str):
        clean_u = username.lower().replace("@", "").strip()
        if clean_u in self.tasks:
            self.tasks[clean_u].cancel()
            del self.tasks[clean_u]
        if clean_u in self.listeners:
            self.listeners[clean_u].stop()
            del self.listeners[clean_u]
            logger.info(f"➖ کانال @{clean_u} از رصد زنده متوقف شد.")

    def sync_channels(self, channels: List[Dict[str, Any]]):
        """همگام‌سازی شنودگرها با آخرین لیست کانال‌ها"""
        active_map = {c["username"].lower().replace("@", "").strip(): c.get("title", f"@{c['username']}") 
                      for c in channels if c.get("enabled", True)}

        # حذف موارد غیرفعال
        to_remove = [u for u in self.listeners if u not in active_map]
        for u in to_remove:
            self.remove_channel(u)

        # افزودن موارد فعال جدید
        for u, title in active_map.items():
            if u not in self.listeners:
                self.add_channel(u, title)

    async def start(self):
        self.is_running = True
        logger.info(f"🌐 رصدگر چند کاناله فعال شد. کانال‌های اولیه: {list(self.listeners.keys())}")
        for u, l in self.listeners.items():
            if u not in self.tasks or self.tasks[u].done():
                self.tasks[u] = asyncio.create_task(l.start())

        while self.is_running:
            await asyncio.sleep(5)


# نام‌های مستعار برای سازگاری کامل
ChannelListener = MultiChannelListener
