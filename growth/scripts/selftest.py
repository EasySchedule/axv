"""
selftest.py — proves the rig computes, on synthetic data, with no network.

A rig that only ever prints placeholders is not a rig. This writes a temporary
data set with a KNOWN answer, runs the real computation, and asserts the medians
land where they must. Specifically it checks the three things most likely to be
silently wrong:

  1. Medians ignore the breakout post. The fixture puts one post at 500,000
     impressions and the rest under 1,000. If the code used a mean anywhere in the
     headline columns, this fails.
  2. The company median is the median of per-post conversions across all formats,
     not the mean of the format medians.
  3. The kill gate refuses to fire under the impression floor and fires above it.

Also checked here, because it is the rule that decides the company's work and it is
the easiest rule in this repo to get subtly wrong:

  4. A format CAN be killed when the evidence is complete. A guard that never opens
     is not a guard, it is a veto. The fixture proves both directions: the gate
     blocks an under-exposed arm, and clears a well-exposed one.

Run: python scripts/selftest.py
"""

from __future__ import annotations

import csv
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

FIXTURE_POSTS = [
    # post_id, format, topic, impressions_24h, engagements, net_new
    # "chart" is the real arm: 8 posts, median 900 impressions, conversion 0.00111
    ("1001", "chart", "benchmarks", 900, 90, 1),
    ("1002", "chart", "benchmarks", 800, 80, 1),
    ("1003", "chart", "benchmarks", 1000, 100, 1),
    ("1004", "chart", "benchmarks", 700, 70, 1),
    ("1005", "chart", "benchmarks", 1100, 110, 1),
    # "number" is the weak arm: 8 posts, decent impressions, 1/20th the conversion
    ("2001", "number", "funding", 9000, 45, 0),
    ("2002", "number", "funding", 8500, 42, 0),
    ("2003", "number", "funding", 9500, 48, 0),
    ("2004", "number", "funding", 8000, 40, 0),
    ("2005", "number", "funding", 10500, 52, 0),
    # THE BREAKOUT. One post, 500,000 impressions, excellent engagement.
    # A mean-based scoreboard would crown "number". A median-based one must not.
    ("2006", "number", "funding", 500_000, 50_000, 5),
    # "thread" is untested: 1 post, cannot be judged at all
    ("3001", "thread", "policy", 1200, 60, 0),
]

OUTBREAK_ID = "2006"


def build_fixture(directory: Path) -> Path:
    data = directory / "data"
    data.mkdir(parents=True, exist_ok=True)
    (directory / "config").mkdir(parents=True, exist_ok=True)
    (directory / "config" / "account.json").write_text(
        '{"username": null, "target_followers": 1000000, "horizon_days": 90}', encoding="utf-8"
    )
    for name in ("formats.csv", "topics.csv", "format_scoreboard.csv", "topic_scoreboard.csv",
                 "channel_scoreboard.csv", "follows_daily.csv"):
        shutil.copy(ROOT / "data" / name, data / name)
    shutil.copy(ROOT / "config" / "target_assumptions.json", directory / "config" / "target_assumptions.json")

    # Written with DictWriter against an explicit field list, not by hand-counting
    # commas. Hand-counting is how a fixture silently ends up one column short and every
    # assertion below then fails for a reason that has nothing to do with the code under
    # test. The column count is asserted below.
    posts_fields = [
        "post_id", "url", "published_at_utc", "format", "topic", "hook_first_line",
        "post_type", "impressions_24h", "impressions_7d", "likes_24h", "reposts_24h",
        "replies_24h", "quotes_24h", "bookmarks_24h", "engagements_24h",
        "engagement_rate_24h", "profile_clicks_24h", "url_clicks_24h",
        "net_new_followers_24h", "follower_conversion_24h", "is_repost", "is_reply",
        "is_quote", "conversation_id", "parent_post_id", "pulled_at_utc",
        "metric_source", "notes",
    ]
    with (data / "posts.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=posts_fields)
        writer.writeheader()
        for pid, fmt, topic, impressions, eng, net in FIXTURE_POSTS:
            writer.writerow({
                "post_id": pid,
                "url": f"https://x.com/test/status/{pid}",
                "published_at_utc": "2026-01-01T12:00:00.000Z",
                "format": fmt,
                "topic": topic,
                "hook_first_line": "hook",
                "post_type": "original",
                "impressions_24h": impressions,
                "impressions_7d": impressions,
                # Engagement goes into likes_24h on purpose. scoreboard.py recomputes the
                # total from the component fields rather than trusting engagements_24h, so
                # a fixture that only fills the total would score every post as 0.
                "likes_24h": eng,
                "engagements_24h": eng,
                "net_new_followers_24h": net,
                "pulled_at_utc": "2026-01-02T12:00:00Z",
                "metric_source": "fixture",
            })
    with (data / "posts.csv").open(encoding="utf-8") as handle:
        assert len(next(csv.reader(handle))) == len(posts_fields)

    with (data / "follower_snapshots.csv").open("w", newline="", encoding="utf-8") as handle:
        handle.write("observed_at_utc,followers,following,post_count,listed_count,source,note\n")
        handle.write("2026-01-08T00:00:00Z,1000,10,15,2,x_api_v2_user_public_metrics,\n")
    return data


def run(script: str, cwd: Path, *args: str) -> str:
    # Resolve the script from cwd, not from the repo. Every script derives its data
    # directory from its own __file__, so pointing at the repo copy would silently
    # test the real (empty) data instead of the fixture.
    result = subprocess.run(
        [sys.executable, str(cwd / "scripts" / script), *args],
        cwd=cwd, capture_output=True, text=True,
    )
    return result.stdout + result.stderr


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{('  -> ' + detail) if detail else ''}")
    return condition


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="axv-scorecard-selftest-"))
    try:
        scripts_dir = workdir / "scripts"
        scripts_dir.mkdir()
        for name in ("scoreboard.py", "velocity_model.py", "noise_floor.py", "kill_gate.py",
                     "board.py", "target_model.py", "cadence_plan.py"):
            if (SCRIPTS / name).exists():
                shutil.copy(SCRIPTS / name, scripts_dir / name)
        build_fixture(workdir)

        print("1. scoreboard medians vs the breakout")
        run("scoreboard.py", workdir, "--write")
        rows = {}
        with (workdir / "data" / "format_scoreboard.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                rows[row["format"]] = row

        passed = True
        number_med = float(rows["number"]["median_impressions_24h"])
        number_max = int(rows["number"]["max_impressions_24h"])
        passed &= check(
            "the 500k breakout is present as the max", number_max == 500_000, f"max={number_max:,}"
        )
        number_imps = [9000, 8500, 9500, 8000, 10500, 500_000]
        number_mean = statistics.mean(number_imps)
        passed &= check(
            "the median is near 8-9k, NOT near the mean of ~90k",
            8_000 <= number_med <= 9_500,
            f"median={number_med:,.0f} mean would be {number_mean:,.0f} "
            f"({number_mean / number_med:.1f}x the median)",
        )
        chart_med = float(rows["chart"]["median_impressions_24h"])
        passed &= check(
            "the quiet high-conversion arm is NOT crowned by impressions",
            chart_med < number_med,
            f"chart median={chart_med:,.0f} < number median={number_med:,.0f}",
        )
        chart_conv = float(rows["chart"]["median_follower_conversion_24h"])
        number_conv = float(rows["number"]["median_follower_conversion_24h"])
        company = float(rows["chart"]["company_median_conversion_24h"])
        passed &= check(
            "conversion, not impressions, ranks the arms",
            chart_conv > number_conv,
            f"chart={chart_conv * 100:.4f}% number={number_conv * 100:.4f}%",
        )
        # The company median must be the median of ALL per-post conversions, not the
        # mean of the per-format medians. The bias that causes is the whole reason the
        # skill says medians, not means.
        all_conversions = sorted(
            (net / impressions) for _, _, _, impressions, _, net in FIXTURE_POSTS
        )
        expected_company = statistics.median(all_conversions)
        mean_of_format_medians = statistics.mean(
            [
                statistics.median(
                    [net / imp for _, fmt, _, imp, _, net in FIXTURE_POSTS if fmt == name]
                )
                for name in ("chart", "number", "thread")
            ]
        )
        passed &= check(
            "company median is the median of per-post conversions, not the mean of format medians",
            abs(company - expected_company) < 1e-12
            and abs(company - mean_of_format_medians) > 1e-9,
            f"company={company:.3e} median-of-posts={expected_company:.3e} "
            f"mean-of-medians={mean_of_format_medians:.3e} (they must differ)",
        )
        passed &= check(
            "kill_eligible is never auto-filled by the scoreboard",
            all(r["kill_eligible"] == "" for r in rows.values()),
        )
        passed &= check(
            "the 1-post thread is counted as 1, not 0",
            rows["thread"]["posts_shipped"] == "1",
        )

        print("2. the kill gate, both directions")
        # The gate reads its impression floor from data/noise_floor.json. Write it first
        # so the gate judges against a real floor rather than a missing-file default of
        # zero, which would make the impression guard silently inert.
        run("noise_floor.py", workdir, "--write")
        out = run("kill_gate.py", workdir, "--write")
        gate = {}
        with (workdir / "data" / "format_scoreboard.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                gate[row["format"]] = row["kill_eligible"]
        # "number" has 6 posts and 541,000 impressions but a 0% median conversion, so it
        # is below the company median. It must still be BLOCKED, because only one weekly
        # board exists so the two-consecutive-week condition is unproven.
        passed &= check(
            "a well-exposed arm below the median is still blocked without 2 weeks of history",
            gate["number"].startswith("no:") and "consecutive week" in gate["number"],
            f"number -> {gate['number']}",
        )
        passed &= check(
            "a well-exposed arm is blocked ONLY on the missing week history",
            "consecutive week" in gate["number"] and "below the" not in gate["number"],
            "it has 6 posts and 541k impressions, so exposure is not its problem",
        )
        # The impression floor is the guard that actually matters, so assert it fires on
        # an arm that is under-exposed. "thread" is 1 post at 1,200 impressions.
        passed &= check(
            "an under-exposed arm is blocked and the block names the impression floor",
            "below the" in gate["thread"] and "impressions" in gate["thread"],
            f"thread -> {gate['thread']}",
        )
        passed &= check(
            "an untested arm reports both missing conditions, not one",
            gate["thread"].count(";") >= 2,
            f"thread -> {gate['thread']}",
        )
        passed &= check(
            "the gate never emits the word kill on its own",
            all(not v.strip().lower().startswith("kill") for v in gate.values()),
        )

        print("   and the guard is not a veto: a complete case still clears")
        # Build the complete case: a low-conversion arm that clears the post count, the
        # impression floor, AND has two consecutive weekly boards below the median.
        history = workdir / "data" / "history"
        history.mkdir(exist_ok=True)
        floor = json.loads((workdir / "data" / "noise_floor.json").read_text()) if (
            workdir / "data" / "noise_floor.json").exists() else {}
        need = int(floor.get("kill_floor_impressions_per_arm_2x", 0) or 47057)
        with (workdir / "data" / "format_scoreboard.csv").open(encoding="utf-8") as handle:
            fieldnames = next(csv.reader(handle))
        if "format" not in fieldnames:
            print(f"  [FAIL] format_scoreboard.csv header is malformed: {fieldnames[:3]}")
            return 1
        passed &= check(
            "the vs_company_median column is unsuffixed, as scoreboard.py writes it",
            "vs_company_median" in fieldnames and "vs_company_median_24h" not in fieldnames,
        )
        with (workdir / "data" / "format_scoreboard.csv").open(encoding="utf-8") as handle:
            current = list(csv.DictReader(handle))
        for row in current:
            if row["format"] == "number":
                row["total_impressions_24h"] = str(max(need + 10_000, 600_000))
                row["vs_company_median"] = "below"
        with (workdir / "data" / "format_scoreboard.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(current)
        for week in ("2026-W01", "2026-W02"):
            with (history / f"format-number-{week}.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerow({"format": "number", "posts_shipped": "6",
                                 "vs_company_median": "below"})
        run("kill_gate.py", workdir, "--write")
        gate2 = {}
        with (workdir / "data" / "format_scoreboard.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                gate2[row["format"]] = row["kill_eligible"]
        passed &= check(
            "a fully-evidenced weak arm DOES clear the gate",
            gate2["number"].startswith("yes:"),
            f"number -> {gate2['number']}",
        )
        passed &= check(
            "clearing the gate still does not say kill, it says recommend-with-numbers",
            "recommend kill with these numbers" in gate2["number"],
        )

        print("3. velocity model against a single snapshot")
        out = run("velocity_model.py", workdir)
        passed &= check("no crash with one snapshot on file", "FOLLOWER VELOCITY" in out)
        passed &= check(
            "net_new_7d is explicitly unavailable, not silently zero-from-nowhere",
            "unavailable" in out or "no follower snapshot" in out,
            out.strip().splitlines()[-1] if out.strip() else "no output",
        )

        print("4. noise floor with 12 posts (overdispersion needs >=12)")
        out = run("noise_floor.py", workdir, "--json")
        passed &= check(
            "no crash with real data",
            "NOISE FLOOR" in out or '"state"' in out,
            out.strip().splitlines()[-1] if out.strip() else "no output",
        )
        floor_out = json.loads(out[out.index("{") :]) if "{" in out else {}
        passed &= check(
            "overdispersion was actually estimated once 12 posts exist",
            floor_out.get("overdispersion_estimated") is True,
            f"estimated={floor_out.get('overdispersion_estimated')} "
            f"alpha={floor_out.get('overdispersion_alpha')} "
            f"multiplier={floor_out.get('sample_size_multiplier')}x",
        )
        passed &= check(
            "the adjusted kill floor is larger than the binomial floor",
            (floor_out.get("kill_floor_impressions_per_arm_2x") or 0) > 0
            and (floor_out.get("sample_size_multiplier") or 1) > 1.0,
            f"kill_floor={floor_out.get('kill_floor_impressions_per_arm_2x'):,} impressions/arm",
        )

        print("5. the whole board renders from the fixture")
        out = run("board.py", workdir)
        passed &= check(
            "board.py produces all five sections",
            all(section in out for section in (
                "Follower velocity", "Format scoreboard", "Topic scoreboard",
                "Channel scoreboard", "Noise floor",
            )),
            out.strip().splitlines()[-1] if out.strip() else "no output",
        )
        passed &= check(
            "the board never quotes a mean of impressions",
            "mean impressions" not in out.lower().replace("median impressions", ""),
        )

        print()
        print("SELFTEST: " + ("ALL CHECKS PASSED" if passed else "FAILURES ABOVE"))
        return 0 if passed else 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
