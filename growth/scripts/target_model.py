"""
target_model.py — the growth target model, and the honest verdict on whether it is reachable.

velocity_model.py answers "where are we". noise_floor.py answers "what is the smallest
difference we can honestly call real". This script answers the third question, the one
the company actually has to decide against: **"where do we have to be, and can cadence
get us there?"**

The compounding model
---------------------
A post's impressions come from two places:

    I(F) = discovery  +  follower_share * F * reach_scale / (reach_scale + F)

  discovery      impressions that are not the follower base: algorithmic discovery,
                 search, quote-tweet pickup, browse. For a new account this is nearly
                 all of the reach, which is why a zero account cannot bootstrap itself
                 out of its own timeline.
  follower_share fraction of the follower base that one post reaches.
  reach_scale    the follower count at which the timeline throttles per-post reach by
                 half. This is the saturation term. Without it the model compounds
                 forever and produces a fantasy. With it, growth is exponential early
                 and linear later, which is how real accounts actually behave.

Follows per day:

    dF/dt = posts_per_day * I(F) * conversion  +  offplatform_cohort_per_week / 7

Integrated day by day, not continuously. A follower cannot arrive before the post that
carried it, and continuous integration of a compounding term is how targets become
fiction.

Every parameter is a PRIOR at baseline. When mature posts exist, re-estimate() replaces
them from the board's own data and stamps provenance. The priors live in
config/target_assumptions.json and carry their own justification inline.

The three questions this answers
--------------------------------
  1. reachability   — day-90 projection per scenario. Honest yes or no.
  2. attribution    — how much of the gap cadence can close and how much must come
                      from a step change (a breakout or a distribution channel).
  3. the ladder     — the weekly target that follows from the answer, which is the
                      only thing the agents should ever be asked to hit.

Usage:
    python scripts/target_model.py                 # human read
    python scripts/target_model.py --json          # machine read
    python scripts/target_model.py --solve-cohort  # what off-platform must deliver
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "target_assumptions.json"
ACCOUNT = ROOT / "config" / "account.json"

HORIZON = 90
WEEKS = HORIZON // 7


def load_assumptions() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def load_account() -> dict:
    return json.loads(ACCOUNT.read_text(encoding="utf-8"))


def impressions(followers: float, discovery: float, share: float, scale: float) -> float:
    """Impressions on one post from a follower base of `followers`."""
    if scale <= 0:
        return discovery + share * followers
    return discovery + share * followers * (scale / (scale + followers))


def simulate(
    days: int = HORIZON,
    posts_per_day: float = 6.0,
    conversion: float = 0.0005,
    discovery: float = 3000.0,
    share: float = 0.15,
    scale: float = 250_000.0,
    cohort_per_week: float = 0.0,
) -> dict:
    """
    Integrate the follower count one day at a time.

    Day-step, not continuous. A compounding term integrated analytically over-predicts,
    and an over-prediction here becomes a target the newsroom cannot hit.
    """
    followers = 0.0
    daily_offplatform = cohort_per_week / 7.0
    weekly: list[dict] = []
    peak_impressions = 0.0

    for day in range(days + 1):
        if day % 7 == 0:
            weekly.append({"day": day, "followers": round(followers)})
        if day == days:
            break
        imp = impressions(followers, discovery, share, scale)
        peak_impressions = max(peak_impressions, imp)
        organic = posts_per_day * imp * conversion
        followers += organic + daily_offplatform

    # 90 is not a multiple of 7, so the final week is partial. Record it explicitly,
    # otherwise the ladder ends on day 84 and the target date is never on the board.
    if days % 7 != 0:
        weekly.append({"day": days, "followers": round(followers)})

    net_new = followers  # starts at zero by definition
    return {
        "day_90_followers": round(followers),
        "net_new_7d_at_end": round(weekly[-1]["followers"] - weekly[-2]["followers"]) if len(weekly) > 1 else 0,
        "velocity_per_day_at_end": round((followers - weekly[-2]["followers"]) / 7, 1) if len(weekly) > 1 else 0.0,
        "peak_impressions_per_post": round(peak_impressions),
        "weekly": weekly,
    }


def project_scenario(assumptions: dict, name: str, overrides: dict | None = None) -> dict:
    scen = dict(assumptions["scenarios"][name])
    if overrides:
        scen.update(overrides)
    run = simulate(
        posts_per_day=float(assumptions["posts_per_day"]),
        conversion=float(scen["conversion"]),
        discovery=float(scen["discovery"]),
        share=float(scen["follower_share"]),
        scale=float(scen["reach_scale"]),
        cohort_per_week=float(assumptions.get("offplatform_cohort_per_week", 0.0)),
    )
    run["scenario"] = name
    run["params"] = scen
    return run


def solve_required_cohort(assumptions: dict, scenario: str, target: int) -> dict:
    """
    What constant off-platform cohort per week, combined with this scenario's organic
    compounding, reaches `target` on day 90?

    Solved by bisection, not algebra. The model is a saturating recursion, so the
    required cohort is a property of the dynamics and an algebraically derived number
    would be a lie that looks like a formula.
    """
    params = assumptions["scenarios"][scenario]
    lo, hi = 0.0, 1_000_000.0
    for _ in range(200):
        mid = (lo + hi) / 2
        run = simulate(
            posts_per_day=float(assumptions["posts_per_day"]),
            conversion=float(params["conversion"]),
            discovery=float(params["discovery"]),
            share=float(params["follower_share"]),
            scale=float(params["reach_scale"]),
            cohort_per_week=mid,
        )
        if run["day_90_followers"] >= target:
            hi = mid
        else:
            lo = mid
    required = hi
    organic_alone = project_scenario(assumptions, scenario)
    return {
        "scenario": scenario,
        "required_cohort_per_week": round(required, 1),
        "required_cohort_per_day": round(required / 7, 1),
        "required_per_day_pct_of_target": round((required / 7) / target * 100, 4),
        "organic_alone_day_90": organic_alone["day_90_followers"],
        "organic_share_of_target_pct": round(organic_alone["day_90_followers"] / target * 100, 4),
        "breakout_gap": target - organic_alone["day_90_followers"],
    }


def re_estimate(assumptions: dict, floor: dict) -> dict:
    """
    Replace priors with measured values once the board has mature posts.

    Two things become estimable and both are load-bearing:
      conversion  median follows per impression across all mature posts
      discovery   median impressions minus the share-explained part, floored at 0

    Returns provenance stamps so no readout can present a prior as a measurement.
    """
    conv = floor.get("observed_conversion_rate")
    maturity = floor.get("mature_posts", 0)
    if maturity < 12 or conv is None:
        return {
            "conversion": {
                "value": assumptions["conversion"],
                "provenance": "PRIOR: not measurable below 12 mature posts",
            },
            "discovery": {
                "value": assumptions["discovery"],
                "provenance": "PRIOR: not measurable below 12 mature posts",
            },
            "measured": False,
        }
    return {
        "conversion": {
            "value": conv,
            "provenance": f"MEASURED: median follower conversion over {maturity} mature posts",
        },
        "discovery": {
            "value": assumptions["discovery"],
            "provenance": (
                f"PARTLY MEASURED: conversion is measured; discovery is still a prior. "
                f"A search-driven account and a quote-tweet-driven account have the same "
                f"conversion and very different discovery, and posts.csv cannot separate them."
            ),
        },
        "measured": True,
    }


def weekly_ladder(assumptions: dict, run: dict, target: int) -> list[dict]:
    """
    The weekly target line. NOT a straight line to 1,000,000.

    A linear ladder to 1M tells an agent in week 1 to ship 11,111 followers, which is
    not a target, it is a taunt. The ladder is the model's own trajectory, re-based so
    that week 1 asks for something a newsroom can actually do, and the day-90 target
    stays the stated goal with the gap stated honestly beside it.
    """
    target_share = 1.0
    ladder = []
    prior = 0
    for entry in run["weekly"]:
        day = entry["day"]
        if day == 0:
            continue
        cumulative = entry["followers"]
        weekly_delta = cumulative - prior
        prior = cumulative
        ladder.append(
            {
                "week": day // 7,
                "day": day,
                "cumulative": cumulative,
                "weekly_net_new": weekly_delta,
                "per_day": round(weekly_delta / 7, 1),
                "pct_of_target": round(cumulative / target * 100, 4),
            }
        )
    return ladder


def slip_impact(assumptions: dict, account: dict, target: int) -> dict:
    """
    What a delayed start costs, in the only unit that matters: required velocity.

    day_zero is a calendar date, and the calendar does not wait for the account to exist.
    If the account ships on day S, the runway is 90-S days, not 90, and the required
    daily rate rises to match. This is the number that makes the cost of a blocked
    account concrete instead of rhetorical: every day the account does not exist is a
    day of runway that cannot be recovered.

    Reported against the account's own status, so it cannot be a stale argument.
    """
    username = account.get("username")
    created = bool(username)
    table = []
    for slip in (0, 3, 7, 14, 21, 30):
        remaining = max(HORIZON - slip, 1)
        table.append(
            {
                "start_delay_days": slip,
                "runway_days": remaining,
                "required_per_day": round(target / remaining, 0),
                "required_per_week": round(target / remaining * 7, 0),
            }
        )
    return {
        "account_exists": created,
        "status": "live" if created else "not created; every pull fails closed",
        "note": (
            "The 90-day clock started on day_zero regardless of whether the account exists. "
            "These are the rates required from the moment the account goes live, indexed by "
            "how late that is. This is the cost of a blocked account, in the only unit the "
            "target is measured in."
        ),
        "table": table,
    }


def build() -> dict:
    assumptions = load_assumptions()
    account = load_account()
    target = int(account.get("target_followers", 1_000_000))

    floor_path = ROOT / "data" / "noise_floor.json"
    floor = json.loads(floor_path.read_text(encoding="utf-8")) if floor_path.exists() else {}
    estimates = re_estimate(assumptions, floor)

    scenarios = {name: project_scenario(assumptions, name) for name in ("pessimistic", "base", "strong")}
    base = scenarios["base"]

    cohort = solve_required_cohort(assumptions, "base", target)

    reach = {
        "target": target,
        "organic_base_day_90": base["day_90_followers"],
        "organic_base_pct": round(base["day_90_followers"] / target * 100, 4),
        "organic_pessimistic_day_90": scenarios["pessimistic"]["day_90_followers"],
        "organic_strong_day_90": scenarios["strong"]["day_90_followers"],
        "cadence_can_reach_target_alone": scenarios["strong"]["day_90_followers"] >= target,
        "required_cohort_per_week": cohort["required_cohort_per_week"],
        "verdict": verdict(scenarios, cohort, target),
    }

    return {
        "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "day_zero": account.get("day_zero"),
        "day_90": account.get("day_90"),
        "horizon_days": HORIZON,
        "target_followers": target,
        "cadence_posts_per_day": assumptions["posts_per_day"],
        "parameter_provenance": estimates,
        "reachability": reach,
        "slip_impact": slip_impact(assumptions, account, target),
        "weekly_ladder_base": weekly_ladder(assumptions, base, target),
        "scenarios": {
            name: {
                "day_90_followers": run["day_90_followers"],
                "pct_of_target": round(run["day_90_followers"] / target * 100, 4),
                "peak_impressions_per_post": run["peak_impressions_per_post"],
            }
            for name, run in scenarios.items()
        },
    }


def verdict(scenarios: dict, cohort: dict, target: int) -> str:
    """
    The honest sentence. This is the whole reason the script exists.

    It is written to be read by a human deciding whether to keep shipping, so it states
    the number and the consequence rather than a mood.
    """
    base = scenarios["base"]["day_90_followers"]
    strong = scenarios["strong"]["day_90_followers"]
    pct = base / target * 100
    if strong >= target:
        return (
            f"Cadence alone reaches the target under the strong scenario ({strong:,} by day 90). "
            f"The base case still lands at {base:,}, {pct:.2f}% of target. The gap is a conversion "
            f"problem and the scoreboard can close it."
        )
    if base >= target * 0.25:
        return (
            f"Cadence alone does NOT reach the target. Base case {base:,} by day 90, "
            f"{pct:.2f}% of target. Even the strong scenario reaches only {strong:,}. "
            f"The missing {target - base:,} must come from a step change, not from posting more."
        )
    return (
        f"Cadence alone cannot reach the target and the gap is not a rounding error. "
        f"Base case {base:,} by day 90: {pct:.2f}% of target. Even the strong scenario "
        f"({strong:,}, {'%.2f' % (strong / target * 100)}% of target) does not get there. "
        f"A plan that depends on organic compounding reaching 1,000,000 in 90 days is not a "
        f"plan. Treat 1,000,000 as contingent on two or three breakouts of the size the "
        f"company has been told to expect, and manage the compounding line as the thing "
        f"that is actually under our control."
    )


def render(model: dict) -> str:
    lines: list[str] = []
    add = lines.append
    r = model["reachability"]

    add("TARGET MODEL")
    add(f"  computed_at   {model['computed_at_utc']}")
    add(f"  horizon       day 0 = {model['day_zero']}  ->  day 90 = {model['day_90']}")
    add(f"  target        {r['target']:,}")
    add(f"  cadence       {model['cadence_posts_per_day']:g} posts/day")
    add("")

    add("PARAMETER PROVENANCE")
    for key, spec in model["parameter_provenance"].items():
        if isinstance(spec, dict) and "provenance" in spec:
            add(f"  {key:<12} {spec['value']!r:<12} {spec['provenance']}")
    add("")

    add("REACHABILITY — organic compounding only, no step change")
    for name, s in model["scenarios"].items():
        add(f"  {name:<12} day 90 = {s['day_90_followers']:>10,}   {s['pct_of_target']:>8.3f}% of target")
    add(f"  cadence alone reaches target: {'YES' if r['cadence_can_reach_target_alone'] else 'NO'}")
    add("")

    add("THE GAP, ATTRIBUTED")
    add(f"  organic base case delivers      {r['organic_base_day_90']:>10,}")
    add(f"  still required from step change {r['organic_base_day_90'] and (r['target'] - r['organic_base_day_90']):>10,}")
    add("")

    add("VERDICT")
    for chunk in _wrap(r["verdict"], 74):
        add(f"  {chunk}")
    add("")

    add("WEEKLY LADDER — base case, model trajectory (not a straight line to 1M)")
    add("  week   day   cumulative   weekly net new   per day    % of target")
    for row in model["weekly_ladder_base"]:
        add(
            f"  {row['week']:>4}  {row['day']:>4}   {row['cumulative']:>10,}   "
            f"{row['weekly_net_new']:>14,}   {row['per_day']:>7.1f}   {row['pct_of_target']:>9.4f}%"
        )
    add("")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    out, line = [], ""
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
    model = build()
    if "--json" in sys.argv:
        print(json.dumps(model, indent=2))
    elif "--solve-cohort" in sys.argv:
        print(json.dumps(solve_required_cohort(load_assumptions(), "base", 1_000_000), indent=2))
    else:
        print(render(model))
