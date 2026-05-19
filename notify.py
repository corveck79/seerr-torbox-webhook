import logging

import requests

import settings

log = logging.getLogger(__name__)


def send(title: str, message: str, success: bool = True) -> None:
    if success and not settings.get("NOTIFY_ON_SUCCESS", True):
        return
    if not success and not settings.get("NOTIFY_ON_FAILURE", True):
        return
    discord_url = settings.get("DISCORD_WEBHOOK_URL", "")
    tg_token = settings.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = settings.get("TELEGRAM_CHAT_ID", "")
    if discord_url:
        _discord(discord_url, title, message, success)
    if tg_token and tg_chat:
        _telegram(tg_token, tg_chat, title, message, success)


def _discord(url: str, title: str, message: str, success: bool) -> None:
    color = 0x4ADE80 if success else 0xF87171
    payload = {"embeds": [{"title": title, "description": message, "color": color}]}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as exc:
        log.warning("Discord notify failed: %s", exc)


def _telegram(token: str, chat_id: str, title: str, message: str, success: bool) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    emoji = "✅" if success else "❌"
    payload = {
        "chat_id": chat_id,
        "text": f"{emoji} *{title}*\n{message}",
        "parse_mode": "Markdown",
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as exc:
        log.warning("Telegram notify failed: %s", exc)


def test() -> dict:
    results = {}
    discord_url = settings.get("DISCORD_WEBHOOK_URL", "")
    tg_token = settings.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = settings.get("TELEGRAM_CHAT_ID", "")
    if discord_url:
        try:
            r = requests.post(
                discord_url,
                json={"content": "🧪 Test notification from Mycelium"},
                timeout=10,
            )
            results["discord"] = "ok" if r.status_code < 400 else f"http {r.status_code}"
        except Exception as exc:
            results["discord"] = str(exc)[:100]
    else:
        results["discord"] = "not configured"
    if tg_token and tg_chat:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            r = requests.post(
                url, json={"chat_id": tg_chat, "text": "🧪 Test notification"}, timeout=10,
            )
            results["telegram"] = "ok" if r.status_code < 400 else f"http {r.status_code}"
        except Exception as exc:
            results["telegram"] = str(exc)[:100]
    else:
        results["telegram"] = "not configured"
    return results
