"""
dispatch_model.py  —  InfraSure Gas Turbine Digital Twin  (v2)
==============================================================
Enhancements over v1:
  1. Calendar-based maintenance scheduling — planned outages snap to the
     nearest April 1 or October 1 on or after the projected EOH trigger date.
     EOH overage (running past threshold while waiting for shoulder month)
     is penalised with an elevated P_forced multiplier.  A hard stop at
     EOH_OVERAGE_HARD_STOP overrides the calendar and triggers maintenance
     immediately.
  2. Three dispatch modes (A / B / C) — EOH-proximity penalty on start
     cost wear component.  Each mode runs independently (own state +
     stochastic draws) using the same pre-built maintenance calendar.
  3. Output: Mode A full daily arrays (gt_outputs_10yr.npz) +
             three-mode annual summary (gt_mode_comparison.npz).

Reads:  gt_market_inputs.npz
Saves:  outputs/gt_outputs_10yr.npz       (Mode A, full daily)
        outputs/gt_mode_comparison.npz    (all modes, annual)
"""

import numpy as np
import os, time
from datetime import date, timedelta
from EnggDTwin_model import (
    HR_ISO, CAP_ISO, VOM_BASE, TRANSPORT, RETAINAGE,
    MIN_RUN, MIN_DOWN, START_COST, EOH_FIRED, EOH_START,
    EOH_INTERVAL, EOH_INIT,
    cap_eff, hr_clean, hr_degraded, gas_delivered,
    insp_params, sample_tbc_threshold, sample_fo_duration,
    init_state, update_stress, p_forced_outage, apply_inspection_reset,
    FO_GT_REPAIR, FO_HRSG_REPAIR, FO_BOP_REPAIR,
)
from LTSAContract import (
    LTSAParams, daily_fixed_fee, daily_eoh_reserve, inspection_cost,
    overage_charge, availability_penalty_annual, classify_forced_outage_cost,
)

# ---------------------------------------------------------------------------
# Paths & dimensions
# ---------------------------------------------------------------------------
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, 'gt_market_inputs.npz')
OUT_DIR    = os.path.join(BASE_DIR, 'outputs')
OUT_FULL   = os.path.join(OUT_DIR, 'gt_outputs_10yr.npz')
OUT_MODES  = os.path.join(OUT_DIR, 'gt_mode_comparison.npz')

N_LONG_PATHS    = 50
N_YEARS         = 10
N_SIMS_PER_YEAR = 100
N_DAYS          = 365
TOTAL_DAYS      = N_YEARS * N_DAYS
SIM_START       = date(2025, 1, 1)

# ---------------------------------------------------------------------------
# Maintenance scheduling parameters
# ---------------------------------------------------------------------------
SHOULDER_MONTHS       = [4, 10]          # April and October
EOH_RATE_ESTIMATE     = None             # computed from input data (see below)
EOH_OVERAGE_HARD_STOP = 1_500            # EOH above threshold → force immediate maintenance
EOH_OVERAGE_PENALTY_MAX = 2.5           # max P_forced multiplier at hard stop
MODES = ['A', 'B', 'C']
# EOH rate multipliers for maintenance scheduling per mode.
# Mode C conserves EOH near thresholds → lower effective accumulation rate
# → inspections projected later → may fall in a later shoulder window
MODE_EOH_MULT = {'A': 1.00, 'B': 0.875, 'C': 0.65}

# ---------------------------------------------------------------------------
# EOH-proximity penalty by mode  (on start cost wear component)
# ---------------------------------------------------------------------------
def eoh_penalty_mult(headroom: float, mode: str) -> float:
    """
    Start cost wear multiplier based on EOH proximity to next threshold.
    Mode A: none.  Mode B: 1.0 → 2.5 over last 3,000 EOH.
    Mode C: 1.0 → 4.0 over last 4,000 EOH (steeper, earlier).
    """
    if mode == 'A' or headroom > 4_000:
        return 1.0
    elif mode == 'B':
        f = max(0.0, min(1.0, (4_000 - headroom) / 3_000))
        return 1.0 + 1.5 * f         # 1.0 → 2.5
    else:  # mode C
        f = max(0.0, min(1.0, (4_000 - headroom) / 4_000))
        return 1.0 + 3.0 * f         # 1.0 → 4.0

# ---------------------------------------------------------------------------
# Calendar maintenance scheduling
# ---------------------------------------------------------------------------

def next_shoulder_gd(after_gd: int) -> int:
    """Return global day index of the next April 1 or Oct 1 on or after after_gd."""
    d = SIM_START + timedelta(days=after_gd)
    for year in [d.year, d.year + 1, d.year + 2]:
        for month in SHOULDER_MONTHS:
            cand = date(year, month, 1)
            cand_gd = (cand - SIM_START).days
            if cand_gd >= after_gd:
                return cand_gd
    return TOTAL_DAYS  # fallback: end of simulation

def build_maint_schedule(eoh_rate: float) -> list:
    """
    Pre-build the maintenance calendar for a path.
    Returns: list of (scheduled_gd, inspection_type, eoh_threshold)
    ordered by scheduled_gd.
    """
    schedule = []
    current_eoh  = float(EOH_INIT)
    current_gd   = 0           # global day index after last outage end
    n_done       = 0

    for _ in range(40):        # max 40 inspections in 10 years
        thr, itype   = insp_params(n_done)
        eoh_needed   = thr - current_eoh
        days_to_thr  = max(1, int(eoh_needed / eoh_rate * 365))
        projected_gd = current_gd + days_to_thr
        sched_gd     = next_shoulder_gd(projected_gd)

        if sched_gd >= TOTAL_DAYS:
            break

        schedule.append((sched_gd, itype, thr))

        # Advance: EOH at scheduled date
        extra_days   = sched_gd - current_gd
        current_eoh += eoh_rate * extra_days / 365.0
        outage_days  = LTSAParams.CI_OUTAGE_DAYS if itype == 'CI' else LTSAParams.MI_OUTAGE_DAYS
        current_gd   = sched_gd + outage_days
        n_done      += 1

    return schedule

def estimate_eoh_rate(inp: dict) -> float:
    """
    Estimate expected EOH/year from average market inputs.
    Uses: average clean spark spread > 0 hours → fired hours/yr → EOH/yr from hours.
    Plus a start-based EOH contribution from typical dispatch patterns.
    """
    power = inp['power_price_mwh']   # (100,365,24)
    gas   = inp['gas_price_mmbtu']   # (100,365)
    temp  = inp['temperature_f']     # (100,365,24)

    # Average daily gas delivered
    gas_del = (gas.mean() * (1 + RETAINAGE) + TRANSPORT)
    # Average clean HR at average temperature
    avg_temp = float(temp.mean())
    from EnggDTwin_model import HR_AMBIENT_COEFF
    hr_avg   = HR_ISO * (1 + max(0, avg_temp - 59) * HR_AMBIENT_COEFF)
    fuel_per_mwh = hr_avg / 1_000.0 * gas_del

    # Fraction of hours with positive clean spark spread (proxy for dispatch fraction)
    spark_h = power.mean(axis=0) - fuel_per_mwh - VOM_BASE  # (365,24)
    dispatch_frac = float((spark_h > 0).mean())
    fired_hrs_yr  = dispatch_frac * 8_760.0

    # EOH from fired hours
    eoh_from_hours = fired_hrs_yr * EOH_FIRED

    # EOH from starts (rough estimate: ~1 start per 3 dispatch days, avg warm/hot mix)
    avg_eoh_per_start = 0.6 * EOH_START[1] + 0.3 * EOH_START[2] + 0.1 * EOH_START[3]
    starts_per_yr     = dispatch_frac * 365.0 / 3.0   # rough estimate
    eoh_from_starts   = starts_per_yr * avg_eoh_per_start

    total_rate = eoh_from_hours + eoh_from_starts
    print(f'  EOH rate estimate: {total_rate:.0f} EOH/yr '
          f'(hours={eoh_from_hours:.0f}, starts={eoh_from_starts:.0f})')
    return total_rate

# ---------------------------------------------------------------------------
# Hourly dispatch engine (with mode-based EOH penalty)
# ---------------------------------------------------------------------------

def hourly_dispatch(power_h, gas_del, hr_val, cap_val, vom,
                    op, hrs_off, run_hrs, min_run_cur, last_stype,
                    mode='A', eoh_headroom=99_999):
    """
    24-hour dispatch for one day. mode and eoh_headroom add EOH-proximity
    penalty to the start cost wear component (HRSG component unchanged).
    """
    fuel_cost_mwh = hr_val / 1_000.0 * gas_del
    GT_WEAR_FRAC  = 0.42   # wear component as fraction of total start cost

    mwh = rev = fuel = 0.0; fired = 0; starts = []
    cur_op, cur_off, cur_run, cur_mr, cur_ls = op, hrs_off, run_hrs, min_run_cur, last_stype
    penalty = eoh_penalty_mult(eoh_headroom, mode)

    for h in range(24):
        spark_h = power_h[h] - fuel_cost_mwh - vom

        if not cur_op:
            stype     = 1 if cur_off < 8 else (2 if cur_off < 72 else 3)
            can_start = cur_off >= MIN_DOWN[stype]
            base_cost = START_COST[stype]
            # Apply mode penalty to wear component only
            eff_cost  = base_cost * (1 - GT_WEAR_FRAC) + base_cost * GT_WEAR_FRAC * penalty
            hurdle    = eff_cost / (cap_val * MIN_RUN[stype])
            commit    = can_start and (spark_h > hurdle)
        else:
            stype  = cur_ls; hurdle = 0.0
            commit = (cur_run < cur_mr) or (spark_h > 0.0)

        if commit:
            if not cur_op:
                starts.append(stype)
                cur_op = True; cur_run = 1; cur_mr = MIN_RUN[stype]; cur_ls = stype
            else:
                cur_run += 1
            mwh  += cap_val; rev  += power_h[h] * cap_val
            fuel += cap_val * hr_val / 1_000.0; fired += 1; cur_off = 0
        else:
            if cur_op: cur_op = False; cur_run = 0
            cur_off += 1

    vom_c = mwh * vom; gas_c = fuel * gas_del
    return {
        'mwh': mwh, 'fired': fired, 'starts': starts,
        'power_rev': rev, 'gas_cost': gas_c, 'vom_cost': vom_c,
        'fuel_mmbtu': fuel, 'spark': rev - gas_c - vom_c,
        'op': cur_op, 'hrs_off': float(cur_off),
        'run_hrs': cur_run, 'min_run': cur_mr, 'last_stype': cur_ls,
    }

# ---------------------------------------------------------------------------
# Output arrays
# ---------------------------------------------------------------------------

def init_outputs():
    shape = (N_LONG_PATHS, TOTAL_DAYS); z = lambda: np.zeros(shape, dtype=np.float32)
    return dict(
        spark_clean=z(), loss_planned=z(), loss_degradation=z(),
        loss_forced=z(), spark_actual=z(),
        power_rev_actual=z(), gas_cost_actual=z(), vom_actual=z(),
        fuel_mmbtu_actual=z(), power_rev_clean=z(), gas_cost_clean=z(),
        fuel_mmbtu_clean=z(), hrs_clean=z(), hrs_actual=z(),
        hrs_planned=z(), hrs_forced_gt=z(), hrs_forced_hrsg=z(), hrs_forced_bop=z(),
        eoh=z(), hr_total_pct=z(), fouling_pct=z(), dc_creep=z(),
        df_fatigue=z(), d_interact=z(), tbc_time=z(), hrsg_drum_cycles=z(),
        rotor_life=z(), ltsa_fixed=z(), ltsa_eoh_reserve=z(),
        ltsa_major_cov=z(), ltsa_major_uncov=z(), ltsa_overage=z(),
        ltsa_avail_penalty=z(), inspection_event=z(),
        maint_scheduled=z(),   # 1 on days with a calendar-scheduled outage
        eoh_overage_days=z(),  # days running past EOH threshold
    )

# ---------------------------------------------------------------------------
# Single-mode path simulation
# ---------------------------------------------------------------------------

def run_path(j: int, mode: str, inp: dict, maint_schedule: list,
             rng: np.random.Generator) -> dict:
    """
    Run one 10-year simulation path for a given dispatch mode.
    Returns a dict of (TOTAL_DAYS,) arrays for this path.
    """
    temp_arr  = inp['temperature_f']
    aqi_arr   = inp['air_quality_idx']
    power_arr = inp['power_price_mwh']
    gas_arr   = inp['gas_price_mmbtu']

    # --- State ---
    st = init_state(rng)
    cl = dict(op=False, hrs_off=720.0, run_hrs=0, min_run=0, last_stype=3)

    # --- Maintenance calendar (copy so we can pop) ---
    pending = list(maint_schedule)   # [(sched_gd, itype, threshold), ...]

    cyc_mwh = cyc_hw = cyc_g = 0.0; cyc_gd = 0

    # Pre-allocate daily output arrays for this path
    keys = ['spark_clean','loss_planned','loss_degradation','loss_forced','spark_actual',
            'power_rev_actual','gas_cost_actual','vom_actual','fuel_mmbtu_actual',
            'power_rev_clean','gas_cost_clean','fuel_mmbtu_clean',
            'hrs_clean','hrs_actual','hrs_planned',
            'hrs_forced_gt','hrs_forced_hrsg','hrs_forced_bop',
            'eoh','hr_total_pct','fouling_pct','dc_creep','df_fatigue','d_interact',
            'tbc_time','hrsg_drum_cycles','rotor_life',
            'ltsa_fixed','ltsa_eoh_reserve','ltsa_major_cov','ltsa_major_uncov',
            'ltsa_overage','ltsa_avail_penalty','inspection_event',
            'maint_scheduled','eoh_overage_days']
    path_out = {k: np.zeros(TOTAL_DAYS, dtype=np.float32) for k in keys}

    for y in range(N_YEARS):
        sim = j + y * N_SIMS_PER_YEAR
        y0  = y * N_DAYS
        ytd_h = ytd_w = ytd_c = ytd_t = 0
        prev_ov = 0.0; avail_h = 0.0

        for d in range(N_DAYS):
            gd      = y0 + d
            doy     = d + 1
            yr_frac = gd / TOTAL_DAYS

            temp_h = temp_arr[sim, d, :]; aqi_h  = aqi_arr[sim, d, :]
            pw_h   = power_arr[sim, d, :]; gas_d  = float(gas_arr[sim, d])
            avg_t  = float(temp_h.mean()); avg_aqi= float(aqi_h.mean())
            gas_del_v = gas_delivered(gas_d)
            fix_fee   = daily_fixed_fee(d, year=y)

            hr_cl = hr_clean(avg_t)
            hr_dg = hr_degraded(st['hr_recov'], st['fouling'], avg_t)
            cap_d = cap_eff(avg_t)

            # EOH headroom to next scheduled threshold
            next_threshold = pending[0][2] if pending else st['eoh'] + 99_999
            eoh_headroom   = max(0.0, next_threshold - st['eoh'])

            # Clean dispatch (always mode A — reference, no EOH penalty)
            cr = hourly_dispatch(pw_h, gas_del_v, hr_cl, cap_d, VOM_BASE,
                                  cl['op'], cl['hrs_off'], cl['run_hrs'],
                                  cl['min_run'], cl['last_stype'], 'A', 99_999)
            cl.update({k: cr[k] for k in ['op','hrs_off','run_hrs','min_run','last_stype']})

            # Degraded counterfactual (for attribution, uses mode for dispatch)
            dr = hourly_dispatch(pw_h, gas_del_v, hr_dg, cap_d, VOM_BASE,
                                  st['op'], st['hrs_off'], st['run_hrs'],
                                  st['min_run'], st['last_stype'], mode, eoh_headroom)

            # Store clean reference
            path_out['spark_clean'][gd]      = cr['spark']
            path_out['power_rev_clean'][gd]  = cr['power_rev']
            path_out['gas_cost_clean'][gd]   = cr['gas_cost']
            path_out['fuel_mmbtu_clean'][gd] = cr['fuel_mmbtu']
            path_out['hrs_clean'][gd]        = cr['fired']
            path_out['ltsa_fixed'][gd]       = fix_fee

            def ws():
                path_out['eoh'][gd]             = st['eoh']
                path_out['hr_total_pct'][gd]    = st['hr_recov'] + st['fouling']
                path_out['fouling_pct'][gd]     = st['fouling']
                path_out['dc_creep'][gd]        = st['dc']
                path_out['df_fatigue'][gd]      = st['df']
                path_out['d_interact'][gd]      = st['dc'] + st['df']
                path_out['tbc_time'][gd]        = st['tbc_time']
                path_out['hrsg_drum_cycles'][gd]= st['hrsg_cycles']
                path_out['rotor_life'][gd]      = st['rotor_life']

            # ── Continuing outage ─────────────────────────────────────────
            if st['outage_days'] > 0:
                st['outage_days'] -= 1
                ot = st['outage_type']
                if st['outage_days'] == 0:
                    if ot and 'planned' in ot:
                        itype = ot.replace('planned_', '').upper()
                        hp = apply_inspection_reset(st, itype, rng, cyc_mwh, cyc_hw, cyc_g, cyc_gd)
                        path_out['ltsa_major_uncov'][gd] += hp
                        cyc_mwh = cyc_hw = cyc_g = 0.0; cyc_gd = 0
                    st['op'] = False; st['hrs_off'] = 24.0
                    st['run_hrs'] = 0; st['outage_type'] = None

                if ot and 'planned' in ot:
                    path_out['loss_planned'][gd]  = cr['spark']
                    path_out['hrs_planned'][gd]   = 24.0
                else:
                    path_out['loss_forced'][gd]       = dr['spark']
                    path_out['loss_degradation'][gd]  = cr['spark'] - dr['spark']
                    cause = (ot or '').replace('forced_','')
                    if cause == 'gt':   path_out['hrs_forced_gt'][gd]   = 24.0
                    elif cause=='hrsg': path_out['hrs_forced_hrsg'][gd] = 24.0
                    elif cause=='bop':  path_out['hrs_forced_bop'][gd]  = 24.0
                    avail_h += 24.0
                ws(); continue

            # ── Calendar maintenance check ────────────────────────────────
            # Hard stop: if EOH far past threshold and still waiting → force now
            if pending and st['eoh'] >= pending[0][2] + EOH_OVERAGE_HARD_STOP:
                sched_gd, itype, thr = pending.pop(0)
                cost = inspection_cost(itype)
                path_out['ltsa_major_cov'][gd]   = cost['oem_covered']
                path_out['ltsa_major_uncov'][gd] = cost['owner_uncovered']
                path_out['inspection_event'][gd] = 1 if itype=='CI' else 2
                path_out['maint_scheduled'][gd]  = 2.0  # 2 = hard stop
                st['outage_type'] = f'planned_{itype.lower()}'
                st['outage_days'] = cost['outage_days']
                path_out['loss_planned'][gd] = cr['spark']
                path_out['hrs_planned'][gd]  = 24.0
                ws(); continue

            # Calendar-scheduled maintenance date
            if pending and gd >= pending[0][0]:
                sched_gd, itype, thr = pending.pop(0)
                cost = inspection_cost(itype)
                path_out['ltsa_major_cov'][gd]   = cost['oem_covered']
                path_out['ltsa_major_uncov'][gd] = cost['owner_uncovered']
                path_out['inspection_event'][gd] = 1 if itype=='CI' else 2
                path_out['maint_scheduled'][gd]  = 1.0  # 1 = calendar
                st['outage_type'] = f'planned_{itype.lower()}'
                st['outage_days'] = cost['outage_days']
                path_out['loss_planned'][gd] = cr['spark']
                path_out['hrs_planned'][gd]  = 24.0
                ws(); continue

            # ── EOH overage penalty on P_forced ──────────────────────────
            eoh_overage = max(0.0, st['eoh'] - next_threshold) if pending else 0.0
            overage_mult = 1.0 + (EOH_OVERAGE_PENALTY_MAX - 1.0) * min(1.0, eoh_overage / EOH_OVERAGE_HARD_STOP)
            if eoh_overage > 0:
                path_out['eoh_overage_days'][gd] = 1.0

            # ── Forced outage ─────────────────────────────────────────────
            avail_h += 24.0
            p_tot, p_gt, p_hr, p_bg = p_forced_outage(st, yr_frac)
            p_tot_adj = min(1.0, p_tot * overage_mult)

            if rng.random() < p_tot_adj:
                wts   = np.array([p_gt, p_hr, p_bg]); wts /= wts.sum()
                cause = ['gt','hrsg','bop'][rng.choice(3, p=wts)]
                rep   = {'gt': FO_GT_REPAIR, 'hrsg': FO_HRSG_REPAIR, 'bop': FO_BOP_REPAIR}[cause]
                cs    = classify_forced_outage_cost('gt_covered' if cause=='gt' else cause, rep)
                path_out['ltsa_major_cov'][gd]   += cs['oem_covered']
                path_out['ltsa_major_uncov'][gd] += cs['owner_uncovered']
                path_out['loss_forced'][gd]       = dr['spark']
                path_out['loss_degradation'][gd]  = cr['spark'] - dr['spark']
                path_out[f'hrs_forced_{cause}'][gd] = 24.0
                st['outage_type'] = f'forced_{cause}'
                st['outage_days'] = sample_fo_duration(rng, cause)
                st['op'] = False; ws(); continue

            # ── Execute dispatch ──────────────────────────────────────────
            path_out['spark_actual'][gd]      = dr['spark']
            path_out['loss_degradation'][gd]  = cr['spark'] - dr['spark']
            path_out['hrs_actual'][gd]        = dr['fired']
            path_out['power_rev_actual'][gd]  = dr['power_rev']
            path_out['gas_cost_actual'][gd]   = dr['gas_cost']
            path_out['vom_actual'][gd]        = dr['vom_cost']
            path_out['fuel_mmbtu_actual'][gd] = dr['fuel_mmbtu']

            st['op'] = dr['op']; st['hrs_off'] = dr['hrs_off']
            st['run_hrs'] = dr['run_hrs']; st['min_run'] = dr['min_run']
            st['last_stype'] = dr['last_stype']

            update_stress(st, dr['fired'], dr['starts'], avg_t, avg_aqi)

            d_eoh  = dr['fired'] * EOH_FIRED + sum(EOH_START.get(int(c),0) for c in dr['starts'])
            eoh_res= daily_eoh_reserve(d_eoh, year=y)
            for c in dr['starts']:
                if c==1: ytd_h+=1
                elif c==2: ytd_w+=1
                elif c==3: ytd_c+=1
                elif c==0: ytd_t+=1
            cum_ov = overage_charge(ytd_h,ytd_w,ytd_c,ytd_t,doy)
            path_out['ltsa_eoh_reserve'][gd] = eoh_res
            path_out['ltsa_overage'][gd]     = max(0.0, cum_ov - prev_ov)
            prev_ov = cum_ov

            cyc_mwh += dr['mwh']; cyc_hw += dr['mwh'] * hr_dg
            cyc_g   += gas_d;     cyc_gd += 1
            ws()

        # Year-end availability penalty
        ann_av = avail_h / (N_DAYS * 24.0)
        ap = availability_penalty_annual(ann_av, year=y)
        if ap > 0:
            path_out['ltsa_avail_penalty'][y0 + N_DAYS - 1] = ap

    return path_out

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(seed: int = 42) -> tuple:
    inp = dict(np.load(INPUT_FILE))
    print(f'Loaded {INPUT_FILE}')

    # Estimate EOH accumulation rate and build shared maintenance calendar
    global EOH_RATE_ESTIMATE
    EOH_RATE_ESTIMATE = estimate_eoh_rate(inp)
    # Print Mode A calendar as reference; each mode gets its own schedule (see MODE_EOH_MULT)
    ref_sched = build_maint_schedule(EOH_RATE_ESTIMATE)
    print(f'Mode A maintenance calendar ({len(ref_sched)} events):')
    for gd, itype, thr in ref_sched[:6]:
        d = SIM_START + timedelta(days=gd)
        print(f'  {d.strftime("%b %Y")}  {itype}  (threshold={thr:,} EOH)')
    ref_sched_c = build_maint_schedule(EOH_RATE_ESTIMATE * MODE_EOH_MULT["C"])
    print(f'Mode C maintenance calendar ({len(ref_sched_c)} events — fewer due to conservative dispatch):')
    for gd, itype, thr in ref_sched_c[:6]:
        d = SIM_START + timedelta(days=gd)
        print(f'  {d.strftime("%b %Y")}  {itype}  (threshold={thr:,} EOH)')

    # Full outputs for Mode A
    out_A = {k: np.zeros((N_LONG_PATHS, TOTAL_DAYS), dtype=np.float32)
             for k in [
                'spark_clean','loss_planned','loss_degradation','loss_forced','spark_actual',
                'power_rev_actual','gas_cost_actual','vom_actual','fuel_mmbtu_actual',
                'power_rev_clean','gas_cost_clean','fuel_mmbtu_clean',
                'hrs_clean','hrs_actual','hrs_planned',
                'hrs_forced_gt','hrs_forced_hrsg','hrs_forced_bop',
                'eoh','hr_total_pct','fouling_pct','dc_creep','df_fatigue','d_interact',
                'tbc_time','hrsg_drum_cycles','rotor_life',
                'ltsa_fixed','ltsa_eoh_reserve','ltsa_major_cov','ltsa_major_uncov',
                'ltsa_overage','ltsa_avail_penalty','inspection_event',
                'maint_scheduled','eoh_overage_days',
             ]}

    # Mode comparison: shape (3 modes, N_PATHS, TOTAL_DAYS) for key metrics
    mode_spark  = np.zeros((3, N_LONG_PATHS, TOTAL_DAYS), dtype=np.float32)
    mode_hrs    = np.zeros((3, N_LONG_PATHS, TOTAL_DAYS), dtype=np.float32)
    mode_ltsa   = np.zeros((3, N_LONG_PATHS, TOTAL_DAYS), dtype=np.float32)

    t0 = time.time()
    print(f'\nRunning {N_LONG_PATHS} paths x {len(MODES)} modes ...')

    for j in range(N_LONG_PATHS):
        for mi, mode in enumerate(MODES):
            rng = np.random.default_rng(seed + j * 100)
            mode_rate = EOH_RATE_ESTIMATE * MODE_EOH_MULT[mode]
            mode_schedule = build_maint_schedule(mode_rate)
            path_out = run_path(j, mode, inp, mode_schedule, rng)

            # Store Mode A full outputs
            if mode == 'A':
                for k in out_A:
                    out_A[k][j] = path_out[k]

            # Key metrics for comparison
            ltsa_total = (path_out['ltsa_fixed'] + path_out['ltsa_eoh_reserve'] +
                          path_out['ltsa_major_cov'] + path_out['ltsa_major_uncov'] +
                          path_out['ltsa_overage'] + path_out['ltsa_avail_penalty'])
            mode_spark[mi, j] = path_out['spark_actual']
            mode_hrs[mi, j]   = path_out['hrs_actual']
            mode_ltsa[mi, j]  = ltsa_total

        eoh_end = float(out_A['eoh'][j, -1])
        insp_ci = int((out_A['inspection_event'][j] == 1).sum())
        insp_mi = int((out_A['inspection_event'][j] == 2).sum())
        ov_days = int(out_A['eoh_overage_days'][j].sum())
        print(f'  path {j+1:2d}  EOH={eoh_end:.0f}  CI={insp_ci}  MI={insp_mi}  '
              f'overage_days={ov_days}  elapsed {time.time()-t0:.1f}s')

    print(f'Done in {time.time()-t0:.1f}s')
    return out_A, mode_spark, mode_hrs, mode_ltsa

def save(out_A, mode_spark, mode_hrs, mode_ltsa):
    os.makedirs(OUT_DIR, exist_ok=True)
    np.savez_compressed(OUT_FULL, **out_A)
    np.savez_compressed(OUT_MODES,
        spark=mode_spark, hrs=mode_hrs, ltsa=mode_ltsa,
        modes=np.array(['A','B','C']))
    print(f'Saved {OUT_FULL}  ({os.path.getsize(OUT_FULL)/1e6:.1f} MB)')
    print(f'Saved {OUT_MODES}  ({os.path.getsize(OUT_MODES)/1e6:.1f} MB)')

def print_summary(out_A, mode_spark, mode_hrs, mode_ltsa):
    tot = TOTAL_DAYS * 24
    def p(lbl, arr, fmt='.1f', u=''):
        v = np.percentile(arr,[10,50,90])
        print(f'  {lbl:<46} P10={v[0]:{fmt}}  P50={v[1]:{fmt}}  P90={v[2]:{fmt}} {u}')

    print('\n=== Mode A summary ===')
    p('CF actual (%)',       out_A['hrs_actual'].sum(1)/tot*100,    u='%')
    p('Planned outage (%)',  out_A['hrs_planned'].sum(1)/tot*100,   u='%')
    p('Forced GT (%)',       out_A['hrs_forced_gt'].sum(1)/tot*100, u='%')
    p('Forced HRSG (%)',     out_A['hrs_forced_hrsg'].sum(1)/tot*100,u='%')
    p('Spark actual ($M/yr)',out_A['spark_actual'].sum(1)/N_YEARS/1e6,u='$M')
    p('EOH overage days',   out_A['eoh_overage_days'].sum(1), fmt='.0f')
    p('CI events',          (out_A['inspection_event']==1).sum(1),  fmt='.0f')
    p('MI events',          (out_A['inspection_event']==2).sum(1),  fmt='.0f')

    print('\n=== Mode comparison (avg spark spread $M/yr) ===')
    for mi, mode in enumerate(MODES):
        avg_spark = mode_spark[mi].sum(axis=1).mean() / N_YEARS / 1e6
        avg_cf    = (mode_hrs[mi].sum(axis=1).mean() / tot) * 100
        avg_ltsa  = mode_ltsa[mi].sum(axis=1).mean() / 1e6
        print(f'  Mode {mode}: spark=${avg_spark:.1f}M/yr  CF={avg_cf:.1f}%  LTSA=${avg_ltsa:.0f}M/10yr')

if __name__ == '__main__':
    out_A, ms, mh, ml = run()
    save(out_A, ms, mh, ml)
    print_summary(out_A, ms, mh, ml)
