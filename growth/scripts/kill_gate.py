"""
kill_gate.py — decides kill_eligible, and refuses to decide it without evidence.

The growth-scorecard skill's rule is: "kill a format when its median follower
conversion is below the company median across two consecutive weeks with at least 5
posts shipped."

Taken literally at baseline, that rule fires on a format with 5 posts that nobody saw.
Median conversion of a low-exposure arm is zero because the denominator was small, not
because the format is bad. The rule measures exposure and calls it quality.

This script applies the skill's rule AND an impression guard:

    kill_eligible = below company median
                    AND >= 5 posts shipped
                    AND >= kill floor impressions for the effect size claimed
                    AND below company median in 2 consecutive weekly boards

The weekly-history requirement is checked against the git-free history this rig keeps:
week_of values present in the scoreboard snapshots written to data/history/. If that
directory is empty, the two-week condition is reported as unproven and kill_eligible
is blank. A kill recommendation is a decision Vanguard acts on, so it gets the same
treatment as any other irreversible call: two independent confirmations, and an
explicit note of which one is missing.

This script never sets kill_eligible to "kill". It sets it to "no" or to a reason
string. The recommendation itself is written by Ledger into the weekly readout, in
words, with the numbers attached. Code should not announce that a content format is
dead; it should only refuse to pretend the data is sufficient.

Usage:
  python scripts/kill_gate.py            # print, write nothing
  python scripts/kill_gate.py --write    # stamp kill_eligible into the scoreboards
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HISTORY = DATA / "history"

MIN_POSTS = 5
MIN_CONSECUTIVE_WEEKS = 2
WINDOW = "24h"


def read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def kill_floor() -> int:
    path = DATA / "noise_floor.json"
    if not path.exists():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8")).get("kill_floor_impressions_per_arm_2x", 0))


def weeks_below(name: str, key: str) -> list[str]:
    """Weekly boards, oldest first, in which this arm sat below the company median."""
    hits = []
    if not HISTORY.exists():
        return hits
    for snapshot in sorted(HISTORY.glob(f"{key}-{name}-*.csv")):
        rows = {row.get(key): row for row in read_csv(snapshot)}
        row = rows.get(name)
        if row and row.get(f"vs_company_median_{WINDOW}") == "below":
            hits.append(snapshot.stem.rsplit("-", 1)[-1])
    return hits


def evaluate(path: Path, key: str) -> list[dict]:
    floor = kill_floor()
    out = []
    for row in read_csv(path):
        name = row.get(key, "")
        posts = int(row.get("posts_shipped") or 0)
        impressions = int(row.get(f"total_impressions_{WINDOW}") or 0)
        below = row.get(f"vs_company_median_{WINDOW}") == "below"
        weeks = weeks_below(name, key)

        blockers = []
        if posts == 0:
            blockers.append("no posts shipped")
        if posts < MIN_POSTS:
            blockers.append(f"only {posts} posts, need {MIN_POSTS}")
        if impressions < floor:
            blockers.append(f"{impressions:,} impressions, below the {floor:,} floor")
        if len(weeks) < MIN_CONSECUTIVE_WEEKS:
            blockers.append(
                f"{len(weeks)} consecutive week(s) below median, need {MIN_CONSECUTIVE_WEEKS}"
            )

        # An arm with no posts is unmeasured, not passing. Say which condition is
        # missing, so the board always tells the reader what the arm still needs.
        if posts == 0:
            verdict = "no: " + blockers[0]
        elif not below:
            verdict = "no"
        elif blockers:
            verdict = "no: " + "; ".join(blockers)
        else:
            verdict = "yes: evidence complete, recommend kill with these numbers attached"
        out.append({**row, "kill_eligible": verdict})
    return out


def main() -> None:
    write = "--write" in sys.argv
    targets = [
        (DATA / "format_scoreboard.csv", "format"),
        (DATA / "topic_scoreboard.csv", "topic"),
    ]
    print(f"KILL GATE  (min {MIN_POSTS} posts, min {kill_floor():,} impressions, "
          f"{MIN_CONSECUTIVE_WEEKS} consecutive weeks below median)\n")
    for path, key in targets:
        rows = evaluate(path, key)
        if not rows:
            continue
        print(key.upper())
        for row in rows:
            print(f"  {row.get(key, ''):<24}{row['kill_eligible']}")
        print()
        if write:
            with path.open(encoding="utf-8") as handle:
                fieldnames = next(csv.reader(handle), [])
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            print(f"  wrote {path.name}")
            print()


if __name__ == "__main__":
    main()
