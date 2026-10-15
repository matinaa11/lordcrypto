import os
import json
import logging
from typing import List, Dict, Any, Tuple, Optional
from dotenv import load_dotenv

logger = logging.getLogger("Config")
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
USER_CHAT_ID = os.getenv("USER_CHAT_ID", "").strip()
DATA_DIR = os.getenv("DATA_DIR", ".").strip()

if DATA_DIR and DATA_DIR != ".":
    os.makedirs(DATA_DIR, exist_ok=True)

CHANNELS_FILE = os.path.join(DATA_DIR, "channels.json")

DEFAULT_GOLD_SYMBOL = "XAUTUSDT"
DEFAULT_GOLD_DISPLAY = "XAUT/USDT (GOLD)"
OURBIT_GOLD_CONTRACT = "GOLD(XAUT)USDT"

DEFAULT_CHANNELS = [
    {
        "username": "lordxau",
        "title": "LORD XAU (XAUT/USDT)",
        "type": "GOLD",
        "enabled": True
    },
    {
        "username": "lordcryptovip",
        "title": "LORD CRYPTO VIP",
        "type": "CRYPTO",
        "enabled": True
    }
]

def _clean_username(raw: str) -> str:
    cleaned = raw.strip()
    if "t.me/" in cleaned:
        cleaned = cleaned.split("t.me/")[-1].split("/")[0].replace("s/", "")
    cleaned = cleaned.replace("@", "").strip()
    return cleaned.lower()

def load_channels() -> List[Dict[str, Any]]:
    """بارگذاری لیست کانال‌ها از فایل دیتابیس پایدار یا مقدار اولیه"""
    channels = []
    if os.path.exists(CHANNELS_FILE):
        try:
            with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
                channels = json.load(f)
        except Exception as e:
            logger.error(f"خطا در خواندن فایل کانال‌ها: {e}")

    if not channels:
        # اگر در متغیر محیطی TARGET_CHANNELS یا TARGET_CHANNEL مقداری ست شده بود
        env_raw = os.getenv("TARGET_CHANNELS", os.getenv("TARGET_CHANNEL", "")).strip()
        if env_raw:
            env_list = [c.strip() for c in env_raw.split(",") if c.strip()]
            for item in env_list:
                u = _clean_username(item)
                # بررسی وجود در دیفالت
                matching = next((d for d in DEFAULT_CHANNELS if d["username"].lower() == u), None)
                if matching:
                    channels.append(matching.copy())
                else:
                    channels.append({
                        "username": u,
                        "title": f"@{u}",
                        "type": "AUTO",
                        "enabled": True
                    })
        else:
            channels = [c.copy() for c in DEFAULT_CHANNELS]
        save_channels(channels)

    return channels

def save_channels(channels: List[Dict[str, Any]]):
    try:
        with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(channels, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"خطا در ذخیره فایل کانال‌ها: {e}")

def get_active_channels() -> List[Dict[str, Any]]:
    return [c for c in load_channels() if c.get("enabled", True)]

def add_channel(raw_input: str, title: Optional[str] = None, ch_type: str = "AUTO") -> Tuple[bool, str]:
    u = _clean_username(raw_input)
    if not u:
        return False, "❌ نام کاربری یا لینک کانال نامعتبر است."

    channels = load_channels()
    for c in channels:
        if c["username"].lower() == u:
            if not c.get("enabled", True):
                c["enabled"] = True
                save_channels(channels)
                return True, f"✅ کانال @{u} که قبلاً غیرفعال بود، دوباره فعال شد."
            return False, f"⚠️ کانال @{u} در حال حاضر در لیست کانال‌های تحت رصد وجود دارد."

    t = title or f"@{u}"
    if u == "lordxau":
        t = "LORD XAU (طلا)"
        ch_type = "GOLD"
    elif u == "lordcryptovip":
        t = "LORD CRYPTO VIP"
        ch_type = "CRYPTO"

    channels.append({
        "username": u,
        "title": t,
        "type": ch_type,
        "enabled": True
    })
    save_channels(channels)
    return True, f"✅ کانال <b>{t}</b> (<code>@{u}</code>) با موفقیت به لیست رصد اضافه شد."

def remove_channel(raw_input: str) -> Tuple[bool, str]:
    u = _clean_username(raw_input)
    channels = load_channels()
    initial_len = len(channels)
    channels = [c for c in channels if c["username"].lower() != u]

    if len(channels) < initial_len:
        save_channels(channels)
        return True, f"🗑 کانال <code>@{u}</code> با موفقیت از سیستم حذف گردید."
    return False, f"⚠️ کانال <code>@{u}</code> در لیست یافت نشد."

def toggle_channel(raw_input: str) -> Tuple[bool, str, bool]:
    u = _clean_username(raw_input)
    channels = load_channels()
    for c in channels:
        if c["username"].lower() == u:
            cur = c.get("enabled", True)
            c["enabled"] = not cur
            save_channels(channels)
            state_str = "فعال 🟢" if not cur else "غیرفعال 🔴"
            return True, f"وضعیت کانال @{u} به <b>{state_str}</b> تغییر یافت.", not cur
    return False, f"⚠️ کانال @{u} یافت نشد.", False
