# Week 0 readout — the baseline, before anything ships

**Ledger, Growth Analyst. 2026-09-29. Pre-launch baseline.**

This is not a week of results. There are no results. This readout exists so that week 1
has something to be measured against, and so that nobody in week 3 mistakes a small
noisy number for a trend.

## The headline chain

```
current_followers   n/a   (account does not exist; SIG-2 is the blocker)
net_new_7d          n/a
velocity_per_day    n/a
projected_day_90    0
gap_to_target       1,000,000   (100% of target)
run_rate_vs_target  0.000%
```

Every field above except the last two is a schema placeholder, not a measurement. The
one real number in this section is the required rate:

> **11,111 net new followers per day, sustained for 90 days.**

That is what 1,000,000 in 90 days means, and the velocity script now reports it on
every run so it is never far from the reader's eye. For scale, that is roughly the
follower count a genuinely large account accumulates over several years, asked for in
three months. The goal is the goal; my job is to report the gap truthfully from week 1
instead of at week 12, when it stops being fixable.

## Format scoreboard

No posts shipped. Schema is fixed, nine format rows exist with zero posts, and rows
begin appending the moment the first post ships. Nothing is inferred from an empty table.

## Topic scoreboard

Same. Eight topic rows, zero posts, schema fixed.

## Channel scoreboard

No off-platform touches logged. Schema fixed.

## The noise floor, and why week 3 will lie to you

The baseline is zero, so the first real numbers will be small and noisy. Rather than
hand-wave "small sample", the rig computes the floor explicitly. `data/noise_floor.json`
holds it, recomputed weekly.

To call a 2x difference in follower conversion between two formats real — alpha 0.05,
power 0.80 — a format arm needs roughly:

| Assumed conversion rate | Impressions per arm | Posts at a 5,000 median |
|---|---|---|
| 0.02% | 117,697 | 24 |
| 0.05% | 47,057 | 10 |
| 0.10% | 23,511 | 5 |
| 0.20% | 11,737 | 3 |

Read the top of that table. If this account converts at 0.02% of impressions, then a
format with 5 posts has not been tested at all — it needs about 24 posts before its
median means anything.

Two honest caveats, both carried in the output file rather than buried here:

- **These are optimistic lower bounds.** They assume every impression is an independent
  trial. Real data is worse. Once 12 mature posts exist, the overdispersion parameter
  phi is estimated from the variance of per-post conversion counts and the floor is
  multiplied by `(1 + phi)`. On the rig's own test fixture phi came out at 1.64, which
  takes the 2x floor from 47,057 to **124,231 impressions per arm**.
- **The equal-exposure assumption is violated** — every post has a different impression
  count. phi is indicative and is re-estimated every week rather than trusted once.

## A change I made to the kill rule, and why

The skill's rule kills a format when its median conversion is below the company median
for two straight weeks with 5 posts shipped. At baseline that rule is a trap, and the
trap is specific: five posts in a low-exposure format will have a median conversion of
zero **because nobody saw them**, and zero is below the company median, so the rule
fires on a format that was never tested. The rule measures exposure and reports it as
quality.

So the kill gate now requires, in addition to the skill's three conditions, that the
format's arm clear the impression floor for the effect size being claimed. The gate
prints the missing condition rather than quietly passing:

```
one-claim   no: only 3 posts, need 5; 12,400 impressions, below the 47,057 floor;
                  1 consecutive week(s) below median, need 2
```

Below the floor, the correct output is "not distinguishable", and that is what gets
published. `kill_gate.py` also never outputs the word "kill" — it outputs `no`, or `no`
with reasons. The kill recommendation is a piece of prose in the weekly readout with
the numbers attached, for Vanguard to act on. Code does not get to decide that a
content format is dead.

**A guard, not a veto.** A format that has genuinely earned a kill will clear the
floor, so this never protects a format that deserves to die. It only stops the board
from killing formats it has not measured.

## Verifying the rig rather than asserting it

`scripts/selftest.py` runs the real computation against a synthetic fixture with a known
answer, with no network. It proves the things most likely to be silently wrong:

- a 500,000-impression breakout is present as the format's max, and the median stays at
  9,250 while the mean would read 90,917 — a 9.8x gap, opposite decisions
- the quiet high-conversion arm (900 median impressions, 0.111% conversion) outranks the
  loud low-conversion arm (9,250 impressions, 0% conversion)
- the company median is the median of per-post conversions, and is provably not the
  mean of the format medians (5.0e-06 against 3.7e-04, a 74x difference)
- `kill_eligible` is never auto-filled by the scoreboard
- overdispersion becomes estimable at 12 posts and raises the kill floor accordingly

All checks pass. Two real bugs were found and fixed by writing it: a crash on empty
stats, and an overdispersion estimator that mixed units by computing a variance
identity on rates instead of counts.

## What is blocked, and on whom

| Blocker | Owner | Effect |
|---|---|---|
| No X account, no username | [Ember](agent://6708b3ae-533f-435e-ae8c-e9dd93d7c214) via [SIG-2](/SIG/issues/SIG-2) | Every pull fails closed. Board cannot move off zero. |
| No X API credentials | Board, via secret proposal | No impressions, no per-post metrics, no velocity |
| No GitHub repository connected | Board | The rig has no version-controlled canonical home. See below. |

The rig fails closed on all three. It writes nothing and exits non-zero rather than
producing an empty file that would read downstream as "zero impressions" — a silent
zero is a lie about the data, and a lie about the data is the one thing this board is
not allowed to contain.

## The canonical-home problem, stated rather than hidden

The storage contract says GitHub is the record for everything version-controlled. There
is no repository connected to this company, and no Supabase project. So this rig's
canonical home right now is the project workspace plus these Paperclip issue
documents, and that is a deviation, not a decision I get to make silently. It is
recorded here so it is visible, and it should be closed by standing up the repository
and moving `growth/` into it.
