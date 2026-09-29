# axv

One repository, one history. This is the canonical home for everything that is
version-controlled on this account: the growth scoreboard, the reading corpus, the
experiment harness, and the white paper.

## growth/ — the growth scoreboard

The measurement rig. Read `growth/README.md` first; it is the one-pager written for the
whole company, not for analysts.

```
growth/
  README.md                    how to read the board
  SCHEMA.md                    every file, every column, the kill rule
  WEEKLY-TARGETS.md            the weekly ladder and the per-agent process targets
  config/account.json          account identity, measurement windows, kill policy
  config/target_assumptions.json  PRIOR parameters, re-estimated from data when estimable
  data/                        the ledgers. Append-only. Nothing is rewritten in place.
  scripts/                     the pipeline
  reports/                     generated readouts
```

The pipeline, in the order it must run:

```
python scripts/velocity_model.py      # the headline chain
python scripts/pull_x_metrics.py follower
python scripts/pull_x_metrics.py posts
python scripts/noise_floor.py --write # the floor, before the gate reads it
python scripts/scoreboard.py --write
python scripts/kill_gate.py --write
python scripts/board.py --out reports/board.md
```

`scripts/selftest.py` and `scripts/target_selftest.py` are the proofs. They run the real
computation against fixtures with known answers. If a change to this rig does not leave
both green, the change is not finished.

## Three rules the rig enforces on itself

1. **Medians, never means.** One breakout post can lift a mean 10x while the median post
   is dead. `selftest.py` proves this with a fixture where the two disagree by 9.8x.
2. **Conversion beats impressions.** Impressions measure reach. Follower conversion per
   impression measures whether the account is worth following. Only one is the business.
3. **No conclusion under the noise floor.** `noise_floor.py` computes the smallest
   difference in the data that is not noise. The kill gate refuses to fire below it and
   prints the missing condition instead of passing quietly.

## Secrets

No credential lives in this repository. The pull scripts read the process environment
only. They never read a token from a file and never accept one as a command argument.
See `growth/SCHEMA.md` for which endpoints need which credential.
