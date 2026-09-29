#!/usr/bin/env bash
# weekly.sh â€” the readout cycle. One command, in order, every week.
#
# Order matters: the noise floor is recomputed before the kill gate reads it, and the
# scoreboard is rebuilt before the gate judges it. Running the gate first would judge
# last week's numbers.
#
#   ./scripts/weekly.sh            # compute and print, write nothing
#   ./scripts/weekly.sh --write    # also write the scoreboards and the noise floor
#
# Expect it to fail loudly when there is no account. That is correct.

set -euo pipefail
cd "$(dirname "$0")/.."

WRITE=""
[ "${1:-}" = "--write" ] && WRITE="--write"

echo "=== 1/6  follower velocity ==========================================="
python scripts/velocity_model.py

echo
echo "=== 2/6  refresh metrics (skipped if no credentials) =================="
if [ -n "${X_BEARER_TOKEN:-}" ]; then
  python scripts/pull_x_metrics.py follower
  python scripts/pull_x_metrics.py posts
  if [ -n "${X_USER_ACCESS_TOKEN:-}" ]; then
    python scripts/pull_x_metrics.py followers-csv
  else
    echo "no X_USER_ACCESS_TOKEN: skipping the follow event stream."
    echo "per-post follower conversion will be attribution-free and coarse."
  fi
else
  echo "no X_BEARER_TOKEN: skipping all API pulls. Board shows last known state."
  echo "This is a credential gap, not a zero. Do not read the board as 'no growth'."
fi

echo
echo "=== 3/6  noise floor ================================================="
python scripts/noise_floor.py $WRITE

echo
echo "=== 4/6  scoreboards ================================================="
python scripts/scoreboard.py $WRITE

echo
echo "=== 5/7  kill gate ===================================================="
python scripts/kill_gate.py $WRITE

echo
echo "=== 6/7  target model (Ember) ========================================="
python scripts/target_model.py

echo
echo "=== 7/7  contract test on the verdict =================================="
# The target model drives three months of allocation off five unmeasured priors. This
# re-checks that the verdict is a property of the model and not of one arbitrary number.
python scripts/contract.py

echo
echo "=== board ============================================================="
python scripts/board.py --out reports/board.md

echo
echo "Next: write the readout. Lead with the velocity chain, name the worst number"
echo "in it, and say what caused it. No manufactured optimism."
