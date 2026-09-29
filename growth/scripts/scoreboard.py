"""
scoreboard.py — build the format, topic, and channel scoreboards from posts.csv.

Medians, never means. The reason is not pedantry: post-level impressions on X are
heavy-tailed enough that a single breakout can lift a mean by 10x while the median
post is dead. The mean then reports the opposite of the truth about the format.

Every row carries p25/p75/max next to the median. A median with a tight spread and a
median with a 200x tail are different decisions, and the distribution is what makes
the difference legible.

Engagement rate        = (likes + reposts + replies + quotes + bookmarks) / impressions
Follower conversion    = net new followers attributed to the post / impressions
Company median         = median of the per-post conversion values across ALL formats,
                         not the mean of the format medians. The mean-of-medians is
                         biased toward small formats.

Kill eligibility is NOT computed here. It is computed in kill_gate.py, which applies
the noise floor. See SCHEMA.md.

Usage:
  python scripts/scoreboard.py                 # print tables
  python scripts/scoreboard.py --write         # rewrite the three scoreboard CSVs
  python scripts/scoreboard.py --as-of 7d      # use the 7d columns instead of 24h
"""

from __future__ import annotations

import csv
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

FORMATS = [
    "one-claim", "number", "contrarian", "build-in-public", "thread",
    "chart", "quote-tweet", "reply", "off-platform-pointer",
]
TOPICS = [
    "model-releases", "agent-frameworks", "benchmarks", "funding", "policy",
    "build-in-public", "opinion", "off-platform-curation",
]


def read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def to_float(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def age_hours(row: dict) -> float | None:
    stamp = row.get("published_at_utc", "")
    if not stamp:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            created = datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - created).total_seconds() / 3600
        except ValueError:
            continue
    return None


def mature(rows: list[dict], window: str) -> list[dict]:
    """Only posts old enough for the requested measurement window to be meaningful."""
    cutoff = 30 if window == "24h" else 168
    out = []
    for row in rows:
        age = age_hours(row)
        if age is None or age < cutoff:
            continue
        impressions = to_float(row.get(f"impressions_{window}"))
        if impressions is None or impressions <= 0:
            continue
        out.append(row)
    return out


def derived(row: dict, window: str) -> dict:
    impressions = to_float(row.get(f"impressions_{window}")) or 0.0
    engagements = sum(
        to_float(row.get(key)) or 0.0
        for key in ("likes_24h", "reposts_24h", "replies_24h", "quotes_24h", "bookmarks_24h")
    )
    net_new = to_float(row.get(f"net_new_followers_{window}")) or 0.0
    return {
        "impressions": impressions,
        "engagement_rate": (engagements / impressions) if impressions else None,
        "conversion": (net_new / impressions) if impressions else None,
        "net_new": net_new,
    }


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    low, high = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def company_median(rows: list[dict], window: str) -> float | None:
    conversions = [c for c in (derived(r, window)["conversion"] for r in rows) if c is not None]
    return statistics.median(conversions) if conversions else None


def group_scoreboard(rows: list[dict], key: str, order: list[str], window: str) -> list[dict]:
    company = company_median(rows, window)
    out = []
    for name in order:
        arm = [r for r in rows if (r.get(key) or "").strip() == name]
        stats = [derived(r, window) for r in arm]
        impressions = [s["impressions"] for s in stats]
        rates = [s["engagement_rate"] for s in stats if s["engagement_rate"] is not None]
        conversions = [s["conversion"] for s in stats if s["conversion"] is not None]
        net_new = [s["net_new"] for s in stats]
        total_impressions = sum(impressions)
        total_net_new = sum(net_new)
        median_conversion = statistics.median(conversions) if conversions else None
        if median_conversion is None or company in (None, 0):
            verdict = ""
        elif median_conversion < company:
            verdict = "below"
        elif median_conversion > company:
            verdict = "above"
        else:
            verdict = "at"
        out.append(
            {
                key: name,
                "posts_shipped": len(arm),
                f"median_impressions_{window}": round(statistics.median(impressions), 1) if impressions else "",
                f"p25_impressions_{window}": round(percentile(impressions, 0.25), 1) if impressions else "",
                f"p75_impressions_{window}": round(percentile(impressions, 0.75), 1) if impressions else "",
                f"max_impressions_{window}": int(max(impressions)) if impressions else "",
                f"median_engagement_rate_{window}": round(statistics.median(rates), 6) if rates else "",
                f"median_follower_conversion_{window}": round(median_conversion, 8) if median_conversion is not None else "",
                f"median_net_new_{window}": round(statistics.median(net_new), 1) if net_new else "",
                f"total_impressions_{window}": int(total_impressions),
                f"total_net_new_{window}": int(total_net_new),
                f"weighted_conversion_{window}": round(total_net_new / total_impressions, 8) if total_impressions else "",
                f"company_median_conversion_{window}": round(company, 8) if company is not None else "",
                f"vs_company_median": verdict,
                # NEVER auto-fills kill_eligible. kill_gate.py owns that column, and
                # only after the noise floor says the difference is real.
                "kill_eligible": "",
                "week_of": datetime.now(timezone.utc).strftime("%G-W%V"),
            }
        )
    return out


def channel_scoreboard(window_hours: int = 48) -> list[dict]:
    rows = read_csv(DATA / "channel_scoreboard.csv")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    out = []
    for row in rows:
        try:
            shipped = datetime.strptime(row["shipped_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if shipped > cutoff:
            continue
        impressions = to_float(row.get("impressions_48h")) or 0.0
        net_new = to_float(row.get("net_new_followers_48h")) or 0.0
        out.append(
            {
                **row,
                "conversion_48h": round(net_new / impressions, 8) if impressions else "",
                "verdict": row.get("verdict", ""),
            }
        )
    return out


def render(name: str, rows: list[dict], window: str) -> str:
    if not rows or all(r.get("posts_shipped") == 0 for r in rows):
        return f"{name.upper()} (T+{window})\n  no shipped posts yet. Schema is fixed; rows append on first ship.\n"
    head = (
        f"{'name':<22}{'n':>4}{'med impr':>11}{'p25':>9}{'p75':>10}{'max':>10}"
        f"{'med eng%':>11}{'med conv%':>12}{'vs co':>7}"
    )
    lines = [f"{name.upper()} (T+{window})", head, "-" * len(head)]
    for r in rows:
        def num(key: str) -> float:
            """CSV round-trips turn '' into a string. Treat blank as zero, never crash."""
            try:
                return float(r.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        label = r.get("format") or r.get("topic") or r.get("channel", "")
        lines.append(
            f"{label:<22}"
            f"{r.get('posts_shipped', 0) or 0:>4}"
            f"{num(f'median_impressions_{window}'):>11,.0f}"
            f"{num(f'p25_impressions_{window}'):>9,.0f}"
            f"{num(f'p75_impressions_{window}'):>10,.0f}"
            f"{num(f'max_impressions_{window}'):>10,.0f}"
            f"{num(f'median_engagement_rate_{window}') * 100:>11.2f}"
            f"{num(f'median_follower_conversion_{window}') * 100:>12.4f}"
            f"{r.get('vs_company_median', ''):>7}"
        )
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open(encoding="utf-8") as handle:
        existing = next(csv.reader(handle), [])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=existing, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    window = "24h"
    if "--as-of" in sys.argv:
        idx = sys.argv.index("--as-of")
        window = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "24h"
    write = "--write" in sys.argv
    window = "24h" if window not in ("24h", "7d") else window

    all_rows = read_csv(DATA / "posts.csv")
    usable = mature(all_rows, window)
    formats = group_scoreboard(usable, "format", FORMATS, window)
    topics = group_scoreboard(usable, "topic", TOPICS, window)
    channels = channel_scoreboard()

    print(f"posts on file: {len(all_rows)}   mature at T+{window}: {len(usable)}")
    print(render("format scoreboard", formats, window))
    print(render("topic scoreboard", topics, window))
    if channels:
        print(f"CHANNEL SCOREBOARD (48h)\n  {len(channels)} channel touches measured\n")
    else:
        print("CHANNEL SCOREBOARD (48h)\n  no off-platform touches logged yet\n")

    if write:
        write_csv(DATA / "format_scoreboard.csv", formats)
        write_csv(DATA / "topic_scoreboard.csv", topics)
        if channels:
            write_csv(DATA / "channel_scoreboard.csv", channels)
        print("wrote format_scoreboard.csv, topic_scoreboard.csv"
              + (", channel_scoreboard.csv" if channels else ""))


if __name__ == "__main__":
    main()
