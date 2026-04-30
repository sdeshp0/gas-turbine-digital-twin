"""
LTSAContract.py  —  InfraSure Gas Turbine Digital Twin
=======================================================
LTSA / CSA contract parameters and cost calculation functions for the
Athens pilot asset (GE 7FA.03 x2, NYISO Zone F).

All parameters sourced from Section 4.4.7 of InfraSure_ModelingFramework_V2.md.
Values marked [ASSUME] are modelling assumptions pending actual contract review.

Usage (from EnggDTwin_model.py):
    from LTSAContract import LTSAParams, daily_fixed_fee, daily_eoh_reserve,
                             inspection_cost, overage_charge, availability_penalty
"""

import numpy as np

# ---------------------------------------------------------------------------
# Contract parameters  (Section 4.4.7)
# ---------------------------------------------------------------------------
class LTSAParams:

    # -- Payment structure --------------------------------------------------
    FIXED_MONTHLY        = 850_000       # $/month fixed base fee  [ASSUME]
    EOH_RATE             = 175.0         # $/EOH variable reserve  [ASSUME]
    VOM_LTSA             = 1.50          # $/MWh LTSA VOM component (within total VOM)
    ESCALATION_ANNUAL    = 0.035         # annual PPI cap (3.5%)    [ASSUME]

    # -- Inspection costs and OEM coverage fractions -----------------------
    # CI (both GTs, mid-point of range)
    CI_COST_TOTAL        = 3_750_000     # $ total  [ASSUME mid of $3–4.5M]
    CI_OEM_FRACTION      = 0.75          # OEM covers 75%          [ASSUME]
    CI_OUTAGE_DAYS       = 12            # planned outage days      [ASSUME mid]

    # MI (both GTs, mid-point of range)
    MI_COST_TOTAL        = 30_000_000    # $ total  [ASSUME mid of $25–35M]
    MI_OEM_FRACTION      = 0.65          # OEM covers 65%          [ASSUME]
    MI_OUTAGE_DAYS       = 52            # planned outage days      [ASSUME mid]

    # Derived: owner-paid uncovered portions
    CI_OWNER_COST        = CI_COST_TOTAL  * (1 - CI_OEM_FRACTION)    # ~$937K
    MI_OWNER_COST        = MI_COST_TOTAL  * (1 - MI_OEM_FRACTION)    # ~$10.5M

    # -- EOH inspection triggers -------------------------------------------
    EOH_CI_1             = 32_000        # first CI trigger
    EOH_CI_2             = 40_000        # second CI trigger
    EOH_MI               = 48_000        # major inspection trigger
    EOH_INITIAL          = 24_000        # starting EOH (post-HGP)

    # Ordered list of (eoh_trigger, inspection_type) for sequential checking
    INSPECTION_SCHEDULE  = [
        (EOH_CI_1, 'CI'),
        (EOH_CI_2, 'CI'),
        (EOH_MI,   'MI'),
    ]

    # -- Contracted start baseline (annual) --------------------------------
    BASELINE_HOT         = 150           # contracted hot starts/yr  [ASSUME]
    BASELINE_WARM        = 35            # contracted warm starts/yr [ASSUME]
    BASELINE_COLD        = 5             # contracted cold starts/yr [ASSUME]
    BASELINE_TRIP        = 3             # contracted trips/yr       [ASSUME]

    # -- Overage charges (per excess event) --------------------------------
    OVERAGE_HOT          = 8_500         # $/excess hot start        [ASSUME]
    OVERAGE_WARM         = 42_000        # $/excess warm start       [ASSUME]
    OVERAGE_COLD         = 125_000       # $/excess cold start       [ASSUME]
    OVERAGE_TRIP         = 80_000        # $/excess trip             [ASSUME]

    # -- Performance guarantees --------------------------------------------
    AVAIL_GUARANTEE      = 0.95          # 95% availability guarantee [ASSUME]
    HR_GUARANTEE_PCT     = 0.020         # 2.0% HR tolerance          [ASSUME]

    # Availability penalty: uplift factor on monthly fee per 1% shortfall
    # Formula: (FIXED_MONTHLY/12) x (0.95 - actual) x 10
    AVAIL_PENALTY_FACTOR = 10.0          # multiplier on monthly fee  [ASSUME]

    # -- Days in projection period -----------------------------------------
    DAYS_PER_YEAR        = 365


# ---------------------------------------------------------------------------
# Cost functions  (called each day by the engineering model)
# ---------------------------------------------------------------------------

def daily_fixed_fee(day: int, year: int = 0) -> float:
    """
    Daily accrual of the fixed monthly LTSA base fee, with annual PPI escalation.

    Args:
        day  : day index within the year (0-364)
        year : projection year (0 = first year, for escalation)

    Returns:
        Daily fixed fee in USD.
    """
    escalated_monthly = LTSAParams.FIXED_MONTHLY * (1 + LTSAParams.ESCALATION_ANNUAL) ** year
    return escalated_monthly * 12 / LTSAParams.DAYS_PER_YEAR


def daily_eoh_reserve(delta_eoh: float, year: int = 0) -> float:
    """
    Daily variable EOH reserve accrual based on EOH accumulated that day.

    Args:
        delta_eoh : EOH accumulated today (fired hours + start penalties)
        year      : projection year for escalation

    Returns:
        Daily EOH reserve charge in USD.
    """
    escalated_rate = LTSAParams.EOH_RATE * (1 + LTSAParams.ESCALATION_ANNUAL) ** year
    return delta_eoh * escalated_rate


def inspection_cost(inspection_type: str) -> dict:
    """
    Returns the cost split for a planned inspection event.

    Args:
        inspection_type : 'CI' or 'MI'

    Returns:
        dict with keys: total, oem_covered, owner_uncovered, outage_days
    """
    if inspection_type == 'CI':
        return {
            'total':           LTSAParams.CI_COST_TOTAL,
            'oem_covered':     LTSAParams.CI_COST_TOTAL * LTSAParams.CI_OEM_FRACTION,
            'owner_uncovered': LTSAParams.CI_OWNER_COST,
            'outage_days':     LTSAParams.CI_OUTAGE_DAYS,
        }
    elif inspection_type == 'MI':
        return {
            'total':           LTSAParams.MI_COST_TOTAL,
            'oem_covered':     LTSAParams.MI_COST_TOTAL * LTSAParams.MI_OEM_FRACTION,
            'owner_uncovered': LTSAParams.MI_OWNER_COST,
            'outage_days':     LTSAParams.MI_OUTAGE_DAYS,
        }
    else:
        raise ValueError(f"Unknown inspection type: {inspection_type}")


def overage_charge(ytd_hot: int, ytd_warm: int, ytd_cold: int, ytd_trip: int,
                   day_of_year: int) -> float:
    """
    Compute cumulative overage charge to date based on YTD start counts vs.
    pro-rated annual contracted baseline.

    Overages are tracked YTD and billed when cumulative starts exceed the
    pro-rated annual threshold. Returns the INCREMENTAL overage charge for
    today (i.e. the change vs. yesterday's cumulative position).

    Args:
        ytd_hot/warm/cold/trip : cumulative YTD start counts (including today)
        day_of_year            : day number in year (1-365), for pro-rating

    Returns:
        Incremental overage charge in USD for today.
    """
    fraction = day_of_year / LTSAParams.DAYS_PER_YEAR

    def excess_cost(ytd, baseline, rate):
        pro_rated = baseline * fraction
        excess    = max(0, ytd - pro_rated)
        return excess * rate

    total = (excess_cost(ytd_hot,  LTSAParams.BASELINE_HOT,  LTSAParams.OVERAGE_HOT)
           + excess_cost(ytd_warm, LTSAParams.BASELINE_WARM, LTSAParams.OVERAGE_WARM)
           + excess_cost(ytd_cold, LTSAParams.BASELINE_COLD, LTSAParams.OVERAGE_COLD)
           + excess_cost(ytd_trip, LTSAParams.BASELINE_TRIP, LTSAParams.OVERAGE_TRIP))
    return total


def availability_penalty_annual(actual_availability: float,
                                 year: int = 0) -> float:
    """
    Annual availability penalty if actual availability falls below 95% guarantee.
    Applied at year-end; spread evenly across days in reporting.

    Formula (Section 4.4.5):
        penalty = (FIXED_MONTHLY / 12) x (0.95 - actual_avail) x 10
    Only triggered when actual_availability < AVAIL_GUARANTEE.

    Args:
        actual_availability : annual availability fraction (0-1)
        year                : projection year for escalation

    Returns:
        Total annual penalty in USD (0 if guarantee met).
    """
    if actual_availability >= LTSAParams.AVAIL_GUARANTEE:
        return 0.0
    shortfall    = LTSAParams.AVAIL_GUARANTEE - actual_availability
    monthly_base = LTSAParams.FIXED_MONTHLY * (1 + LTSAParams.ESCALATION_ANNUAL) ** year
    return (monthly_base / 12) * shortfall * LTSAParams.AVAIL_PENALTY_FACTOR


def hr_penalty_cycle(cycle_avg_hr: float,
                     contracted_hr: float,
                     cycle_mwh:     float,
                     avg_gas_price: float,
                     transport_adder: float = 0.12,
                     retainage:       float = 0.017) -> float:
    """
    Heat rate penalty applied at inspection cycle end if cycle-average HR
    exceeds contracted guarantee by more than HR_GUARANTEE_PCT.

    Formula (Section 4.4.5):
        excess_fuel_cost = (actual_hr - guaranteed_hr) / 1e6 * mwh * gas_delivered
        penalty = excess_fuel_cost * 1.25

    Args:
        cycle_avg_hr   : MWh-weighted average actual HR over cycle (BTU/kWh)
        contracted_hr  : contracted post-HGP baseline HR (BTU/kWh)
        cycle_mwh      : total MWh dispatched over the cycle
        avg_gas_price  : average delivered gas price $/MMBtu over cycle
        transport_adder: $/MMBtu fixed transport cost
        retainage      : fuel-in-kind fraction

    Returns:
        Heat rate penalty in USD (0 if guarantee met).
    """
    guaranteed_hr = contracted_hr * (1 + LTSAParams.HR_GUARANTEE_PCT)
    if cycle_avg_hr <= guaranteed_hr:
        return 0.0
    gas_delivered    = avg_gas_price * (1 + retainage) + transport_adder
    excess_hr        = cycle_avg_hr - guaranteed_hr            # BTU/kWh excess
    excess_fuel_cost = (excess_hr / 1e6) * cycle_mwh * gas_delivered * 1000
    return excess_fuel_cost * 1.25                              # 1.25x penalty factor


# ---------------------------------------------------------------------------
# Forced outage cost classification
# ---------------------------------------------------------------------------

def classify_forced_outage_cost(outage_type: str,
                                 repair_cost: float) -> dict:
    """
    Classify repair cost for a forced outage event as covered or uncovered
    under the LTSA, based on outage type.

    Coverage rules (Section 4.4.6):
    - GT mechanical failures within covered scope: OEM covered (zero owner cost)
    - HRSG / steam turbine: owner responsibility (excluded from LTSA)
    - BOP / background: owner responsibility (excluded from LTSA)
    - FOD / over-temperature: insurance (treated as uncovered here)

    Args:
        outage_type  : 'gt_covered', 'gt_excluded', 'hrsg', 'bop'
        repair_cost  : estimated repair cost in USD

    Returns:
        dict with 'oem_covered' and 'owner_uncovered' in USD
    """
    if outage_type == 'gt_covered':
        return {'oem_covered': repair_cost, 'owner_uncovered': 0.0}
    else:
        # hrsg, bop, gt_excluded — all owner responsibility
        return {'oem_covered': 0.0, 'owner_uncovered': repair_cost}


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    p = LTSAParams
    print("=== LTSAContract self-test ===")
    print(f"Daily fixed fee (yr 0):       ${daily_fixed_fee(0, 0):>12,.0f}")
    print(f"Daily fixed fee (yr 5):       ${daily_fixed_fee(0, 5):>12,.0f}")
    print(f"EOH reserve (50 EOH, yr 0):   ${daily_eoh_reserve(50, 0):>12,.0f}")
    ci = inspection_cost('CI')
    print(f"CI total cost:                ${ci['total']:>12,.0f}")
    print(f"  OEM covered:                ${ci['oem_covered']:>12,.0f}")
    print(f"  Owner uncovered:            ${ci['owner_uncovered']:>12,.0f}")
    mi = inspection_cost('MI')
    print(f"MI total cost:                ${mi['total']:>12,.0f}")
    print(f"  OEM covered:                ${mi['oem_covered']:>12,.0f}")
    print(f"  Owner uncovered:            ${mi['owner_uncovered']:>12,.0f}")
    ov = overage_charge(200, 50, 6, 4, 182)
    print(f"Overage (200 hot,50 warm,6 cold,4 trip at mid-yr): ${ov:>10,.0f}")
    ap = availability_penalty_annual(0.90)
    print(f"Availability penalty (90% actual): ${ap:>12,.0f}")
    hr_pen = hr_penalty_cycle(7_350, 7_070, 400_000, 4.0)
    print(f"HR penalty (7350 actual vs 7070 contracted, 400K MWh): ${hr_pen:>10,.0f}")
    print("=== OK ===")
