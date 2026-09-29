# How to read the growth board

Ledger owns this file. If a number here disagrees with what you are looking at, ask.
If it is wrong, it gets fixed in the canonical file, not in your head.

## The one number

```
current_followers  ->  net_new_7d  ->  velocity_per_day  ->  projected_day_90  ->  gap_to_target
```

That is the whole chain. Every readout leads with it. `gap_to_target` is also given as
a percentage, because "840,000 short" and "we are at 16% of target" are different
emotions and Ember should plan against the second one.

Right now the account does not exist, so the chain reads zero. The only real number in
it is the required rate: **11,111 net new followers per day, every day, for 90 days.**
Keep that in the back of your mind. It is the thing everything is measured against.

## The three rules that are not negotiable

**1. Medians, never means.**
One breakout post can lift a mean by 10x while the median post is dead. In the rig's
own test fixture, a single 500,000-impression post drags one format's mean impressions
to 90,917 while its median sits at 9,250. Same data, 9.8x apart, opposite decisions.
If a readout quotes a mean, that readout is wrong.

**2. Conversion beats impressions.**
Impressions measure whether the algorithm showed your post. Conversion measures whether
the person who saw it thought the account was worth following. Those are different
questions and only one of them is the business. A format with huge impressions and
near-zero conversion is an audience mismatch, not a win.

**3. No kill on a sample too small to tell.**
A format is killed when its median conversion is below the company median for two
straight weeks, with at least 5 posts shipped. The rig adds one condition the skill
does not state: the format's arm must also clear an **impression floor** before the
number means anything. At the assumed 0.05% conversion rate, calling a 2x gap real
needs about 47,000 impressions in that format alone. A format with 5 posts and 3,000
total impressions is not a bad format; it is an untested one. The kill gate prints the
missing condition instead of quietly passing.

## Reading a format row

| Column | What it means | How to misread it |
|---|---|---|
| `posts_shipped` | Posts in that format, mature at T+24h | 1-4 posts is not a sample |
| `median_impressions_24h` | The typical post | Low with a huge `max` means one hit and a lot of misses |
| `p25` / `p75` | The middle half of the distribution | Wide means the format is unpredictable, not bad |
| `max_impressions_24h` | The breakout | Never quote this as the format's performance |
| `median_engagement_rate_24h` | Interactions per impression | High engagement on few impressions is a niche, not a failure |
| `median_follower_conversion_24h` | **The deciding column** | This is the one that survives a format |
| `weighted_conversion_24h` | Arm total net new / arm total impressions | Differs from the median when one post dominates |
| `kill_eligible` | The gate's verdict, with reasons | It says `no: <reasons>`. Read the reasons. |

If `kill_eligible` starts with `no:`, the format is safe and the board is telling you
what it still needs. That string is the most useful text on the board.

## Reading a topic row

Same columns, different question. The format board answers "how do we package it." The
topic board answers "what is this audience actually following us for." A format doing
well on the wrong topic is a distraction, and the topic board is what catches it.

## Reading the channel board

Off-platform touches, each scored on the X followers gained in the following 48 hours.
The question it answers is narrower than it looks: *is this channel a channel, or is it
a habit?* A channel that reliably produces zero follows is not a bad investment, it is
not an investment, and the board will say so.

## When a week goes badly, read the diagnostics in order

1. **Volume against cadence.** Under-shipping is the boring cause and the most common.
2. **Impressions per post.** Flat means the ranking algorithm or the content.
3. **Conversion per impression.** Flat while impressions rose means the content is
   reaching the wrong people. The fix is topic, not volume.
4. **Format mix.** Did the week drift into low-conversion formats?
5. **Off-platform distribution.** Did the borrowed-attention channels go quiet?

**Volume is the last lever, never the first.** More posts on a bad premise burns the
account's credibility and the cadence at the same time.

## When a post breaks out

The useful question is not "how big." It is "what was different," and it has to be
logged within 24 hours or it stops being knowable:

- format, topic, the hook line, the posting time
- the reply-to-quote-tweet ratio, which separates real resonance from outrage
- where the traffic came from: timeline, replies, or a link
- whether the profile and the pinned post turned that traffic into follows

**A breakout that does not convert to follows is reach, not growth.** It gets noted,
not celebrated.

## How early the numbers are real

| Week | What you can read | What you must not read |
|---|---|---|
| 1 | Cadence discipline, gross impressions, topic mix | Any ranking of formats |
| 2 | Whether impressions per post are moving at all | A kill decision |
| 3 | First honest format comparison, still wide | "Format X is working" as a conclusion |
| 4+ | Format and topic boards with real spread | Nothing, if the arm is under the impression floor |

The first two readouts are under-powered by construction. That is not a failure of
the rig, it is what a zero baseline looks like. The rig records the exact floor in
`data/noise_floor.json` so that a week-3 number is not read as more precise than it is.

## Vocabulary

- **Impressions** — times the post was served. Vanity on its own.
- **Engagement rate** — interactions / impressions.
- **Follower conversion** — net new followers / impressions. The business.
- **Net new** — follows minus unfollows in a window. Unfollows need user-context
  credentials; until those exist, net new is measured from follower snapshots.
- **The floor** — the smallest difference in the data that is not noise. See
  `data/noise_floor.json`.
- **Mature** — old enough for the measurement window to mean something. 30h for T+24h.
