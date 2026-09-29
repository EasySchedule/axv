"""
noise_floor.py — the smallest difference in this dataset that is not noise.

Why this file exists. The kill rule in the growth-scorecard skill is "kill a format when
its median follower conversion is below the company median across two consecutive weeks
with at least 5 posts shipped." At baseline that rule is a trap. Five posts in a
low-impression format can have a median conversion of zero purely because nobody saw
them, and zero is below the company median, so the rule fires and the newsroom kills a
format that was never tested. The rule is measuring exposure, not quality.

So the floor gets computed rather than guessed. This script answers: given the
company's actual follower-conversion rate, how many impressions must a format arm
accumulate before a 2x gap between two formats can be called real at all?

Two layers, in order of pessimism:

1. Binomial floor. Assumes every impression is an independent Bernoulli trial with the
   same conversion probability. This is the OPTIMISTIC floor. Real data is worse.

2. Overdispersion multiplier. Post-level conversion rates are not independent. A post
   that hits a bad hour, a bad audience, or a bad hook converts at a rate 50x below a
   post that lands. That extra spread over-disperses the count, and the required
   sample size is multiplied by the dispersion factor. Until there are enough posts to
   estimate it, this script reports alpha = 0 and therefore the optimistic floor, and
   says so in the output. A floor that is known to be optimistic is still better than
   no floor.

Also emitted: the minimum detectable ratio at a given impression count, which is the
number to quote when someone asks "how big would the difference have to be".

Usage:
  python scripts/noise_floor.py            # print the floor
  python scripts/noise_floor.py --write    # write data/noise_floor.json
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

Z_ALPHA = NormalDist().inv_cdf(0.975)   # 1.96, two-sided 5%
Z_BETA = NormalDist().inv_cdf(0.80)     # 0.8416, 80% power
ALPHA_KNOWN = 0.0                       # replaced by the fitted value once measurable
MIN_POSTS_TO_ESTIMATE_ALPHA = 12
MAX_OVERDISPERSION = 10.0                  # a small sample can imply an absurd phi
REFERENCE_MEDIAN_IMPRESSIONS = 5_000    # placeholder, replaced by the observed median

RATIOS = (1.5, 2.0, 3.0, 4.0)
BASELINE_RATES = (0.0002, 0.0005, 0.001, 0.002)


def binomial_impressions(p0: float, ratio: float) -> int:
    """Impressions needed PER ARM to detect p1 = ratio*p0 at alpha .05, power .80."""
    p1 = ratio * p0
    if p1 >= 1.0:
        return 0
    pbar = (p0 + p1) / 2
    qbar = 1 - pbar
    numerator = (Z_ALPHA * math.sqrt(2 * pbar * qbar) + Z_BETA * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2
    return math.ceil(numerator / (p1 - p0) ** 2)


def minimum_detectable_ratio(p0: float, impressions: int) -> float | None:
    """Smallest p1/p0 detectable with `impressions` per arm, inverting the same formula."""
    if impressions <= 0 or p0 <= 0:
        return None
    lo, hi = 1.0, 100.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if binomial_impressions(p0, mid) > impressions:
            lo = mid
        else:
            hi = mid
    return round(hi, 2)


def fit_overdispersion(rows: list[dict]) -> tuple[float, str, int]:
    """
    Estimate the overdispersion factor from shipped posts.

    The identity used is Poisson's: for a count y drawn from a constant-rate process,
    Var(y) = E[y]. Conversions are not Poisson. A post that hits a bad hour, a bad
    audience, or a bad hook converts at a rate 50x below a post that lands, and the
    variance of the counts blows past the mean. The excess is

        phi = (sample Var(y) - mean(y)) / mean(y)^2

    which is the negative-binomial overdispersion parameter. Required sample size for
    detecting a difference scales linearly in (1 + phi), so phi is the multiplier
    applied to every floor below.

    This is computed on COUNTS, not on per-post rates. The variance identity is a
    statement about counts; applying it to rates mixes units and produces a number that
    looks plausible and is wrong. Exposures differ per post here, which is a real
    violation of the equal-exposure assumption, so treat phi as indicative and
    re-estimate it as the post count grows rather than trusting one value.
    """
    counts = []
    for row in rows:
        try:
            impressions = float(row.get("impressions_24h") or 0)
            net_new = float(row.get("net_new_followers_24h") or 0)
        except ValueError:
            continue
        if impressions > 0:
            counts.append(net_new)
    n = len(counts)
    if n < MIN_POSTS_TO_ESTIMATE_ALPHA:
        return (
            ALPHA_KNOWN,
            f"NOT YET ESTIMABLE: {n} mature posts, need {MIN_POSTS_TO_ESTIMATE_ALPHA}. "
            "Reported floors are therefore optimistic lower bounds.",
            n,
        )
    mean_count = statistics.mean(counts)
    if mean_count <= 0:
        return (
            0.0,
            f"zero conversions across all {n} posts; mean count is 0 and phi is undefined. "
            "Floors cannot be computed until at least one post converts.",
            n,
        )
    sample_var = statistics.variance(counts)
    phi = (sample_var - mean_count) / (mean_count**2)
    phi = max(0.0, round(phi, 2))
    capped = phi > MAX_OVERDISPERSION
    phi = min(phi, MAX_OVERDISPERSION)
    note = (
        f"estimated from {n} posts: mean net new {mean_count:.2f}/post, "
        f"sample variance {sample_var:.2f}, phi={phi}"
    )
    if sample_var <= mean_count:
        note += ". Variance did not exceed the mean, so no overdispersion penalty is applied."
    if capped:
        note += f". Capped at MAX_OVERDISPERSION={MAX_OVERDISPERSION} from a small sample; re-estimate later."
    return (phi, note, n)


def build() -> dict:
    posts_path = DATA / "posts.csv"
    rows: list[dict] = []
    if posts_path.exists() and posts_path.stat().st_size > 0:
        with posts_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

    alpha, provenance, n_posts = fit_overdispersion(rows)
    multiplier = 1.0 + alpha
    estimated = alpha > 0

    # Company baseline conversion: pooled over all posts, which is the least biased
    # estimator available at low post counts.
    total_impressions = 0.0
    total_net_new = 0.0
    for row in rows:
        try:
            total_impressions += float(row.get("impressions_24h") or 0)
            total_net_new += float(row.get("net_new_followers_24h") or 0)
        except ValueError:
            continue
    observed_rate = (total_net_new / total_impressions) if total_impressions else None

    table = []
    for p0 in BASELINE_RATES:
        entry = {"assumed_baseline_conversion": p0, "by_ratio": {}}
        for ratio in RATIOS:
            need = binomial_impressions(p0, ratio)
            entry["by_ratio"][str(ratio)] = {
                "impressions_per_arm_binomial": need,
                "impressions_per_arm_adjusted": math.ceil(need * multiplier),
                "posts_per_arm_at_5000_median_impressions": math.ceil(need * multiplier / REFERENCE_MEDIAN_IMPRESSIONS),
                "min_detectable_ratio_at_10000_impressions": minimum_detectable_ratio(p0, 10_000),
                "min_detectable_ratio_at_50000_impressions": minimum_detectable_ratio(p0, 50_000),
            }
        table.append(entry)

    kill_floor_impressions = max(
        binomial_impressions(0.001, 2.0) * multiplier,
        binomial_impressions(0.0005, 2.0) * multiplier,
    )

    return {
        "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": "baseline_zero" if not rows else "measured",
        "mature_posts": n_posts,
        "observed_conversion_rate": observed_rate,
        "overdispersion_alpha": alpha,
        "overdispersion_estimated": estimated,
        "overdispersion_provenance": provenance,
        "sample_size_multiplier": round(multiplier, 2),
        "reference_median_impressions": REFERENCE_MEDIAN_IMPRESSIONS,
        "alpha": 0.05,
        "power": 0.80,
        "test": "two-proportion comparison of follower conversion per impression, per format arm",
        "kill_floor_impressions_per_arm_2x": math.ceil(kill_floor_impressions),
        "table": table,
        "rules": [
            "No format is killed on conversion until its arm has BOTH >=5 posts AND the impression floor for the effect size being claimed.",
            "A difference is called real only when the two arms' impressions clear the floor for that ratio. Below the floor, report 'not distinguishable' and say so.",
            "Until overdispersion is estimable (>=12 mature posts), every floor in this file is a lower bound and the true floor is larger.",
            "Two consecutive weeks below the company median is necessary but not sufficient; the impression guard is also necessary.",
        ],
        "honest_read": (
            "Baseline is zero. No floor is measured, only modelled. The first two weekly "
            "readouts will be under-powered by construction and will say so."
            if not rows
            else f"Floors are computed from {n_posts} mature posts."
        ),
    }


def render(floor: dict) -> str:
    lines = []
    add = lines.append
    add("NOISE FLOOR")
    add(f"  state                {floor['state']}")
    add(f"  mature posts         {floor['mature_posts']}")
    add(f"  overdispersion alpha {floor['overdispersion_alpha']}  (multiplier {floor['sample_size_multiplier']}x)")
    add(f"  provenance           {floor['overdispersion_provenance']}")
    add(f"  observed conv rate   {floor['observed_conversion_rate']}")
    add("")
    add(f"  Impressions needed per arm to call a difference real (alpha .05, power .80, two-proportion):")
    head = f"    {'baseline conv':<16}{'ratio':<8}{'binomial':>12}{'adjusted':>12}{'posts@5k':>11}{'min ratio@10k':>15}"
    add(head)
    add("    " + "-" * (len(head) - 4))
    for row in floor["table"]:
        for ratio, cell in row["by_ratio"].items():
            add(
                f"    {row['assumed_baseline_conversion'] * 100:>14.3f}%"
                f"{float(ratio):>8.1f}x"
                f"{cell['impressions_per_arm_binomial']:>12,}"
                f"{cell['impressions_per_arm_adjusted']:>12,}"
                f"{cell['posts_per_arm_at_5000_median_impressions']:>11,}"
                f"{str(cell['min_detectable_ratio_at_10000_impressions']):>15}"
            )
    add("")
    add(f"  Kill floor (2x gap, worst-case baseline): {floor['kill_floor_impressions_per_arm_2x']:,} impressions per arm")
    add(f"  READ: {floor['honest_read']}")
    return "\n".join(lines)


if __name__ == "__main__":
    floor = build()
    if "--write" in sys.argv:
        out = DATA / "noise_floor.json"
        out.write_text(json.dumps(floor, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)}")
    if "--json" in sys.argv:
        print(json.dumps(floor, indent=2))
    else:
        print(render(floor))
