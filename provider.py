"""Jisu movie API adapter. Coverage/freshness must be validated before enabling."""
import re
from datetime import datetime
from urllib.parse import urlparse

import requests


class SourceError(RuntimeError):
    pass


class Jisu:
    def __init__(self, key):
        if not key:
            raise SourceError("missing JISU_API_KEY; no cinema data fetched")
        self.key = key
        self.session = requests.Session()
        self.calls = 0

    def call(self, endpoint, **params):
        self.calls += 1
        # No retries: each request may consume quota. Never log a keyed URL.
        try:
            response = self.session.get(
                f"https://api.jisuapi.com/movie/{endpoint}",
                params={**params, "appkey": self.key}, timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            raise SourceError("provider HTTP/JSON request failed (URL redacted)") from None
        if not isinstance(data, dict) or str(data.get("status")) != "0":
            status = data.get("status") if isinstance(data, dict) else "invalid"
            # Provider error messages can echo credentials; only retain numeric codes.
            code = str(status) if re.fullmatch(r"\d+", str(status)) else "invalid"
            raise SourceError(f"provider returned error code {code}")
        result = data.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("list"), list):
            raise SourceError("provider schema changed: expected result.list")
        return result

    def discover(self):
        return self.call("theater", city="上海")["list"]

    def schedule(self, theater_id, day):
        result = self.call("theatermovie", theaterid=theater_id, date=day)
        if str(result.get("theaterid")) != str(theater_id) or result.get("date") != day:
            raise SourceError("provider returned a different cinema/date")
        return result


def normalized(value):
    return re.sub(r"[\W_]+", "", str(value), flags=re.UNICODE).casefold()


def discover_candidates(cinema, rows):
    # Candidate discovery only: never assume IDs are shared with Maoyan.
    tokens = [normalized(x) for x in cinema["lookup_tokens"]]
    return [{k: row.get(k, "") for k in ("theaterid", "theatername", "address", "city")}
            for row in rows if isinstance(row, dict)
            and all(t in normalized(row.get("theatername", "")) for t in tokens)]


def parse_shows(result, cinema, target_titles, now):
    """Keep every movie for diagnostics; target matches are scoped to each row."""
    day = result["date"]
    aliases = {normalized(x) for x in target_titles}
    shows = []
    for movie in result["list"]:
        if not isinstance(movie, dict) or "moviename" not in movie:
            raise SourceError("invalid movie row")
        rows = movie.get("showlist")
        if not isinstance(rows, list):
            raise SourceError("provider schema changed: expected movie.showlist")
        for row in rows:
            if not isinstance(row, dict):
                raise SourceError("invalid show row")
            start = str(row.get("starttime", ""))
            if not re.fullmatch(r"\d{2}:\d{2}", start):
                raise SourceError("invalid show starttime")
            try:
                stamp = datetime.fromisoformat(f"{day}T{start}").replace(tzinfo=now.tzinfo)
            except ValueError:
                raise SourceError("invalid show date/time") from None
            hall = str(row.get("hallname", ""))
            screen = str(row.get("screentype", ""))
            # Only a show-specific hall/format can establish IMAX.
            imax = bool(re.search(r"\bIMAX\b|IMAX(?=[23]D)", f"{hall} {screen}", re.I))
            url = str(row.get("ticketurl", ""))
            if urlparse(url).scheme not in ("https", "http"):
                url = ""
            shows.append({
                "cinema": cinema["name"], "theater_id": str(result["theaterid"]),
                "movie": movie["moviename"], "movie_id": str(movie.get("movieid", "")),
                "date": day, "start": start, "hall": hall, "format": screen,
                "imax": imax, "target": normalized(movie["moviename"]) in aliases,
                "sale": str(row.get("issale", "")) == "1", "future": stamp > now,
                "url": url or cinema["url"],
            })
    return shows


def show_key(show):
    # Sale status and ticket URL intentionally excluded, so status changes can be detected.
    return "|".join(str(show[k]) for k in ("theater_id", "movie_id", "movie", "date", "start", "hall", "format"))
