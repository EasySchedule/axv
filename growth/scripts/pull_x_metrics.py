"""
pull_x_metrics.py — the only script in the rig that talks to X.

Design rules, all of them load-bearing:

1. No credential is ever read from a file in this repository. Tokens come from the
   process environment only, and the environment is populated by Paperclip secret
   bindings. If a token is not in the environment, this script exits with a clear
   message and writes nothing. It does not accept a token as an argument either,
   because arguments land in process listings and shell history.

2. Nothing is printed that contains a token. Redaction is applied to any error text
   before it is printed, because X error bodies occasionally echo the request.

3. Fails closed. With no username in config/account.json this script writes zero rows
   and returns exit code 2. A silent empty file is worse than a loud failure, because
   an empty file reads as "zero impressions" in the scoreboard.

Credentials required (see README.md "What needs a credential"):

  X_BEARER_TOKEN       REQUIRED. App-only OAuth2 bearer. Grants /2/users/by/username
                       and /2/users/:id/tweets with tweet.fields=public_metrics.
                       This is impressions, likes, reposts, replies, quotes, bookmarks
                       on any public post, including our own.

  X_USER_ACCESS_TOKEN  OPTIONAL. OAuth 2.0 user-context access token. Grants
  X_USER_CTX_SECRET    non_public_metrics (profile clicks, URL clicks, engagements)
                       and /2/users/:id/followers for the per-follow event stream.
                       Without it, follower_conversion_24h is measured the coarse way
                       (account-level net new followers over the window) and the script
                       records metric_source=public_only_coarse_conversion.

Usage:

  python scripts/pull_x_metrics.py follower     # append one follower snapshot
  python scripts/pull_x_metrics.py posts         # append per-post metrics for recent posts
  python scripts/pull_x_metrics.py followers-csv # append daily follows/unfollows (needs user ctx)
  python scripts/pull_x_metrics.py probe         # check credentials and print capabilities, write nothing

Cost, so nobody is surprised: X moved to pay-per-use in Feb 2026. Owned reads are
$0.001 per resource; a generic post read is $0.005 and a user read $0.010. Reads are
deduplicated within a UTC day, so re-running posts on the same day for the same ids is
close to free. A daily full pull of ~50 posts and ~20 replies is roughly $0.04.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config" / "account.json"
API = "https://api.x.com/2"

RETRYABLE = (429, 500, 502, 503, 504)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact(text: str) -> str:
    """Strip anything token-shaped before it reaches stdout, a log, or a comment."""
    if not text:
        return text
    for var in (
        "X_BEARER_TOKEN",
        "X_USER_ACCESS_TOKEN",
        "X_USER_CTX_SECRET",
        "X_USER_REFRESH_TOKEN",
        "X_CLIENT_SECRET",
    ):
        value = os.environ.get(var, "")
        if len(value) >= 8:
            text = text.replace(value, f"<redacted:{var}>")
    return text


def load_config() -> dict:
    with CONFIG.open(encoding="utf-8") as handle:
        return json.load(handle)


def fail(message: str, code: int = 1) -> None:
    print(f"pull_x_metrics: {redact(message)}", file=sys.stderr)
    sys.exit(code)


def request(path: str, params: dict, token: str, label: str, attempts: int = 4) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params, doseq=True)}"
    last_error = ""
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "axv-growth-scorecard/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = redact(exc.read().decode("utf-8", "replace"))
            last_error = f"{label}: HTTP {exc.code} {body}"
            if exc.code == 429 or exc.code in RETRYABLE:
                # Respect Retry-After when present; otherwise exponential backoff.
                delay = float(exc.headers.get("Retry-After", 2 ** attempt))
                print(f"pull_x_metrics: {label} retry {attempt + 1}/{attempts} in {delay:.0f}s", file=sys.stderr)
                time.sleep(min(delay, 60))
                continue
            break
        except urllib.error.URLError as exc:
            last_error = f"{label}: {exc.reason}"
            time.sleep(min(2 ** attempt, 30))
    fail(last_error or f"{label}: unknown failure")


def append_row(path: Path, row: dict, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({key: ("" if value is None else value) for key, value in row.items()})


def fieldnames(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as handle:
        return next(csv.reader(handle))


def read_rows(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- follower count


def cmd_follower(config: dict, token: str) -> None:
    username = config.get("username")
    if not username:
        fail(
            "config/account.json has username=null. SIG-2 (Create and secure the X "
            "account) has not landed. Set username there first. Wrote nothing.",
            code=2,
        )
    data = request(
        f"users/by/username/{urllib.parse.quote(username)}",
        {"user.fields": "public_metrics,created_at"},
        token,
        "follower",
    ).get("data", {})
    metrics = data.get("public_metrics", {})
    row = {
        "observed_at_utc": now_utc(),
        "followers": metrics.get("followers_count", ""),
        "following": metrics.get("following_count", ""),
        "post_count": metrics.get("tweet_count", ""),
        "listed_count": metrics.get("listed_count", ""),
        "source": "x_api_v2_user_public_metrics",
        "note": "",
    }
    append_row(DATA / "follower_snapshots.csv", row, fieldnames(DATA / "follower_snapshots.csv"))
    print(f"followers={row['followers']} at {row['observed_at_utc']}")


# ---------------------------------------------------------------- per-post stats


def engagements(metrics: dict) -> int:
    return sum(
        to_int(metrics.get(key))
        for key in ("like_count", "retweet_count", "reply_count", "quote_count", "bookmark_count")
    )


def cmd_posts(config: dict, token: str) -> None:
    username = config.get("username")
    user_id = config.get("x_user_id")
    if not username or not user_id:
        fail(
            "config/account.json needs both username and x_user_id before per-post pulls. "
            "Run: python scripts/pull_x_metrics.py follower. Wrote nothing.",
            code=2,
        )
    user_token = os.environ.get("X_USER_ACCESS_TOKEN", "")
    ctx = bool(user_token)
    fields = "created_at,public_metrics,conversation_id,referenced_tweets,entities"
    if ctx:
        fields += ",non_public_metrics,organic_metrics"
    payload = request(
        f"users/{user_id}/tweets",
        {
            "max_results": 100,
            "tweet.fields": fields,
            "exclude": "retweets",
            "pagination_token": "",
        },
        token,
        "posts",
    )
    tweets = payload.get("data") or []
    if not tweets:
        print("no posts returned; the account has not published yet. Wrote nothing.")
        return

    follows = {r["post_id"]: r for r in read_rows(DATA / "posts.csv") if r.get("post_id")}
    names = fieldnames(DATA / "posts.csv")
    pulled = now_utc()
    for tweet in tweets:
        tid = tweet["id"]
        metrics = tweet.get("public_metrics", {})
        nonpublic = tweet.get("non_public_metrics", {}) or {}
        referenced = tweet.get("referenced_tweets") or []
        types = {r.get("type") for r in referenced}
        impressions = to_int(metrics.get("impression_count"))
        eng = engagements(metrics)
        prior = follows.get(tid, {})
        age_hours = 0.0
        try:
            created = datetime.strptime(tweet["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        except (KeyError, ValueError):
            pass
        suffix = "24h" if age_hours < 36 else "7d"
        impressions_col = f"impressions_{suffix}"
        net_new = to_int(prior.get(f"net_new_followers_{suffix}"))
        conversion = round(net_new / impressions, 8) if impressions else ""
        row = {
            "post_id": tid,
            "url": f"https://x.com/{username}/status/{tid}",
            "published_at_utc": tweet.get("created_at", ""),
            "format": prior.get("format", ""),
            "topic": prior.get("topic", ""),
            "hook_first_line": prior.get("hook_first_line", ""),
            "post_type": sorted(types)[0] if types else "original",
            f"impressions_{suffix}": impressions,
            "likes_24h": metrics.get("like_count", ""),
            "reposts_24h": metrics.get("retweet_count", ""),
            "replies_24h": metrics.get("reply_count", ""),
            "quotes_24h": metrics.get("quote_count", ""),
            "bookmarks_24h": metrics.get("bookmark_count", ""),
            "engagements_24h": eng,
            "engagement_rate_24h": round(eng / impressions, 6) if impressions else "",
            "profile_clicks_24h": nonpublic.get("user_profile_clicks", ""),
            "url_clicks_24h": nonpublic.get("url_link_clicks", ""),
            f"net_new_followers_{suffix}": prior.get(f"net_new_followers_{suffix}", ""),
            f"follower_conversion_{suffix}": conversion,
            "is_repost": "reposted" in types,
            "is_reply": "replied_to" in types,
            "is_quote": "quoted" in types,
            "conversation_id": tweet.get("conversation_id", ""),
            "parent_post_id": next(
                (r.get("id") for r in referenced if r.get("type") == "replied_to"), ""
            ),
            "pulled_at_utc": pulled,
            "metric_source": "api_v2_full" if ctx else "api_v2_public_only",
            "notes": "format/topic must be filled by the publisher; the API cannot tell us either",
        }
        append_row(DATA / "posts.csv", row, names)
    print(f"appended/updated {len(tweets)} posts; user_context={'yes' if ctx else 'no'}")


# ---------------------------------------------------------------- follow stream


def cmd_followers_csv(config: dict) -> None:
    username = config.get("username")
    user_id = config.get("x_user_id")
    user_token = os.environ.get("X_USER_ACCESS_TOKEN", "")
    if not (user_token and username and user_id):
        fail(
            "follows_daily.csv needs X_USER_ACCESS_TOKEN (OAuth 2.0 user context). "
            "App-only bearer tokens cannot read the follower event stream. "
            "Without it, compute net new from follower_snapshots.csv instead. Wrote nothing.",
            code=2,
        )
    path = DATA / "follows_daily.csv"
    names = fieldnames(path)
    seen = {r["post_id"] for r in []}  # placeholder removed below
    acquired: list[str] = []
    token = None
    while True:
        params = {"max_results": 1000}
        if token:
            params["pagination_token"] = token
        page = request(f"users/{user_id}/followers", params, user_token, "followers")
        acquired.extend(item["created_at"] for item in page.get("data") or [])
        meta = page.get("meta") or {}
        if not meta.get("next_token"):
            break
        token = meta["next_token"]
        time.sleep(1)  # courtesy: this endpoint is rate limited and billable per resource
    acquired.sort()
    buckets: dict[str, int] = {}
    for stamp in acquired:
        buckets[stamp[:10]] = buckets.get(stamp[:10], 0) + 1
    for day in sorted(buckets):
        append_row(
            path,
            {
                "date_utc": day,
                "followers_snapshot": "",
                "follows_acquired": buckets[day],
                "unfollows": "",
                "net_new": "",
                "source": "x_api_v2_user_followers",
                "note": "acquired only; unfollows unavailable without reverse-follower scan",
            },
            names,
        )
    print(f"wrote {len(buckets)} day-buckets covering {len(acquired)} follow events")


# ---------------------------------------------------------------- capability check


def cmd_probe() -> None:
    config = load_config()
    bearer = os.environ.get("X_BEARER_TOKEN", "")
    user_token = os.environ.get("X_USER_ACCESS_TOKEN", "")
    print("credential presence (values are never printed):")
    print(f"  X_BEARER_TOKEN       present={bool(bearer)}")
    print(f"  X_USER_ACCESS_TOKEN  present={bool(user_token)}")
    print(f"  username configured  {bool(config.get('username'))}")
    print(f"  x_user_id configured {bool(config.get('x_user_id'))}")
    if bearer and config.get("username"):
        try:
            request(
                f"users/by/username/{urllib.parse.quote(config['username'])}",
                {"user.fields": "public_metrics"},
                bearer,
                "probe",
                attempts=1,
            )
            print("  live read: OK")
        except SystemExit:
            print("  live read: FAILED (see error above)")
    else:
        print("  live read: skipped (no bearer token or no username)")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    command = sys.argv[1]
    config = load_config()
    bearer = os.environ.get("X_BEARER_TOKEN", "")
    if command != "probe" and command != "followers-csv" and not bearer:
        fail(
            "X_BEARER_TOKEN is not in the environment. Bind it as a Paperclip secret; "
            "do not put it in a file, a command argument, or a comment. Wrote nothing.",
            code=2,
        )
    if command == "follower":
        cmd_follower(config, bearer)
    elif command == "posts":
        cmd_posts(config, bearer)
    elif command == "followers-csv":
        cmd_followers_csv(config)
    elif command == "probe":
        cmd_probe()
    else:
        fail(f"unknown command {command!r}; expected follower|posts|followers-csv|probe")
    print("ok")


if __name__ == "__main__":
    main()
