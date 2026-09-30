#!/usr/bin/env python3
"""India X/Twitter Top 10 trends -> Telegram (or WhatsApp via CallMeBot). Standard library only.

On Telegram each hour also brings Hindi news drafts (title + 80-100 word description) per trend,
written by GitHub Models (free, via the workflow's GITHUB_TOKEN) from Google News headlines.

Usage:
  python trends_bot.py --dry-run   # print the messages, don't send, don't save state
  python trends_bot.py --chat-id   # print your Telegram chat id
  python trends_bot.py             # send
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

SOURCE_URL = "https://trends24.in/india/"
STATE_FILE = os.environ.get("STATE_FILE", "state/last.json")
TOP_N = int(os.environ.get("TOP_N", "10"))
CLIMB = 3  # places gained since last hour to earn a ⬆️
IST = timezone(timedelta(hours=5, minutes=30))
MODEL = os.environ.get("MODEL", "openai/gpt-4.1-mini")
MODELS_URL = "https://models.github.ai/inference/chat/completions"
HEADLINES_PER_TREND = 3
AI_BATCH = 5  # topics per model call (keeps each reply under the free tier's output cap)
TELEGRAM_LIMIT = 3900  # Telegram max is 4096 chars per message

DRAFT_PROMPT = """You assist a Hindi news desk in India. You get X (Twitter) topics trending in India right now, \
each with the latest news headlines found for it (possibly empty or unrelated).
For every topic write, in Hindi (Devanagari):
- "title": a publishable news headline, max 15 words
- "description": a news description of 80-100 words
Rules:
- Use ONLY facts stated in the given headlines. Never invent names, numbers, quotes, dates or events.
- If the headlines are empty or don't clearly explain why the topic is trending, set "verified": false, \
make the title "<topic>: X पर ट्रेंड, वजह अभी साफ नहीं" and in the description say neutrally what is known and \
what the desk should check. Do not guess.
- Otherwise set "verified": true.
Reply with JSON only: {"items": [{"rank": <rank>, "title": "...", "description": "...", "verified": true}]}"""


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


def env(name):
    """Env var with stray quotes/spaces removed (cmd's `set X="..."` keeps the quotes)."""
    return os.environ.get(name, "").strip().strip("\"'").strip()


def telegram_api(method, data=None):
    token = env("TELEGRAM_BOT_TOKEN") or sys.exit("Set TELEGRAM_BOT_TOKEN first")
    if not re.fullmatch(r"\d+:[\w-]{30,}", token):
        sys.exit("TELEGRAM_BOT_TOKEN looks wrong — it must be the full '1234567890:AA...' token from BotFather")
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        hint = {401: "token is wrong or was revoked", 404: "token is wrong or incomplete",
                400: "chat id is wrong, or you haven't pressed Start in your bot"}.get(e.code, "")
        sys.exit(f"Telegram error {e.code}: {hint}")


def send_telegram(text):
    chat_id = env("TELEGRAM_CHAT_ID") or sys.exit("Set TELEGRAM_CHAT_ID (run: python trends_bot.py --chat-id)")
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    print("Telegram:", telegram_api("sendMessage", data).get("ok"))


def print_chat_ids():
    """After you message your bot once, this prints your chat id."""
    updates = telegram_api("getUpdates")["result"]
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "")
             for u in updates if "message" in u}
    print(chats or "No messages yet — send your bot any message (e.g. hi) and run again")


def headlines_for(topic):
    """Latest (last 24h) Google News headlines for a trend: [{title, source, link}]."""
    q = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", topic.replace("#", "").replace("_", " ")).strip()
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{q} when:1d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    try:
        root = ET.fromstring(fetch(url))
    except Exception as e:
        print(f"News lookup failed for {topic!r}: {e}")
        return []
    return [{"title": it.findtext("title", ""), "source": it.findtext("source", ""),
             "link": it.findtext("link", "")} for it in root.iter("item")][:HEADLINES_PER_TREND]


def ai_drafts(batch):
    """One GitHub Models call for a batch of topics -> {rank: item}. Empty on any failure."""
    body = json.dumps({"model": MODEL, "temperature": 0.3, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": DRAFT_PROMPT},
                                    {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}]}).encode()
    req = urllib.request.Request(MODELS_URL, body, {"Authorization": f"Bearer {env('GITHUB_TOKEN')}",
                                                    "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            content = json.load(r)["choices"][0]["message"]["content"]
        items = json.loads(content[content.find("{"):content.rfind("}") + 1])["items"]
        return {int(it["rank"]): it for it in items}
    except urllib.error.HTTPError as e:
        hint = {401: "token missing models permission", 403: "GitHub Models is disabled for this org/repo",
                429: "free rate limit hit"}.get(e.code, "")
        print(f"GitHub Models error {e.code}: {hint}")
    except Exception as e:
        print(f"GitHub Models reply unusable: {e}")
    return {}


def draft_messages(trends):
    """Telegram messages with a Hindi title + description per trend, split under the size limit."""
    news = [headlines_for(t["name"]) for t in trends]
    drafts = {}
    if env("GITHUB_TOKEN"):
        for start in range(0, len(trends), AI_BATCH):
            batch = [{"rank": r, "topic": trends[r - 1]["name"], "headlines": [n["title"] for n in news[r - 1]]}
                     for r in range(start + 1, min(start + AI_BATCH, len(trends)) + 1)]
            drafts.update(ai_drafts(batch))
    else:
        print("(GITHUB_TOKEN not set, AI drafts skipped)")
    if not drafts:
        return []
    blocks = []
    for rank, t in enumerate(trends, 1):
        d = drafts.get(rank)
        if d:
            mark = "" if d.get("verified") else "⚠️ "
            block = f"<b>{rank}. {mark}{html.escape(d.get('title', ''))}</b>\n{html.escape(d.get('description', ''))}"
        else:
            block = f"<b>{rank}. {html.escape(t['name'])}</b>\n<i>ड्राफ्ट नहीं बन पाया</i>"
        if news[rank - 1]:
            src = news[rank - 1][0]
            block += f'\n🔗 <a href="{html.escape(src["link"])}">{html.escape(src["source"] or "source")}</a>'
        blocks.append(block)
    messages = ["<b>📝 न्यूज़ ड्राफ्ट</b> — <i>AI ड्राफ्ट है, पब्लिश से पहले सोर्स से पुष्टि करें। ⚠️ = वजह पुष्ट नहीं</i>"]
    for block in blocks:
        if len(messages[-1]) + len(block) + 2 > TELEGRAM_LIMIT:
            messages.append(block)
        else:
            messages[-1] += "\n\n" + block
    return messages


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
    telegram = bool(env("TELEGRAM_BOT_TOKEN"))
    trends = latest_trends(fetch(SOURCE_URL))
    message = build_message(trends, load_previous(), TELEGRAM if telegram else WHATSAPP)
    print(message)
    drafts = draft_messages(trends) if telegram or dry_run else []
    for d in drafts:
        print("\n" + d)
    if dry_run:
        return
    if telegram:
        for text in [message] + drafts:
            send_telegram(text)
    else:
        send_whatsapp(message)
    save_state(trends)


if __name__ == "__main__":
    main()
