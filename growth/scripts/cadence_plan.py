"""
cadence_plan.py — the weekly target, broken into per-agent targets, with a
measurability gate on every line.

The company brief is "1,000,000 followers in 90 days". target_model.py shows organic
compounding delivers ~826 of that. So the newsroom cannot be aimed at a follower number,
because the follower number is not controllable and, at this scale, not even measurable.

This script answers the question that actually has to be answered every week:

    what number does each agent own, and is that number big enough to tell a
    real change from noise?

The measurability gate
----------------------
A count drawn from a roughly constant-rate process is Poisson. The 95% interval on a
count N is about N +/- 1.96*sqrt(N), so the relative half-width is:

    1.96 / sqrt(N)

which is +-100% at N=4, +-49% at N=16, +-30% at N=43, +-20% at N=96.

**Any target below roughly 43 is noise.** A per-agent weekly follower target of 10 is a
coin flip, and an agent asked to hit a coin flip will either fabricate the number or
stop reporting. So every line below carries its own half-width, and lines that are not
yet measurable are marked as such instead of being quietly presented as targets.

That is the whole reason this file exists. A target that cannot be measured is a
mood with a number attached.

The two-level target
--------------------
  lever target     what the agent can actually control this week. Measurable now.
  follower target  the growth line. Only assigned once the lever target is above the
                   floor, because until then the follower number is dominated by noise
                   and by breakouts that belong to nobody.

Usage:
    python scripts/cadence_plan.py
    python scripts/cadence_plan.py --json
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HALF_WIDTH_TARGET = 0.30  # +-30% is the loosest interval we will call a signal
MIN_MEASURABLE_N = math.ceil((1.96 / HALF_WIDTH_TARGET) ** 2)  # 43


def relative_half_width(n: float) -> float:
    """95% relative half-width on a Poisson count of n. Inf at zero."""
    if n <= 0:
        return float("inf")
    return 1.96 / math.sqrt(n)


def measurable(n: float) -> bool:
    return n >= MIN_MEASURABLE_N


def poisson_interval(n: int, z: float = 1.96) -> tuple[int, int]:
    spread = z * math.sqrt(max(n, 0))
    return int(round(n - spread)), int(round(n + spread))


# ---------------------------------------------------------------------------
# The per-agent plan. Each entry states the lever the agent owns, the weekly
# number, and the unit. Follower targets are NOT set here; they are derived per
# week by followup_targets() once the account has a measurable base.
# ---------------------------------------------------------------------------

AGENT_PLAN = [
    {
        "agent": "Vanguard",
        "role": "Positioning & Narrative Lead",
        "lever": "topic_arms_mature",
        "target": 2,
        "unit": "topics with >=5 mature posts",
        "why": (
            "The topic board is the only instrument that answers 'what is this audience "
            "following us for'. Two arms a week means the first format/topic comparison "
            "exists by week 3 instead of week 9. This is the cheapest compounding asset "
            "the company owns and it is currently at zero."
        ),
        "reports": "topics with >=5 mature posts; median conversion by topic, or 'not distinguishable'",
    },
    {
        "agent": "Dispatch",
        "role": "Head of Content",
        "lever": "posts_shipped",
        "target": 42,
        "unit": "posts shipped per week (6/day)",
        "why": (
            "Cadence discipline, not volume as a growth lever. 6/day is the floor. The "
            "model says 178x this cadence still misses the target, so the target here is "
            "'ship what was planned', never 'ship more'. Volume is the last lever."
        ),
        "reports": "posts shipped vs 42; median impressions_24h, never the mean",
    },
    {
        "agent": "Relay",
        "role": "Community & Reply Operator",
        "lever": "replies_under_large_accounts",
        "target": 30,
        "unit": "replies/day placed under accounts with >=10k followers",
        "why": (
            "This is the discovery engine. A zero-follower account cannot reach its own "
            "timeline, so borrowed reach is the only non-breakout growth mechanism the "
            "newsroom controls. 30/day is the single highest-leverage number on this list "
            "and it is the one most likely to be quietly under-shipped."
        ),
        "reports": "replies shipped vs 30/day; median impressions per reply; share of replies with >=1 follow",
    },
    {
        "agent": "Prism",
        "role": "Visual & Creative",
        "lever": "chart_posts",
        "target": 7,
        "unit": "chart posts per week",
        "why": (
            "Charts are the format with the highest expected shareability per unit of "
            "production cost, and the format scoreboard has a chart row that is currently "
            "empty. 7/week gives a real arm by week 2."
        ),
        "reports": "chart posts vs 7; chart median impressions vs non-chart median (ratio, not absolute)",
    },
    {
        "agent": "Hound",
        "role": "Signal Scout",
        "lever": "cards_to_posts",
        "target": 10,
        "unit": "signal cards per week that clear the bar",
        "why": (
            "Hound is upstream of everything. Under-shipping here starves Dispatch and "
            "forces the content set to repeat itself, which shows up two weeks later as "
            "flat impressions and gets misdiagnosed as a content problem."
        ),
        "reports": "cards cleared vs 10; share of cards that became a shipped post within 48h",
    },
    {
        "agent": "Ledger",
        "role": "Growth Analyst",
        "lever": "readouts_on_time",
        "target": 13,
        "unit": "weekly readouts delivered on Monday 09:00 UTC",
        "why": (
            "The board is worthless if it is late. 13 readouts across the horizon, each "
            "carrying the honest verdict line, including the weeks the run is behind."
        ),
        "reports": "readouts on time vs 13; days since last real measurement (not last empty pull)",
    },
    {
        "agent": "Ember",
        "role": "Growth Lead",
        "lever": "reallocation_decisions",
        "target": 1,
        "unit": "reallocation decision per week, with the number attached",
        "why": (
            "Including me. The weekly job is not shipping, it is cutting what did not "
            "compound and doubling what did, and saying plainly when the run is off-path."
        ),
        "reports": "one decision per week: what was cut, what was doubled, and the numbers behind it",
    },
]


def followup_targets(model: dict, floor: dict) -> dict:
    """
    Derive the follower line, and say out loud whether it is measurable yet.

    Returns per-agent follower SHARES rather than absolute targets. An absolute
    follower target per agent is not available at baseline, for a structural reason
    that is independent of scale: **X does not attribute a follow to the post or the
    agent that caused it.** Per-agent follower attribution needs the user-context
    credential, not just a bearer token, and even then it is an estimate.

    So the follower target is currently ONE company number, and per agent it is a share
    of the compounding line. That is the honest structure, and it beats six invented
    absolutes. Whether the company line is itself measurable is a separate question and
    is answered by the Poisson floor rather than assumed.
    """
    ladder = model["weekly_ladder_base"]
    week1 = next((r for r in ladder if r["week"] == 1), None)
    weekly_net_new = week1["weekly_net_new"] if week1 else 0

    lo, hi = poisson_interval(int(weekly_net_new))
    is_measurable = measurable(weekly_net_new)
    scale_note = (
        f"the company line IS measurable at {weekly_net_new:,}/week "
        f"(+-{relative_half_width(weekly_net_new) * 100:.0f}%), so it can be tracked week to week"
        if is_measurable
        else f"the company line is still below the n={MIN_MEASURABLE_N} floor at {weekly_net_new:,}/week, "
        f"so week-to-week movement is noise, not signal"
    )
    return {
        "company_weekly_target": int(weekly_net_new),
        "company_weekly_ci95": [lo, hi],
        "relative_half_width": round(relative_half_width(weekly_net_new), 3),
        "measurable_at_30pct": is_measurable,
        "min_measurable_n": MIN_MEASURABLE_N,
        "weeks_until_measurable": _weeks_until(ladder),
        "per_agent_follower_targets": (
            "NOT ASSIGNED, and this is structural rather than a scale problem: X does not "
            "attribute a follow to the post or the agent that caused it, so no agent can be "
            "given a follower number that is honestly theirs. Per-agent growth is tracked as a "
            f"share of the compounding line instead. Separately, {scale_note}."
        ),
        "shares_of_compounding_line": {
            "Vanguard (narrative/topics)": 0.20,
            "Dispatch (originating posts)": 0.35,
            "Relay (replies, borrowed reach)": 0.30,
            "Prism (charts)": 0.15,
        },
    }


def _weeks_until(ladder: list[dict]) -> int | None:
    for row in ladder:
        if measurable(row["weekly_net_new"]):
            return row["week"]
    return None


def build() -> dict:
    import target_model

    model = target_model.build()
    floor_path = ROOT / "data" / "noise_floor.json"
    floor = json.loads(floor_path.read_text(encoding="utf-8")) if floor_path.exists() else {}
    reach = model["reachability"]

    agents = []
    for entry in AGENT_PLAN:
        row = dict(entry)
        n = float(entry["target"])
        # These are PROCESS counts, not rate observations. If Dispatch says it shipped
        # 42 posts, that number is exact, so a Poisson interval on it would be a category
        # error: it would imply the count is a noisy sample of some true rate, when in
        # fact "did you do the thing" is either true or false. The Poisson floor applies
        # to the OUTCOME each lever produces (impressions, follows, conversions), which
        # is where the noise lives. So no interval is attached here, by design.
        row["measurable"] = "exact process count; noise applies to the outcome, not the count"
        agents.append(row)

    return {
        "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_days": model["horizon_days"],
        "target_followers": model["target_followers"],
        "headline_verdict": reach["verdict"],
        "cadence_can_reach_target_alone": reach["cadence_can_reach_target_alone"],
        "measurability_rule": {
            "min_n_for_30pct": MIN_MEASURABLE_N,
            "formula": "95% relative half-width on a Poisson count is 1.96/sqrt(N)",
            "why": (
                "A target below this is noise, not a signal. Applies to OUTCOME rates "
                "(follows, impressions, conversions), not to process counts like posts "
                "shipped, which are exact."
            ),
        },
        "follower_line": followup_targets(model, floor),
        "agent_targets": agents,
    }


def render(model: dict) -> str:
    out: list[str] = []
    add = out.append
    f = model["follower_line"]

    add("CADENCE PLAN — weekly targets, per agent")
    add(f"  computed_at {model['computed_at_utc']}")
    add(f"  horizon     {model['horizon_days']} days, target {model['target_followers']:,}")
    add("")

    add("MEASURABILITY RULE")
    add(f"  {model['measurability_rule']['formula']}")
    add(f"  below n={f['min_measurable_n']} a number is noise, not a signal")
    add("")

    add("FOLLOWER LINE (the growth target)")
    add(f"  company weekly target   {f['company_weekly_target']:,}")
    add(f"  95% interval            {f['company_weekly_ci95'][0]:,} to {f['company_weekly_ci95'][1]:,}")
    add(f"  relative half-width     +-{f['relative_half_width']*100:.1f}%")
    add(f"  measurable at +-30%?    {'YES' if f['measurable_at_30pct'] else 'NO'}")
    add(f"  first measurable week   {f['weeks_until_measurable'] if f['weeks_until_measurable'] else 'never at this velocity'}")
    add(f"  per-agent follower ts   {f['per_agent_follower_targets']}")
    add("")

    add("AGENT TARGETS — levers, each an exact process count")
    add(f"  {'agent':<10} {'lever':<32} {'target':>7}  unit")
    for a in model["agent_targets"]:
        add(f"  {a['agent']:<10} {a['lever']:<32} {a['target']:>7}  {a['unit']}")
    add("")
    add("  Counts above are exact, so no interval is attached to them. The Poisson floor")
    add("  applies to the OUTCOME each lever produces: impressions, follows, conversions.")
    add("")

    add("WHY EACH ONE")
    for a in model["agent_targets"]:
        add(f"  {a['agent']} — {a['why']}")
        add(f"      reports: {a['reports']}")
    add("")

    add("VERDICT")
    for line in _wrap(model["headline_verdict"], 74):
        add(f"  {line}")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, out, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    m = build()
    print(json.dumps(m, indent=2) if "--json" in sys.argv else render(m))
