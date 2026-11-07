"""Monitor structured showtimes after provider coverage has been reviewed."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
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
    body += "\n\n以上为数据源报告的新增可售 IMAX 场次，请在购票平台核实当前余票。"
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
        data={"title": "沙丘3 IMAX 场次提醒", "desp": body},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"ServerChan notification failed: {result.get('message', 'unknown')}")
    return True


def run(probe=False):
    from datetime import date
    from zoneinfo import ZoneInfo
    from provider import Jisu, SourceError, discover_candidates, parse_shows, show_key

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    report = {"checked_at": now.isoformat(), "provider": "jisu", "mode": "probe" if probe else "monitor",
              "status": "unavailable", "cinemas": [], "requests": 0,
              "freshness": "Provider has no documented source update timestamp; latency unverified"}
    report_file = ROOT / "source_report.json"
    def finish(status, code):
        report["status"] = status
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Data source: {status}; requests={report['requests']}. See source_report.json")
        return code

    if not probe and os.getenv("LIVE_MONITOR_ENABLED", "").lower() != "true":
        report["reason"] = "Live calls disabled until trial coverage is reviewed"
        return finish("not_enabled", 0)
    try:
        api = Jisu(os.getenv("JISU_API_KEY", "").strip())
    except SourceError as exc:
        report["reason"] = str(exc)
        return finish("missing_credentials", 2)
    dates = cfg.get("monitor_dates", [])
    if not dates or len(dates) > 7:
        report["reason"] = "Configure 1-7 explicit monitor_dates"
        return finish("invalid_config", 2)
    for day in dates:
        date.fromisoformat(day)
    dates = [d for d in dates if d >= now.date().isoformat()]
    if not dates:
        report["reason"] = "All monitor_dates have passed; no requests made"
        return finish("expired_dates", 2)
    old = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    seen = old.get("notified_shows", {})
    pending = []
    failures = 0
    try:
        candidates = api.discover() if probe else []
    except SourceError as exc:
        report["reason"] = str(exc)
        report["requests"] = api.calls
        return finish("discovery_failed", 2)
    for cinema in cfg["cinemas"]:
        item = {"name": cinema["name"], "dates": []}
        report["cinemas"].append(item)
        theater_id = str(cinema.get("jisu_theater_id", "")).strip()
        if probe:
            options = discover_candidates(cinema, candidates)
            item["candidates"] = options
            if not theater_id and len(options) == 1:
                theater_id = str(options[0]["theaterid"])
                item["identity"] = "unique candidate; must review name/address before saving mapping"
        if not theater_id:
            item["status"] = "unmapped_or_ambiguous"
            failures += 1
            continue
        # Probe today's actual listings as a positive control, plus watched dates.
        query_dates = sorted(set(([now.date().isoformat()] if probe else []) + dates))
        for day in query_dates:
            entry = {"date": day}
            item["dates"].append(entry)
            try:
                result = api.schedule(theater_id, day)
                if not probe:
                    expected_name = cinema.get("jisu_verified_name", "")
                    if not expected_name or result.get("theatername") != expected_name:
                        raise SourceError("cinema name mismatch or identity not reviewed")
                shows = parse_shows(result, cinema, cfg["target_titles"], now)
                matches = [s for s in shows if s["target"] and s["imax"] and s["future"]]
                entry.update({"status": "received" if shows else "empty_unverified",
                              "theater_id": theater_id, "provider_name": result.get("theatername", ""),
                              "show_count": len(shows), "imax_count": sum(s["imax"] for s in shows),
                              "target_imax": matches,
                              "sample": shows[:3] if day == now.date().isoformat() else []})
                if not shows:
                    # Empty data is not proof that the cinema hasn't released tickets.
                    failures += 1
                if not probe:
                    for show in matches:
                        if show["sale"] and show_key(show) not in seen:
                            pending.append(show)
            except SourceError as exc:
                entry.update({"status": "error", "reason": str(exc)})
                failures += 1
    report["requests"] = api.calls
    pending = list({show_key(s): s for s in pending}.values())
    if pending:
        entries = [(f"{s['cinema']} / {s['movie']} / {s['date']} {s['start']} / {s['hall']}", s["url"]) for s in pending]
        try:
            delivered = send_wechat(entries)
        except Exception:
            # Never expose exception strings containing notification keys.
            delivered = False
            print("Notification failed; new shows will be retried")
        if delivered:
            for show in pending:
                seen[show_key(show)] = {"date": show["date"], "notified_at": now.isoformat()}
        else:
            failures += 1
    if not probe:
        # Preserve deduplication through empty/error responses. Prune only expired shows.
        state = {"notified_shows": {k: v for k, v in seen.items() if v["date"] >= now.date().isoformat()}}
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return finish("probe_complete" if probe and not failures else
                  "healthy" if not failures else "incomplete_coverage", 0 if not failures else 2)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="Inspect coverage without sending or altering notification state")
    args = parser.parse_args()
    raise SystemExit(run(args.probe))

