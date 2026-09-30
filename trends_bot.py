#!/usr/bin/env python3
"""India X/Twitter Top 10 trends -> WhatsApp (via CallMeBot). Standard library only.

Usage:
  python trends_bot.py --dry-run   # print the message, don't send, don't save state
  python trends_bot.py             # send to WhatsApp (needs WHATSAPP_PHONE + CALLMEBOT_APIKEY)
"""
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

SOURCE_URL = "https://trends24.in/india/"
STATE_FILE = os.environ.get("STATE_FILE", "state/last.json")
TOP_N = int(os.environ.get("TOP_N", "10"))
CLIMB = 3  # places gained since last hour to earn a ⬆️
IST = timezone(timedelta(hours=5, minutes=30))


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (india-trends-bot)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def latest_trends(page):
    """First list-container on trends24 = the most recent hourly snapshot."""
    block = re.search(r"<div class=list-container>(.*?)</ol>", page, re.S)
    if not block:
        sys.exit("trends24 layout changed: no list-container found")
    trends = []
    for li in re.findall(r"<li>(.*?)</li>", block.group(1), re.S):
        name = re.search(r"class=trend-link>(.*?)</a>", li, re.S)
        if not name:
            continue
        count = re.search(r'data-count="?(\d+)', li)
        trends.append({"name": html.unescape(name.group(1)).strip(),
                       "count": int(count.group(1)) if count else None})
    if not trends:
        sys.exit("trends24 layout changed: no trends parsed")
    return trends[:TOP_N]


def short_count(n):
    if not n:
        return ""
    return f" · {n / 1000:.0f}K posts" if n >= 1000 else f" · {n} posts"


def load_previous():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("ranks", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(trends):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"time": datetime.now(IST).isoformat(),
                   "ranks": {t["name"]: i for i, t in enumerate(trends, 1)}}, f, ensure_ascii=False)


WHATSAPP = {"b": lambda s: f"*{s}*", "i": lambda s: f"_{s}_"}
TELEGRAM = {"b": lambda s: f"<b>{html.escape(s)}</b>", "i": lambda s: f"<i>{html.escape(s)}</i>"}


def build_message(trends, prev, fmt=WHATSAPP):
    b, i = fmt["b"], fmt["i"]
    now = datetime.now(IST).strftime("%I:%M %p").lstrip("0")
    lines = [f"{b(f'🇮🇳 India X Top {len(trends)}')} — {now} IST", ""]
    for rank, t in enumerate(trends, 1):
        was = prev.get(t["name"])
        if prev and was is None:
            mark = "🆕 "
        elif was and was - rank >= CLIMB:
            mark = "⬆️ "
        else:
            mark = ""
        line = f"{rank}. {mark}{b(t['name'])}{short_count(t['count'])}"
        if was and was != rank and mark:
            line += f" (was #{was})"
        lines.append(line)
        if mark == "🆕 ":
            lines.append("   https://x.com/search?q=" + urllib.parse.quote(t["name"]))
    if not prev:
        lines += ["", i("First run — 🆕 marks start from next hour.")]
    lines += ["", i("Source: trends24.in")]
    return "\n".join(lines)


def send_telegram(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        sys.exit("Set TELEGRAM_CHAT_ID (run: python trends_bot.py --chat-id)")
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=30) as r:
        print("Telegram:", json.load(r).get("ok"))


def print_chat_ids():
    """After you message your bot once, this prints your chat id."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or sys.exit("Set TELEGRAM_BOT_TOKEN first")
    updates = json.loads(fetch(f"https://api.telegram.org/bot{token}/getUpdates"))["result"]
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "")
             for u in updates if "message" in u}
    print(chats or "No messages yet — send your bot any message (e.g. hi) and run again")


def send_whatsapp(text):
    phone = os.environ.get("WHATSAPP_PHONE")
    key = os.environ.get("CALLMEBOT_APIKEY")
    if not phone or not key:
        sys.exit("Set WHATSAPP_PHONE (e.g. +919876543210) and CALLMEBOT_APIKEY")
    query = urllib.parse.urlencode({"phone": phone, "text": text, "apikey": key})
    reply = re.sub(r"<[^>]+>", " ", fetch("https://api.callmebot.com/whatsapp.php?" + query))
    reply = " ".join(reply.split())[:300]
    print("CallMeBot:", reply)
    if "error" in reply.lower() or "invalid" in reply.lower():
        sys.exit("CallMeBot rejected the message — check phone number / API key")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--chat-id" in sys.argv:
        return print_chat_ids()
    dry_run = "--dry-run" in sys.argv
    telegram = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
    trends = latest_trends(fetch(SOURCE_URL))
    message = build_message(trends, load_previous(), TELEGRAM if telegram else WHATSAPP)
    print(message)
    if dry_run:
        return
    send_telegram(message) if telegram else send_whatsapp(message)
    save_state(trends)


if __name__ == "__main__":
    main()
