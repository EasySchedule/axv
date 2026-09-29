# Weekly targets, per agent

Ember owns this file. The number changes; the rule does not: **every agent reports a
number, and a target too small to measure is not a target.**

Generated from `growth/scripts/cadence_plan.py`. Numbers regenerate weekly. Do not
hand-edit a number here to make a week look better.

## The headline, and it is not good news

The company is accountable for 1,000,000 followers in 90 days. I built the model that
asks whether that is reachable, and it is not reachable by posting. This is the
arithmetic, not an opinion:

| Lever | What it would take to reach 1,000,000 by cadence | Where we are | Multiple |
|---|---|---|---|
| More posts | 1,072 posts/day | 6/day | **179x** |
| Better conversion | 8.93% follows per impression | 0.05% | **179x** |
| More off-platform reach | 77,248 followers/week, every week | 0 | — |

At 6 posts/day the base case reaches **826 followers by day 90, which is 0.08% of
target.** The strong scenario, where every prior is simultaneously wrong in our favour,
reaches 3,465: 0.35%.

To be plain about what that means: 179x more volume is not a cadence change, it is a
different company. 8.93% follower conversion would mean roughly 1 in every 11
impressions follows the account. No account on X does that.

**So 1,000,000 in 90 days is a breakout target, not a cadence target.** It depends on
two or three posts breaking out at a scale the newsroom does not control and cannot
schedule. My honesty instruction says to say that early rather than let the team
optimise against a fiction, so I am saying it on day 1, and I will keep saying it until
either the compounding line surprises us or the run is re-scoped.

**What changes because of this:** the compounding line is what we actually manage. It is
small, it is real, and it is the thing that makes the next breakout convert. A breakout
that lands on an account with 800 followers converts a fraction of what it would on an
account with 80,000. The ladder is not consolation. It is the thing that makes the
contingent part of the target survivable.

## The account does not exist yet, and the clock does not care

`day_zero` is a calendar date. The calendar does not wait for the account to be created,
so a blocked account does not pause the target, it consumes it. Required velocity from
the moment the account goes live, indexed by how late that is:

| Start delay | Runway | Required/day | Required/week |
|---|---|---|---|
| on time | 90 days | 11,111 | 77,778 |
| +3d | 87 days | 11,494 | 80,460 |
| +7d | 83 days | 12,048 | 84,337 |
| +14d | 76 days | 13,158 | 92,105 |
| +21d | 69 days | 14,493 | 101,449 |
| +30d | 60 days | 16,667 | 116,667 |

This is the cost of [SIG-2](/SIG/issues/SIG-2) in the only unit the target is measured
in. Given the verdict above, a fortnight of delay does not change the shape of the run
— but it does mean the compounding line, which is the part we control, has two fewer
weeks to compound in. I would rather have the account on day 3 than day 17, and that is
worth saying out loud while it is still cheap to say.

## The growth line

```
company weekly target   63 followers
95% interval             47 to 79   (+-25%)
first measurable week    1
```

That interval is from a Poisson count: 95% half-width is `1.96 / sqrt(n)`. Below about
**43** an outcome rate is noise. This is why the per-agent numbers below are process
counts and not follower counts.

## Per-agent weekly targets

| Agent | Lever | Target | What they report |
|---|---|---|---|
| **Vanguard** | topics with >=5 mature posts | **2** | topics matured; median conversion by topic, or "not distinguishable" |
| **Dispatch** | posts shipped | **42** (6/day) | shipped vs 42; median impressions_24h, never the mean |
| **Relay** | replies under accounts >=10k followers | **30/day** | shipped vs 30/day; median impressions per reply; share with >=1 follow |
| **Prism** | chart posts | **7** | chart vs 7; chart median impressions vs non-chart, as a ratio |
| **Hound** | signal cards clearing the bar | **10** | cleared vs 10; share that became a shipped post within 48h |
| **Ledger** | readouts on Monday 09:00 UTC | **13** | on time vs 13; days since last *real* measurement |
| **Ember** | reallocation decisions, number attached | **1** | one per week: what was cut, what was doubled, the numbers behind it |

Counts above are exact process counts. The noise lives in the **outcomes** they produce,
not in the counts.

### Why Relay's is the highest-leverage number on this list

A zero-follower account cannot reach its own timeline. It has no audience to compound
through. The only non-breakout reach mechanism the newsroom controls is borrowed
attention: replies placed under accounts that already have an audience.

30 replies/day under accounts with >=10k followers is the single line most likely to be
quietly under-shipped, and it is the one that most directly moves discovery impressions,
which is the `discovery` term in the model. If we are going to be off the 1M path by
cadence, this is the line that makes the base case better than 826.

## Why nobody gets a follower target

Not a scaling problem. A structural one: **X does not attribute a follow to the post
that caused it**, so no agent can be handed a follower number that is honestly theirs.
Per-agent growth is tracked as a share of the compounding line until the user-context
credential makes even that an estimate:

| Lever | Share of compounding line |
|---|---|
| Vanguard (narrative/topics) | 20% |
| Dispatch (originating posts) | 35% |
| Relay (replies, borrowed reach) | 30% |
| Prism (charts) | 15% |

When the base case is 63 followers a week, six invented per-agent absolutes would be six
ways to be wrong in public. Shares are honest at that scale. Absolutes come later.

## The rule that overrides the table

**Volume is the last lever, never the first.** The model says 179x more posts still
misses the target, so "ship more" cannot be the answer to a bad week. The diagnostics
run in the order the growth-scorecard skill sets, and they are not reordered by anyone
who is having a bad week:

1. volume against cadence — under-shipping is the boring cause and the most common
2. impressions per post — flat means the ranking or the content
3. conversion per impression — flat while impressions rose means wrong audience, and
   the fix is topic, not volume
4. format mix — did the week drift into low-conversion formats?
5. off-platform — did the borrowed-attention channels go quiet?

## What would change my mind

The priors in `config/target_assumptions.json` are beliefs, and I will re-estimate them
from the board's own data once 12 mature posts exist. Two specific findings would move
the verdict, and I will publish whichever way they come out:

- **Discovery above ~3,000/post.** If our posts are reaching 15k non-followers, the base
  case is an order of magnitude better than 826 and the ladder is worth rebuilding.
- **Conversion above ~0.15%.** Above that, the compounding term starts to matter and the
  179x gap narrows enough to be arguable.

Equally: if week 4 shows impressions flat at the prior and conversion at 0.05%, then
826 is a good estimate and the 1,000,000 target needs re-scoping by whoever set it. I
will say so with the numbers attached, and I will not move the goalpost in the readout
to make the miss look like a plan.

## Where this came from

- `growth/scripts/target_model.py` — the compounding model, scenarios, required cohort
- `growth/scripts/cadence_plan.py` — these targets and the measurability gate
- `growth/scripts/target_selftest.py` — independent cross-check, RK4 vs day-step
- `growth/config/target_assumptions.json` — the priors, each with its own caveat
