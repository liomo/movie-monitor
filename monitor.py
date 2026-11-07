"""Monitor configured public cinema schedule pages for Dune IMAX mentions."""
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "cinemas.json"
STATE = ROOT / "state.json"

def send_wechat(items):
    key = os.getenv("SERVERCHAN_SENDKEY", "").strip()
    if not key:
        print("SERVERCHAN_SENDKEY not configured; notification skipped")
        return False
    body = "\n\n".join(f"- {name}: {url}" for name, url in items)
    body += "\n\n注意：仅检测到网页关键词，不代表已确认放票或可购买。请前往售票平台核实。"
    if key.startswith("sctp"):
        match = re.match(r"^sctp(\d+)t", key)
        if not match:
            raise ValueError("Invalid ServerChan3 key format")
        endpoint = f"https://{match.group(1)}.push.ft07.com/send/{key}.send"
    elif key.startswith("SCT"):
        endpoint = f"https://sctapi.ftqq.com/{key}.send"
    else:
        raise ValueError("Unsupported ServerChan key prefix")
    response = requests.post(
        endpoint,
        data={"title": "沙丘3 IMAX 排片线索", "desp": body},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"ServerChan notification failed: {result.get('message', 'unknown')}")
    return True

def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    old = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    new = dict(old)
    found = []
    checked = 0
    for cinema in cfg["cinemas"]:
        name = cinema["name"]
        url = cinema.get("url", "").strip()
        if not url:
            print(f"SKIP {name}: configure a verified public schedule URL")
            continue
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            print(f"SKIP {name}: URL must be HTTPS")
            continue
        try:
            response = requests.get(url, timeout=20, headers={"User-Agent": "MovieMonitor/1.0"})
            response.raise_for_status()
            content = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.text))
            keywords = cinema.get("keywords", cfg["keywords"])
            matched = all(re.search(re.escape(k), content, re.I) for k in keywords)
            checked += 1
            if matched and not old.get(name, {}).get("matched", False):
                found.append((name, url))
            new[name] = {"matched": matched, "checked_at": datetime.now(timezone.utc).isoformat()}
            print(f"{name}: keyword_match={matched}")
            time.sleep(1)
        except requests.RequestException as exc:
            print(f"ERROR {name}: {exc}")
    # Do not mark a notification as delivered if sending failed.
    if found:
        if not send_wechat(found):
            for name, _ in found:
                new[name] = old.get(name, {"matched": False})
    STATE.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Checked {checked} pages; {len(found)} new signals")

if __name__ == "__main__":
    main()
