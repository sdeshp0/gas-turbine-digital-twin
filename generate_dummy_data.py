"""
generate_dummy_data.py  —  InfraSure GT Digital Twin
=====================================================
Generates synthetic market and climate inputs for the Athens pilot
(GE 7FA.03 2x1 CC, NYISO Zone F, 100 sims x 1 year).

Output: gt_market_inputs.npz
  temperature_f      float32  (N_SIMS, N_DAYS, 24)   hourly deg F
  air_quality_idx    float32  (N_SIMS, N_DAYS, 24)   hourly AQI 0-200
  power_price_mwh    float32  (N_SIMS, N_DAYS, 24)   hourly $/MWh (NYISO Zone F)
  gas_price_mmbtu    float32  (N_SIMS, N_DAYS)        daily $/MMBtu (TGP Zone 6)

Dispatch is NO LONGER generated here. The dispatch_model.py computes
hourly dispatch dynamically using live engineering model feedback.

Index convention: [sim, day, hour]  -- sim 0..99, day 0..364, hour 0..23
Start date: 2025-01-01
"""

import numpy as np
import os

N_SIMS   = 1000
N_DAYS   = 365
RNG_SEED = 42

rng = np.random.default_rng(RNG_SEED)

hours_in_year = N_DAYS * 24
h_idx = np.arange(hours_in_year)
doy   = h_idx // 24
hod   = h_idx % 24
phase_d = (doy - 16) / 365 * 2 * np.pi - np.pi / 2


def make_temperature():
    t_seas    = 53.0 + 27.0 * np.sin(phase_d)
    t_diurnal = -6.0 * np.cos(2 * np.pi * (hod - 15) / 24)
    base      = t_seas + t_diurnal
    out = np.empty((N_SIMS, hours_in_year), dtype=np.float32)
    for s in range(N_SIMS):
        dn = np.empty(N_DAYS); dn[0] = rng.normal(0, 4)
        eps = rng.normal(0, 4 * np.sqrt(1 - 0.72**2), N_DAYS)
        for d in range(1, N_DAYS): dn[d] = 0.72 * dn[d-1] + eps[d]
        out[s] = np.clip(base + np.repeat(dn, 24) + rng.normal(0, 0.8, hours_in_year),
                         -5, 105).astype(np.float32)
    return out.reshape(N_SIMS, N_DAYS, 24)


def make_aqi(temp_arr):
    aqi_seas = np.clip(20 + 25 * np.sin(phase_d), 0, None)
    out = np.empty((N_SIMS, hours_in_year), dtype=np.float32)
    tf  = temp_arr.reshape(N_SIMS, hours_in_year)
    for s in range(N_SIMS):
        dn = np.empty(N_DAYS); dn[0] = rng.normal(0, 8)
        eps = rng.normal(0, 8 * np.sqrt(1 - 0.65**2), N_DAYS)
        for d in range(1, N_DAYS): dn[d] = 0.65 * dn[d-1] + eps[d]
        noise = np.repeat(dn, 24) + rng.normal(0, 3, hours_in_year)
        out[s] = np.clip(aqi_seas + 0.35 * np.clip(tf[s] - 59, 0, None) + noise,
                         0, 200).astype(np.float32)
    return out.reshape(N_SIMS, N_DAYS, 24)


def make_power_prices():
    p_seas = (35 + 12 * np.sin(phase_d)**2).astype(np.float32)
    shape  = np.where(np.isin(hod, [7,8,9,18,19,20]), 1.35,
             np.where(np.isin(hod, [0,1,2,3,4,5]),   0.68, 1.0))
    out = np.empty((N_SIMS, hours_in_year), dtype=np.float32)
    for s in range(N_SIMS):
        dn = np.empty(N_DAYS); dn[0] = rng.normal(0, 12)
        eps = rng.normal(0, 12 * np.sqrt(1 - 0.55**2), N_DAYS)
        for d in range(1, N_DAYS): dn[d] = 0.55 * dn[d-1] + eps[d]
        pr = (p_seas + np.repeat(dn, 24)) * shape + rng.normal(0, 3, hours_in_year)
        for _ in range(rng.poisson(4)):
            sh  = rng.integers(0, hours_in_year)
            pr[sh:sh + int(rng.integers(1, 7))] += float(rng.lognormal(np.log(200), 0.6))
        out[s] = np.clip(pr, 10, 1000).astype(np.float32)
    return out.reshape(N_SIMS, N_DAYS, 24)


def make_gas_prices():
    doy_1d   = np.arange(N_DAYS)
    gas_seas = (2.8 + 1.5 * np.cos(2 * np.pi * doy_1d / 365)**2).astype(np.float32)
    kappa, sigma = 0.08, 0.80
    base = np.zeros(N_DAYS)
    for d in range(1, N_DAYS): base[d] = base[d-1] * (1 - kappa) + rng.normal(0, sigma)
    winter = np.where((doy_1d <= 58) | (doy_1d >= 334))[0]
    out = np.empty((N_SIMS, N_DAYS), dtype=np.float32)
    for s in range(N_SIMS):
        idio = np.zeros(N_DAYS)
        for d in range(1, N_DAYS): idio[d] = idio[d-1]*(1-kappa) + rng.normal(0, sigma*0.6)
        pr = gas_seas + 0.7*base + 0.3*idio
        for sd in rng.choice(winter, size=min(rng.poisson(2), len(winter)), replace=False):
            pr[sd:sd + int(rng.integers(1, 5))] += float(rng.lognormal(np.log(8), 0.7))
        out[s] = np.clip(pr, 2.0, 35.0).astype(np.float32)
    return out


if __name__ == '__main__':
    import time
    t0 = time.time()
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'gt_market_inputs.npz')
    print(f'Generating {N_SIMS} sims x {N_DAYS} days of market + climate inputs ...')
    temp_arr  = make_temperature()
    aqi_arr   = make_aqi(temp_arr)
    power_arr = make_power_prices()
    gas_arr   = make_gas_prices()
    np.savez_compressed(out_path,
        temperature_f   = temp_arr,
        air_quality_idx = aqi_arr,
        power_price_mwh = power_arr,
        gas_price_mmbtu = gas_arr)
    print(f'Saved {out_path}  ({os.path.getsize(out_path)/1e6:.1f} MB)  in {time.time()-t0:.1f}s')
    print(f'  temp:  min={temp_arr.min():.0f}F  mean={temp_arr.mean():.1f}F  max={temp_arr.max():.0f}F')
    print(f'  power: p50=${np.percentile(power_arr,50):.1f}/MWh  max=${power_arr.max():.0f}/MWh')
    print(f'  gas:   p50=${np.percentile(gas_arr,50):.2f}/MMBtu  max=${gas_arr.max():.1f}/MMBtu')
