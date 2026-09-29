"""Independent cross-check of target_model.py. Different method, same question.

Deliberately does NOT import target_model. It re-derives the three load-bearing numbers
by a different route so a bug in one does not silently validate the other.

  1. Organic-only day 90, closed form (no day-step loop).
  2. Required off-platform cohort, checked by substitution rather than bisection.
  3. The conversion rate that WOULD make cadence alone reach 1M, by bisection.
  4. The cadence that WOULD reach 1M at the prior conversion, by bisection.
     -> answers "is this a content problem or a volume problem", which is the question
        the company keeps asking.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
A = json.loads((ROOT / "config" / "target_assumptions.json").read_text(encoding="utf-8"))
S = A["scenarios"]["base"]
TARGET = 1_000_000
DAYS = 90
PPD = float(A["posts_per_day"])
CONV = float(S["conversion"])
DISC = float(S["discovery"])
SHARE = float(S["follower_share"])
SCALE = float(S["reach_scale"])

K = SHARE * SCALE  # so that share*F*scale/(scale+F) == K*F/(scale+F)


def f_and_rate(F):
    return DISC + K * F / (SCALE + F), PPD * (DISC + K * F / (SCALE + F)) * CONV


# ---- 1. closed form, no loop -------------------------------------------------
# dF/dt = PPD*DISC*CONV + PPD*CONV*K*F/(SCALE+F)
# Split the term: K*F/(SCALE+F) = K - K*SCALE/(SCALE+F) = K - K/(1+F/SCALE)
# So dF/dt = a + b*F - c/(1+F/SCALE) with a = PPD*DISC*CONV, b = PPD*CONV*K, c = b*SCALE
# Substitute G = 1 + F/SCALE  ->  dG/dt = (1/SCALE) dF/dt
#   dG/dt = (a + b*SCALE*(G-1) - c)/SCALE = (a - b*SCALE + b*SCALE*G - b*SCALE)/SCALE
#          = (a - 2*b*SCALE + b*SCALE*G)/SCALE
# Not separable, so integrate with a very fine independent step (1/100 day) using
# RK4. Different integrator, same recurrence -> catches day-step and RK4 bugs.
def rk4(days, cohort_per_day=0.0, h=0.01):
    F, t = 0.0, 0.0
    while t < days - 1e-12:
        h = min(h, days - t)
        k1 = f_and_rate(F)[1] + cohort_per_day
        k2 = f_and_rate(F + h / 2 * k1)[1] + cohort_per_day
        k3 = f_and_rate(F + h / 2 * k2)[1] + cohort_per_day
        k4 = f_and_rate(F + h * k3)[1] + cohort_per_day
        F += h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        t += h
    return F


def day_step(days, cohort_per_day=0.0):
    """Mirror of target_model.simulate: integer days, Euler."""
    F = 0.0
    for _ in range(days):
        F += f_and_rate(F)[1] + cohort_per_day
    return F


organic_rk4 = rk4(DAYS)
organic_euler = day_step(DAYS)

# ---- 2. required cohort, by substitution -------------------------------------
lo, hi = 0.0, 200_000.0
for _ in range(300):
    mid = (lo + hi) / 2
    if day_step(DAYS, mid / 7) >= TARGET:
        hi = mid
    else:
        lo = mid
required_cohort_week = hi
verify = day_step(DAYS, required_cohort_week / 7)

# ---- 3. conversion that makes cadence alone reach 1M ------------------------
lo, hi = 1e-9, 10.0
for _ in range(300):
    mid = (lo + hi) / 2
    saved = CONV
    CONV = mid
    v = day_step(DAYS)
    CONV = saved
    if v >= TARGET:
        hi = mid
    else:
        lo = mid
required_conversion = hi

# ---- 4. cadence that reaches 1M at the prior conversion ---------------------
lo, hi = 0.1, 1e7
for _ in range(300):
    mid = (lo + hi) / 2
    saved = PPD
    PPD = mid
    v = day_step(DAYS)
    PPD = saved
    if v >= TARGET:
        hi = mid
    else:
        lo = mid
required_cadence = hi

print(f"organic day90  RK4(h=0.01)      {organic_rk4:>14,.1f}")
print(f"organic day90  day-step Euler   {organic_euler:>14,.1f}")
print(f"integrator spread               {abs(organic_rk4 - organic_euler):>14,.4f}  ({abs(organic_rk4-organic_euler)/organic_rk4*100:.4f}%)")
print()
print(f"required off-platform cohort    {required_cohort_week:>14,.1f} / week")
print(f"  substitution check            {verify:>14,.1f} followers at day 90  (target {TARGET:,})")
print()
print(f"conversion needed for 1M        {required_conversion:>14.6%}   (prior {CONV:.4%})")
print(f"  multiple of prior             {required_conversion/CONV:>14,.1f}x")
print()
print(f"cadence needed for 1M           {required_cadence:>14,.0f} posts/day  (prior {PPD:g})")
print(f"  multiple of prior             {required_cadence/PPD:>14,.1f}x")
print()
print(f"impressions required/day for 1M at prior conversion "
      f"{TARGET/CONV:>12,.0f}")
print(f"  ...at the prior 6 posts/day  {TARGET/CONV/PPD:>12,.0f} impressions per post")
