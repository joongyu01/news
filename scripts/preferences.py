"""Small, owner-managed Telegram subscriptions (one JSON row, max five chats)."""
from . import storage
from .config import env


def defaults():
    return {"urgent": True, "daily": True, "mode": "standard", "limit": 0,
            "watch": [], "exclude": [], "quiet": "off"}


def initial():
    owner = env("TELEGRAM_CHAT_ID")
    if not owner.isdigit():
        raise RuntimeError("Initial TELEGRAM_CHAT_ID must be the owner's private chat")
    return {"version": 1, "owner": owner, "chats": {owner: defaults()}, "recent": []}


def load():
    if not storage.enabled():
        return initial()
    rows = storage.request("GET", "news_bot_settings", params={"id": "eq.main", "select": "payload"}).json()
    if not rows:
        return initial()
    payload = rows[0]["payload"]
    if payload.get("version") != 1 or not str(payload.get("owner", "")).isdigit():
        raise RuntimeError("Invalid bot settings")
    if not isinstance(payload.get("chats"), dict) or len(payload["chats"]) > 5:
        raise RuntimeError("Invalid subscriptions")
    return normalize(payload)


def normalize(payload):
    import copy
    common = {**defaults(), **payload.get("global", payload["chats"].get(payload["owner"], next(iter(payload["chats"].values()), {})))}
    return {**payload, "global": common,
            "chats": {chat: copy.deepcopy(common) for chat in payload["chats"]}}


def quiet_now(settings, now):
    quiet = settings.get("quiet", "off")
    if quiet == "off":
        return False
    start, end = map(int, quiet.split("-"))
    return start <= now.hour < end if start < end else now.hour >= start or now.hour < end
