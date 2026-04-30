"""
EnggDTwin_model.py  —  InfraSure GT Digital Twin  (engineering library)
========================================================================
Pure engineering model library imported by dispatch_model.py.
Provides: plant state management, stress accumulation, forced outage
probability, and inspection scheduling.

NOT a standalone runner — call from dispatch_model.py.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Plant constants  (Sections 4.1-4.8)
# ---------------------------------------------------------------------------
HR_ISO      = 7_070.0   # BTU/kWh HHV, post-HGP baseline at ISO
CAP_ISO     = 531.0     # MW net at ISO
VOM_BASE    = 2.50      # $/MWh total variable O&M
TRANSPORT   = 0.12      # $/MMBtu lateral + scheduling
RETAINAGE   = 0.017     # fuel-in-kind fraction

# Min run / min down time by start type  {1=hot, 2=warm, 3=cold}
MIN_RUN  = {1: 4,  2: 6,  3: 8}    # hours
MIN_DOWN = {1: 2,  2: 6,  3: 12}   # hours

# Start costs (GT + HRSG/ST combined, both units)  (Section 4.5)
START_COST = {1: 36_000, 2: 88_000, 3: 176_000}   # $

# EOH counting (Section 4.4.2 / GER-3620)
EOH_FIRED  = 1.0        # per fired hour
EOH_START  = {1: 50, 2: 150, 3: 350, 0: 500}      # per start by type

# ---------------------------------------------------------------------------
# Methodology assumptions  (Appendix B)
# ---------------------------------------------------------------------------
D_INTERACT_MIXED    = 0.70
CREEP_LIFE_BASE     = 100_000.0     # hours
CREEP_TEMP_FACTOR   = 0.005
DMG_IDX             = {1: 1.0, 2: 2.5, 3: 4.0, 0: 5.0}
COMB_BUDGET         = 500.0
HOCKEY_INFLECTION   = 0.60
FOULING_A           = 2.5           # % HR asymptotic impact
FOULING_TAU         = 1_000.0       # hours
AQI_NORMAL          = 25.0
WASH_RECOVERY       = 0.70
HGP_DEG_RATE        = 0.30          # %/yr recoverable HGP degradation
CI_RECOVERY_HGP     = 0.30
HGP_RECOVERY        = 0.75
DERATE_COEFF        = 0.005         # %/degF above 59F ISO
DERATE_MIN, DERATE_MAX = 0.80, 1.05
HR_AMBIENT_COEFF    = 0.00074       # %/degF above 59F ISO
TBC_BETA, TBC_ETA   = 3.0, 28_000.0
HRSG_DMG            = {1: 1.0, 2: 2.5, 3: 5.0, 0: 3.0}
ROTOR_LIFE_DESIGN   = 7_500.0
ROTOR_WT            = {1: 1.0, 2: 2.0, 3: 4.0, 0: 3.0}
P_HRSG_BASE         = 0.0075
P_BG_BASE           = 0.0040
P_ROTOR_BASE        = 0.00003
P_BG_AGE_MAX        = 1.5
FO_GT_MED, FO_HRSG_MED, FO_BOP_MED = 8.0, 12.0, 5.0
FO_SIGMA            = 0.5
FO_GT_REPAIR        = 500_000
FO_HRSG_REPAIR      = 750_000
FO_BOP_REPAIR       = 200_000
EOH_INTERVAL        = 8_000         # EOH per inspection interval
EOH_INIT            = 24_000.0      # starting EOH (post-HGP)

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def cap_eff(temp_f: float) -> float:
    """Effective plant capacity after ambient temperature derating (MW)."""
    return CAP_ISO * float(np.clip(1.0 - max(0.0, temp_f - 59.0) * DERATE_COEFF,
                                    DERATE_MIN, DERATE_MAX))


def hr_clean(temp_f: float) -> float:
    """Clean plant heat rate: ISO baseline + ambient correction only (BTU/kWh)."""
    return HR_ISO * (1.0 + max(0.0, temp_f - 59.0) * HR_AMBIENT_COEFF)


def hr_degraded(hr_recov_pct: float, fouling_pct: float, temp_f: float) -> float:
    """Degraded heat rate: adds HGP degradation and fouling on top of clean (BTU/kWh)."""
    return (HR_ISO
            * (1.0 + hr_recov_pct / 100.0)
            * (1.0 + fouling_pct  / 100.0)
            * (1.0 + max(0.0, temp_f - 59.0) * HR_AMBIENT_COEFF))


def gas_delivered(gas_price: float) -> float:
    """Plant-gate delivered gas cost ($/MMBtu)."""
    return gas_price * (1.0 + RETAINAGE) + TRANSPORT


def insp_params(n_done: int):
    """Next inspection threshold and type given inspections completed so far."""
    n_next = n_done + 1
    return EOH_INIT + n_next * EOH_INTERVAL, ('MI' if n_next % 3 == 0 else 'CI')


def sample_tbc_threshold(rng: np.random.Generator) -> float:
    """Sample path-specific TBC failure threshold from Weibull distribution."""
    u = rng.uniform(0.01, 0.99)
    return TBC_ETA * (-np.log(1.0 - u)) ** (1.0 / TBC_BETA)


def sample_fo_duration(rng: np.random.Generator, cause: str) -> int:
    """Lognormal forced outage duration (days)."""
    med = {'gt': FO_GT_MED, 'hrsg': FO_HRSG_MED, 'bop': FO_BOP_MED}[cause]
    return max(1, int(np.round(rng.lognormal(np.log(med), FO_SIGMA))))


# ---------------------------------------------------------------------------
# Degraded plant state
# ---------------------------------------------------------------------------

def init_state(rng: np.random.Generator) -> dict:
    """
    Initialise degraded plant state at model start (day 0, post-HGP at 24K EOH).
    All stress counters reset to post-HGP values per Section 4.8.
    """
    return dict(
        eoh         = float(EOH_INIT),
        hr_recov    = 0.0,      # % recoverable HGP degradation (reset at HGP)
        fouling     = 0.0,      # % compressor fouling (washed at HGP)
        dc          = 0.0,      # creep damage fraction
        df          = 0.0,      # fatigue damage fraction
        tbc_time    = 0.0,      # TBC time at temperature (hrs)
        tbc_thresh  = sample_tbc_threshold(rng),
        hrsg_cycles = 0.0,      # HP drum cycle accumulation
        rotor_life  = 0.35,     # estimated after 22 years
        insp_done   = 0,        # inspections completed
        # Outage tracking
        outage_type = None,     # None | 'planned_ci' | 'planned_mi' | 'forced_gt' | ...
        outage_days = 0,        # remaining outage days
        # Dispatch continuity (carries across days)
        op          = False,    # is plant currently operating?
        hrs_off     = 720.0,    # hours since last shutdown (cold after HGP)
        run_hrs     = 0,        # hours operated since last start
        min_run     = 0,        # min run for current start type
        last_stype  = 3,        # last start type (cold)
    )


def update_stress(state: dict, fired_hrs: float, starts: list,
                  avg_temp: float, avg_aqi: float) -> None:
    """
    Update all stress accumulators based on today's actual dispatch.
    Called only on non-outage days.
    """
    if fired_hrs <= 0:
        state['hrs_off'] += 24.0
        return

    st = state
    # 1. EOH (contractual)
    eoh_starts = sum(EOH_START.get(int(c), 0) for c in starts)
    st['eoh'] += fired_hrs * EOH_FIRED + eoh_starts

    # 2. Creep damage
    tf = np.exp(CREEP_TEMP_FACTOR * max(0.0, avg_temp - 59.0))
    st['dc'] += fired_hrs * tf / CREEP_LIFE_BASE

    # 3. Fatigue damage (combustion cycling)
    st['df'] += sum(DMG_IDX.get(int(c), 0.0) for c in starts) / COMB_BUDGET

    # Interaction check
    d_lim = D_INTERACT_MIXED if (st['dc'] > 0.05 and st['df'] > 0.05) else 1.0
    if st['dc'] + st['df'] >= d_lim:
        st['dc'] *= 0.5; st['df'] *= 0.5

    # 4. Compressor fouling (exponential, AQI-scaled)
    aqi_f  = max(0.5, min(3.0, avg_aqi / AQI_NORMAL))
    tau_adj = FOULING_TAU / aqi_f
    st['fouling'] = min(FOULING_A,
                        st['fouling'] + (FOULING_A - st['fouling']) * fired_hrs / tau_adj)

    # 5. HGP recoverable degradation (linear)
    st['hr_recov'] += fired_hrs * (HGP_DEG_RATE / 100.0) / 8_760.0

    # 6. TBC time at temperature
    st['tbc_time'] += fired_hrs

    # 7. HRSG cycling + rotor life (from starts)
    for c in starts:
        st['hrsg_cycles'] += HRSG_DMG.get(int(c), 0.0)
        st['rotor_life']  += ROTOR_WT.get(int(c), 0.0) / ROTOR_LIFE_DESIGN


def p_forced_outage(state: dict, year_frac: float) -> tuple:
    """
    Daily forced outage probability and component breakdown.
    Returns: (p_total, p_gt, p_hrsg, p_bg)
    """
    st  = state
    age = 1.0 + (P_BG_AGE_MAX - 1.0) * year_frac

    p_comb = 0.0
    df_frac = st['df'] / COMB_BUDGET
    if df_frac > HOCKEY_INFLECTION:
        excess  = (df_frac - HOCKEY_INFLECTION) / (1.0 - HOCKEY_INFLECTION)
        p_comb  = min(0.10, excess**2 * 0.10)

    # TBC Weibull hazard
    p_tbc = 0.0
    if st['tbc_time'] >= st['tbc_thresh']:
        p_tbc = 1.0
    elif st['tbc_time'] > 0:
        p_tbc = min(1.0, (TBC_BETA / TBC_ETA) * (st['tbc_time'] / TBC_ETA)**(TBC_BETA - 1))

    p_rotor = min(0.01, P_ROTOR_BASE * st['rotor_life'] / max(0.01, 0.35))
    p_gt    = min(1.0, p_comb + p_tbc + p_rotor)
    p_hrsg  = min(1.0, P_HRSG_BASE * (1.0 + st['hrsg_cycles'] / 2000.0) * age)
    p_bg    = min(1.0, P_BG_BASE * age)
    p_total = 1.0 - (1.0 - p_gt) * (1.0 - p_hrsg) * (1.0 - p_bg)
    return p_total, p_gt, p_hrsg, p_bg


def apply_inspection_reset(state: dict, itype: str, rng: np.random.Generator,
                            cycle_mwh: float, cycle_hr_wt: float,
                            cycle_gas: float, cycle_gas_days: int) -> float:
    """
    Reset engineering state at inspection completion.
    Returns: HR penalty charge (USD) if applicable, else 0.

    """
    from LTSAContract import hr_penalty_cycle
    hr_pen = 0.0
    if cycle_mwh > 0:
        avg_hr  = cycle_hr_wt / cycle_mwh
        avg_gas = cycle_gas / max(1, cycle_gas_days)
        hr_pen  = hr_penalty_cycle(avg_hr, HR_ISO, cycle_mwh, avg_gas)

    if itype == 'CI':
        state['hr_recov']    *= (1.0 - CI_RECOVERY_HGP)
        state['dc']          *= 0.5
        state['df']          *= 0.5
        state['fouling']     *= (1.0 - WASH_RECOVERY)
        state['tbc_thresh']   = sample_tbc_threshold(rng)
    elif itype == 'MI':
        state['hr_recov']    *= (1.0 - HGP_RECOVERY)
        state['dc']           = 0.0
        state['df']           = 0.0
        state['fouling']      = 0.0
        state['tbc_time']     = 0.0
        state['tbc_thresh']   = sample_tbc_threshold(rng)
        state['hrsg_cycles']  = 0.0

    state['insp_done'] += 1
    return hr_pen
