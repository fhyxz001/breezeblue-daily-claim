import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

API_URL = "https://breezeblue.ai/api/credits/daily-claim"
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def log(message):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def load_cookie():
    cookie = (os.getenv("BREEZE_COOKIE") or "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    return cookie


def claim(session):
    response = session.post(API_URL, timeout=30)
    try:
        payload = response.json()
    except ValueError:
        payload = response.text[:500]

    if response.status_code == 200 and not (
        isinstance(payload, dict) and payload.get("ok") is False
    ):
        log(f"签到成功: HTTP {response.status_code} {json.dumps(payload, ensure_ascii=False)}")
        return True

    log(f"签到失败: HTTP {response.status_code} {json.dumps(payload, ensure_ascii=False)}")
    if response.status_code in (401, 403):
        log("Cookie 可能已失效，请更新 .env 中的 BREEZE_COOKIE 后重启容器。")
    return False


def next_run_at(now):
    hour, minute = (int(part) for part in os.getenv("RUN_AT", "00:05").split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def main():
    cookie = load_cookie()
    if not cookie:
        log("未设置 BREEZE_COOKIE，请在 .env 中填写浏览器 Cookie。")
        sys.exit(1)

    session = requests.Session()
    session.headers.update(
        {
            "Cookie": cookie,
            "User-Agent": os.getenv("BREEZE_USER_AGENT", DEFAULT_UA),
            "Origin": "https://breezeblue.ai",
            "Referer": "https://breezeblue.ai/zh/app/home",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )

    log("启动，先签到一次")
    claim(session)

    if os.getenv("RUN_ONCE") == "1":
        return

    while True:
        target = next_run_at(datetime.now(TZ))
        log(f"下次签到时间: {target:%Y-%m-%d %H:%M:%S} (Asia/Shanghai)")
        while True:
            remaining = (target - datetime.now(TZ)).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 3600))
        claim(session)


if __name__ == "__main__":
    main()
