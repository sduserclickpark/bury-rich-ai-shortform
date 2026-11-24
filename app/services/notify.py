"""알림. 텔레그램 봇(무료)이 설정되면 운영자 스마트폰으로 알림을 보낸다."""
import json
import logging
import urllib.request

from .. import config

log = logging.getLogger(__name__)


def admin(text: str) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return False
    try:
        data = json.dumps({"chat_id": config.TELEGRAM_CHAT_ID, "text": f"[BURY RICH 숏폼] {text}"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        log.warning("telegram notify failed: %s", e)
        return False
