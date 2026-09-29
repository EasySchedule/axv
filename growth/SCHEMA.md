# Growth scoreboard schema

Every file, what it holds, who writes it, and the rule that keeps it honest. Schemas
are fixed now so rows can be appended the moment the first post ships, with no debate
about columns during week 1.

## Files

| File | Grain | Written by |
|---|---|---|
| `data/follower_snapshots.csv` | one row per pull | `pull_x_metrics.py follower` |
| `data/follows_daily.csv` | one row per day | `pull_x_metrics.py followers-csv` |
| `data/posts.csv` | one row per post | `pull_x_metrics.py posts`, plus the publisher's format/topic |
| `data/formats.csv` | one row per format | fixed roster, do not reorder |
| `data/topics.csv` | one row per topic | fixed roster, do not reorder |
| `data/format_scoreboard.csv` | one row per format per week | `scoreboard.py --write` |
| `data/topic_scoreboard.csv` | one row per topic per week | `scoreboard.py --write` |
| `data/channel_scoreboard.csv` | one row per off-platform touch | Relay / Dispatch, logged by hand |
| `data/noise_floor.json` | one object | `noise_floor.py --write` |
| `config/account.json` | account identity and policy | Ledger, once the account exists |

`posts.csv` is append-only. A correction is a new row with a later `pulled_at_utc`; the
scoring scripts take the most recent pull per `post_id`. Nothing is ever rewritten
in place, because a rewritten metric has no audit trail and this board is the audit.

## The two columns the API cannot fill

`format` and `topic` are **not** in the X API. Nothing infers them. The publisher sets
them at ship time, in the same commit that ships the post, from the fixed rosters in
`formats.csv` and `topics.csv`. A post with a blank format is scored under no arm, which
is a loud failure rather than a silent miscount, and that is the intent.

A post with an unknown value gets added to its roster file first, then scored. Rosters
are append-only for the same reason the metrics are.

## Kill rule, with the guard the skill does not state

The skill's rule: median follower conversion below the company median, two consecutive
weeks, at least 5 posts shipped.

The guard, added here because the rule alone kills untested formats:

```
kill_eligible = below company median
             AND posts_shipped          >= 5
             AND total_impressions_24h   >= kill_floor_impressions_per_arm_2x
             AND consecutive weeks below >= 2
```

From `data/noise_floor.json`. At baseline the modelled kill floor is **47,057
impressions per format arm** for a 2x gap at an assumed 0.05% conversion rate, before
any overdispersion penalty. Once 12+ mature posts exist, phi is estimated from the
counts and the floor grows by `(1 + phi)`. On the rig's own fixture the estimate is
phi = 1.64, which nearly triples the floor to 124,231 impressions per arm.

So: **5 posts is a floor on sample count, not a licence to conclude.** Below the
impression floor, the correct output is "not distinguishable," and that is what
`kill_gate.py` writes.

### The column-name bug that made the gate dead code

`kill_gate.py` originally looked up `vs_company_median_24h`. `scoreboard.py` writes
`vs_company_median`, unsuffixed — it is a verdict on the whole arm, not a measurement
at one window. The lookup returned an empty string for every arm, "below the company
median" was therefore never true, and the gate returned `no` for everything
unconditionally. It printed confident verdicts, and the impression guard I had added
was never the binding condition because the gate short-circuited before reaching it.

Nothing in the original test suite caught it, because the original suite asserted the
gate *blocked* things and a gate that blocks everything passes that test. The fix
required asserting the opposite: that a fully-evidenced weak arm **clears**. Both
directions are now in `selftest.py`, and the test also asserts the column name itself
so a rename cannot silently reintroduce this.

Lesson worth carrying: a guard test that only checks the guard holds is a test of the
guard's existence, not its behaviour.

The two-week condition is checked against `data/history/`, which holds one scoreboard
snapshot per week. Empty history means the condition is unproven and the gate says so.

`kill_gate.py` never outputs "kill." It outputs `no` or `no: <reasons>`. The kill
recommendation is written by Ledger, in prose, in the weekly readout, with the numbers
attached, for Vanguard to act on. Code does not get to decide that a content format is
dead.

## Two windows, never mixed

T+24h is the primary window. T+7d is recorded alongside it. A T+24h number is never
compared to a T+7d number, because a post's impressions roughly double in the first
day and the comparison flatters whoever shipped earlier. A post is *mature* at 30h for
T+24h scoring and 168h for T+7d. Immature posts are excluded from the medians, not
averaged in as zeros.

## The noise floor, stated plainly

`noise_floor.py` answers one question: how many impressions must a format arm accumulate
before a difference between two formats can be called real?

Method: two-proportion comparison of follower conversion per impression, alpha 0.05,
power 0.80, then multiplied by `(1 + phi)` where phi is the negative-binomial
overdispersion parameter estimated from the variance of per-post conversion counts.

Two honest caveats, both of which appear in the output file:

1. **Until 12 mature posts exist, phi is unknown and the floors are optimistic lower
   bounds.** The file says `overdispersion_estimated: false` while this is true.
2. **The exponent assumption is violated** — every post has a different impression
   count, and the identity assumes equal exposure. phi is indicative. It is re-estimated
   every week rather than trusted once.

A floor that is known to be optimistic is still better than no floor. An unstated floor
is how a newsroom kills a format it never tested.

## What needs a credential

| Data | Endpoint | Auth | Cost (2026 pay-per-use) |
|---|---|---|---|
| Follower count | `GET /2/users/by/username/:u` | app-only bearer | $0.010, or $0.001 owned read |
| Impressions, likes, reposts, replies, quotes, bookmarks | `GET /2/users/:id/tweets` `tweet.fields=public_metrics` | app-only bearer | $0.005, or $0.001 owned read |
| Profile clicks, URL clicks, engagements | `tweet.fields=non_public_metrics` | **OAuth user context** | — |
| Per-follow event stream, daily follows | `GET /2/users/:id/followers` | **OAuth user context** | $0.010, or $0.001 owned read |
| Unfollows | not directly available | — | measure from snapshot deltas |

Consequence for the scoreboard, stated so nobody is surprised later: **with a bearer
token alone, per-post follower conversion is not directly measurable.** X does not
attribute follows to posts. Without user context, conversion is measured coarsely as
account-level net new followers over the window divided by total impressions, and rows
are stamped `metric_source=api_v2_public_only`. That number is real and it is
attribution-free. Both tokens are proposed as Paperclip secrets; neither is ever written
into this repository, a comment, a document, or a transcript.

The pull script reads credentials from the process environment only. It never reads a
token from a file, never accepts one as a command argument, and redacts anything
token-shaped out of error text before printing.
