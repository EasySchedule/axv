"""
velocity_model.py — the headline model, recomputed from snapshots.

  current_followers = F
  net_new_7d        = sum of daily net_new over the last 7 complete days
  velocity_per_day  = net_new_7d / 7
  projected_day_90  = F + velocity_per_day * 90
  gap_to_target     = target - projected_day_90
  run_rate_vs_target= projected_day_90 / target

Read from data/follower_snapshots.csv (authoritative follower count) and
data/follows_daily.csv (per-day net new, when user context is available). If the
daily file is empty it falls back to snapshot deltas, which is coarser: a snapshot
taken 7 days ago gives net_new_7d directly, but only if the snapshot exists.

It also reports the noise floor attached to the velocity number, because a velocity
computed from one noisy day is not a velocity. See noise_floor.py.

Usage: python scripts/velocity_model.py [--json]
"""

from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config" / "account.json"

HORIZON = 90
TARGET = 1_000_000


def read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse(ts: str):
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def to_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def current_followers(snapshots: list[dict]):
    """Latest snapshot that actually has a follower count. Returns (count, when, note)."""
    usable = [s for s in snapshots if s.get("followers") not in (None, "", "None")]
    if not usable:
        return None, None, "no follower snapshot on file; the account does not exist yet"
    usable.sort(key=lambda s: parse(s["observed_at_utc"]) or datetime.min.replace(tzinfo=timezone.utc))
    latest = usable[-1]
    return int(to_float(latest["followers"])), parse(latest["observed_at_utc"]), ""


def snapshot_7d_ago(snapshots: list[dict], reference):
    """Closest snapshot at or before reference. Returns (count, gap_days)."""
    candidates = []
    for snap in snapshots:
        when = parse(snap.get("observed_at_utc", ""))
        if when and snap.get("followers") not in (None, "", "None") and when <= reference:
            candidates.append((when, int(to_float(snap["followers"]))))
    if not candidates:
        return None, None
    when, count = max(candidates, key=lambda pair: pair[0])
    return count, (reference - when).days


def daily_net_new(follows: list[dict], days: int, reference):
    """Sum of net_new over the last `days` complete days ending at reference."""
    window = [(reference - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, days + 1)]
    index = {row.get("date_utc", ""): row for row in follows}
    total = 0
    covered = 0
    for day in window:
        row = index.get(day)
        if row and row.get("net_new") not in (None, ""):
            total += int(to_float(row["net_new"]))
            covered += 1
    return total, covered


def poisson_interval(count: int, exposure_days: int, z: float = 1.96):
    """
    If followers arrive as a roughly constant-rate process, net new over n days is
    Poisson(n*lambda) and the 95% interval on the rate is count +/- z*sqrt(count) per
    day. With count in the low single digits this interval is wider than the point
    estimate, which is the whole point of recording it.
    """
    if exposure_days <= 0:
        return (0.0, 0.0)
    spread = z * math.sqrt(max(count, 0))
    return ((count - spread) / exposure_days, (count + spread) / exposure_days)


def build() -> dict:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    target = int(config.get("target_followers", TARGET))
    horizon = int(config.get("horizon_days", HORIZON))
    snapshots = read_csv(DATA / "follower_snapshots.csv")
    follows = read_csv(DATA / "follows_daily.csv")

    followers, observed_at, note = current_followers(snapshots)
    reference = observed_at or datetime.now(timezone.utc)
    reference = reference.replace(hour=0, minute=0, second=0, microsecond=0)

    out: dict = {
        "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "day_zero": config.get("day_zero"),
        "day_90": config.get("day_90"),
        "target_followers": target,
        "horizon_days": horizon,
        "data_state": "baseline_zero" if followers is None else "live",
        "current_followers": followers,
        "observed_at_utc": observed_at.strftime("%Y-%m-%d") if observed_at else None,
        "note": note,
    }

    if followers is None:
        out.update(
            {
                "net_new_7d": None,
                "velocity_per_day": None,
                "velocity_95ci": None,
                "projected_day_90": 0,
                "gap_to_target": target,
                "gap_to_target_pct": 100.0,
                "run_rate_vs_target": 0.0,
                "net_new_source": "none",
                "required_velocity_per_day": round(target / horizon, 1),
                "honest_read": (
                    "No account and no posts. Every field is a schema placeholder, not a "
                    "measurement. The only number that is real is required_velocity_per_day."
                ),
            }
        )
        return out

    net_new, covered = daily_net_new(follows, 7, reference)
    source = "follows_daily.csv"
    if covered < 7:
        past, gap = snapshot_7d_ago(snapshots, reference - timedelta(days=7))
        if past is not None and gap == 7:
            net_new, source = followers - past, f"follower_snapshots.csv delta over {gap}d"
        elif past is not None:
            net_new = int(round((followers - past) / max(gap, 1)))
            source = f"follower_snapshots.csv dailyised over {gap}d (coarse)"
        else:
            net_new, source = 0, "unavailable: fewer than 7 days of history"

    velocity = net_new / 7
    projected = followers + velocity * horizon
    out.update(
        {
            "net_new_7d": net_new,
            "velocity_per_day": round(velocity, 2),
            "velocity_95ci": [
                round(x, 2) for x in poisson_interval(net_new, 7)
            ],
            "projected_day_90": int(round(projected)),
            "gap_to_target": int(round(target - projected)),
            "gap_to_target_pct": round((target - projected) / target * 100, 3),
            "run_rate_vs_target": round(projected / target, 5),
            "net_new_source": source,
            "required_velocity_per_day": round(target / horizon, 1),
        }
    )
    out["honest_read"] = (
        f"At {velocity:.1f}/day the day-90 projection is {out['projected_day_90']:,}, which is "
        f"{out['run_rate_vs_target'] * 100:.3f}% of the {target:,} target. "
        f"Required sustained rate is {out['required_velocity_per_day']:,}/day. "
        + (
            "On a credible path."
            if out["run_rate_vs_target"] >= 0.25
            else "NOT on a credible path. Say so in the readout this week, not in week 12."
        )
    )
    return out


def render(model: dict) -> str:
    lines = []
    add = lines.append
    add("FOLLOWER VELOCITY")
    add(f"  computed_at        {model['computed_at_utc']}")
    add(f"  data_state         {model['data_state']}")
    add(f"  current_followers  {model['current_followers'] if model['current_followers'] is not None else 'n/a'}")
    add(f"  net_new_7d         {model['net_new_7d']}")
    add(f"  velocity_per_day   {model['velocity_per_day']}")
    add(f"  velocity 95% CI    {model['velocity_95ci'] or 'n/a'}")
    add(f"  projected_day_90   {model['projected_day_90']:,}")
    add(f"  gap_to_target      {model['gap_to_target']:,} ({model['gap_to_target_pct']}% of target)")
    add(f"  run_rate_vs_target {model['run_rate_vs_target'] * 100:.3f}%")
    add(f"  required velocity  {model['required_velocity_per_day']:,}/day to hit target")
    add(f"  net_new source     {model['net_new_source']}")
    add("")
    add(f"READ: {model['honest_read']}")
    return "\n".join(lines)


if __name__ == "__main__":
    model = build()
    if "--json" in sys.argv:
        print(json.dumps(model, indent=2))
    else:
        print(render(model))
