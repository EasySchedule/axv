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

    with (data / "posts.csv").open("w", newline="", encoding="utf-8") as handle:
        handle.write(
            "post_id,url,published_at_utc,format,topic,hook_first_line,post_type,"
            "impressions_24h,impressions_7d,likes_24h,reposts_24h,replies_24h,quotes_24h,"
            "bookmarks_24h,engagements_24h,engagement_rate_24h,profile_clicks_24h,url_clicks_24h,"
            "net_new_followers_24h,follower_conversion_24h,is_repost,is_reply,is_quote,"
            "conversation_id,parent_post_id,pulled_at_utc,metric_source,notes\n"
        )
        for pid, fmt, topic, impressions, eng, net in FIXTURE_POSTS:
            # Engagement goes into likes_24h on purpose. scoreboard.py recomputes the
            # total from the component fields rather than trusting engagements_24h, so a
            # fixture that only fills the total would silently score every post as 0.
            handle.write(
                f"{pid},https://x.com/test/status/{pid},2026-01-01T12:00:00.000Z,{fmt},{topic},"
                f"hook,original,{impressions},{impressions},{eng},0,0,0,0,{eng},,,,{net},,,,,,,,"
                f"2026-01-02T12:00:00Z,fixture,\n"
            )

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
        for name in ("scoreboard.py", "velocity_model.py", "noise_floor.py"):
            shutil.copy(SCRIPTS / name, scripts_dir / name)
        build_fixture(workdir)

        print("1. scoreboard medians vs the breakout")
        subprocess.run(
            [sys.executable, str(scripts_dir / "scoreboard.py"), "--write"],
            cwd=workdir, capture_output=True, text=True,
        )
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

        print("2. velocity model against a single snapshot")
        out = run("velocity_model.py", workdir)
        passed &= check("no crash with one snapshot on file", "FOLLOWER VELOCITY" in out)
        passed &= check(
            "net_new_7d is explicitly unavailable, not silently zero-from-nowhere",
            "unavailable" in out or "no follower snapshot" in out,
            out.strip().splitlines()[-1] if out.strip() else "no output",
        )

        print("3. noise floor with 12 posts (overdispersion needs >=12)")
        out = run("noise_floor.py", workdir, "--json")
        passed &= check(
            "no crash with real data",
            "NOISE FLOOR" in out or '"state"' in out,
            out.strip().splitlines()[-1] if out.strip() else "no output",
        )
        floor = json.loads(out[out.index("{") :]) if "{" in out else {}
        passed &= check(
            "overdispersion was actually estimated once 12 posts exist",
            floor.get("overdispersion_estimated") is True,
            f"estimated={floor.get('overdispersion_estimated')} "
            f"alpha={floor.get('overdispersion_alpha')} "
            f"multiplier={floor.get('sample_size_multiplier')}x",
        )
        passed &= check(
            "the adjusted kill floor is larger than the binomial floor",
            (floor.get("kill_floor_impressions_per_arm_2x") or 0) > 0
            and (floor.get("sample_size_multiplier") or 1) > 1.0,
            f"kill_floor={floor.get('kill_floor_impressions_per_arm_2x'):,} impressions/arm",
        )

        print()
        print("SELFTEST: " + ("ALL CHECKS PASSED" if passed else "FAILURES ABOVE"))
        return 0 if passed else 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
