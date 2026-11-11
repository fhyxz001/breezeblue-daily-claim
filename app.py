import html
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests

API_URL = "https://breezeblue.ai/api/credits/daily-claim"
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai
DATA_FILE = os.getenv("DATA_FILE", "/data/records.json")
PORT = int(os.getenv("PORT", "8080"))
RUN_AT = os.getenv("RUN_AT", "00:05")
RUN_ONCE = os.getenv("RUN_ONCE") == "1"
MAX_RECORDS = 500
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

records_lock = threading.Lock()
state_lock = threading.Lock()
records = []
next_run_text = "未启动"


def log(message):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def load_records():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_records():
    directory = os.path.dirname(DATA_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_file = DATA_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, DATA_FILE)


def add_record(ok, status, detail):
    entry = {
        "time": f"{datetime.now(TZ):%Y-%m-%d %H:%M:%S}",
        "ok": ok,
        "status": status,
        "detail": detail,
    }
    with records_lock:
        records.insert(0, entry)
        del records[MAX_RECORDS:]
        try:
            save_records()
        except OSError as exc:
            log(f"保存签到记录失败: {exc}")
    log(f"{'签到成功' if ok else '签到失败'}: {detail}")


def claim_once():
    cookie = (os.getenv("BREEZE_COOKIE") or "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    if not cookie:
        add_record(False, 0, "未配置 BREEZE_COOKIE 环境变量")
        return

    headers = {
        "Cookie": cookie,
        "User-Agent": os.getenv("BREEZE_USER_AGENT", DEFAULT_UA),
        "Origin": "https://breezeblue.ai",
        "Referer": "https://breezeblue.ai/zh/app/home",
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    try:
        response = requests.post(API_URL, headers=headers, timeout=30)
    except requests.RequestException as exc:
        add_record(False, 0, f"请求异常: {exc}")
        return

    try:
        payload = response.json()
        detail = json.dumps(payload, ensure_ascii=False)
    except ValueError:
        payload = None
        detail = response.text[:500]

    ok = response.status_code == 200 and not (
        isinstance(payload, dict) and payload.get("ok") is False
    )
    add_record(ok, response.status_code, detail[:500])


def next_run_at(now):
    hour, minute = (int(part) for part in RUN_AT.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def scheduler():
    global next_run_text
    if RUN_ONCE:
        with state_lock:
            next_run_text = "已关闭（RUN_ONCE=1）"
        return

    while True:
        target = next_run_at(datetime.now(TZ))
        with state_lock:
            next_run_text = f"{target:%Y-%m-%d %H:%M:%S}"
        log(f"下次签到时间: {next_run_text} (Asia/Shanghai)")
        while True:
            remaining = (target - datetime.now(TZ)).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 3600))
        claim_once()


def render_page():
    with records_lock:
        rows_data = list(records)
    with state_lock:
        next_run = next_run_text

    if rows_data:
        last = rows_data[0]
        last_text = ("成功" if last["ok"] else "失败") + f" · {last['time']}"
        last_class = "ok" if last["ok"] else "fail"
        success_count = sum(1 for record in rows_data if record["ok"])
        fail_count = len(rows_data) - success_count
    else:
        last_text = "暂无记录"
        last_class = "muted"
        success_count = 0
        fail_count = 0

    rows = []
    for record in rows_data[:100]:
        badge = (
            '<span class="badge ok">成功</span>'
            if record["ok"]
            else '<span class="badge fail">失败</span>'
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(record.get('time', '')))}</td>"
            f"<td>{badge}</td>"
            f"<td>{html.escape(str(record.get('status', '')))}</td>"
            f"<td>{html.escape(str(record.get('detail', '')))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="4" class="empty">暂无签到记录</td></tr>')

    return (
        PAGE_TEMPLATE.replace("__LAST_TEXT__", html.escape(last_text))
        .replace("__LAST_CLASS__", last_class)
        .replace("__NEXT_RUN__", html.escape(next_run))
        .replace("__TOTAL__", str(len(rows_data)))
        .replace("__SUCCESS__", str(success_count))
        .replace("__FAIL__", str(fail_count))
        .replace("__ROWS__", "".join(rows))
    )


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>BreezeBlue 签到记录</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 32px 16px;
    background: #f4f6fb; color: #1c2434;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Microsoft YaHei", sans-serif;
  }
  .wrap { max-width: 920px; margin: 0 auto; }
  h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -.02em; }
  .sub { margin: 0 0 24px; color: #6b7485; font-size: 14px; }
  .cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
  .card {
    background: #fff; border: 1px solid #e6eaf2; border-radius: 14px;
    padding: 16px; box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
  }
  .label { font-size: 12px; color: #7a8394; margin-bottom: 8px; }
  .value { font-size: 18px; font-weight: 650; word-break: break-all; }
  .value.ok { color: #067647; }
  .value.fail { color: #b42318; }
  .value.muted { color: #98a2b3; }
  .panel {
    background: #fff; border: 1px solid #e6eaf2; border-radius: 16px;
    overflow: hidden; box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
  }
  .panel-head {
    padding: 16px 20px; border-bottom: 1px solid #eef1f6;
    display: flex; justify-content: space-between; align-items: center;
  }
  .panel-head h2 { margin: 0; font-size: 15px; }
  .panel-head span { color: #98a2b3; font-size: 12px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 12px 20px; text-align: left; border-bottom: 1px solid #f1f4f9; }
  th { color: #7a8394; font-weight: 500; background: #fafbfd; white-space: nowrap; }
  td { vertical-align: top; }
  td:nth-child(4) { color: #5b6474; word-break: break-all; }
  tr:last-child td { border-bottom: 0; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .badge.ok { background: #e6f6ec; color: #067647; }
  .badge.fail { background: #feeceb; color: #b42318; }
  .empty { text-align: center; color: #98a2b3; padding: 40px 0; }
  .foot { margin-top: 16px; color: #98a2b3; font-size: 12px; text-align: center; }
  @media (max-width: 720px) {
    .cards { grid-template-columns: repeat(2, 1fr); }
    body { padding: 20px 12px; }
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>BreezeBlue 签到记录</h1>
  <p class="sub">每天自动签到一次，页面每 60 秒刷新</p>

  <div class="cards">
    <div class="card"><div class="label">最近状态</div><div class="value __LAST_CLASS__">__LAST_TEXT__</div></div>
    <div class="card"><div class="label">下次签到</div><div class="value">__NEXT_RUN__</div></div>
    <div class="card"><div class="label">成功次数</div><div class="value ok">__SUCCESS__</div></div>
    <div class="card"><div class="label">失败次数</div><div class="value fail">__FAIL__</div></div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h2>签到明细</h2>
      <span>共 __TOTAL__ 条，显示最近 100 条</span>
    </div>
    <div class="scroll">
      <table>
        <thead><tr><th>时间</th><th>结果</th><th>HTTP</th><th>说明</th></tr></thead>
        <tbody>__ROWS__</tbody>
      </table>
    </div>
  </div>
  <p class="foot">时间均为 Asia/Shanghai</p>
</div>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path != "/":
            self.send_error(404)
            return
        body = render_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log(f"{self.address_string()} {fmt % args}")


def main():
    global records, next_run_text
    records = load_records()
    log("启动，先签到一次")
    claim_once()

    if not RUN_ONCE:
        threading.Thread(target=scheduler, daemon=True).start()
    else:
        with state_lock:
            next_run_text = "已关闭（RUN_ONCE=1）"

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"签到记录页面: http://0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
