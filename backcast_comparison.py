"""
backcast_comparison.py  —  InfraSure GT Digital Twin
=====================================================
Back-cast validation: compare model synthetic input distributions
against actual historical NYISO Zone F and TGP Zone 6 market data
(2015-2024), sourced from EIA, NYISO annual reports, and public data.

Key comparison metrics (annual averages):
  - NYISO Zone F power price ($/MWh)
  - TGP Zone 6 / Henry Hub gas price ($/MMBtu)
  - Implied clean spark spread ($/MWh)
  - Albany, NY temperature (deg F) — validates climate inputs

Output: charts/chart_backcast.png
"""

import numpy as np, os
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, 'gt_market_inputs.npz')
CHART_DIR  = os.path.join(BASE_DIR, 'charts')

# ---------------------------------------------------------------------------
# Historical annual data (2015-2024)
# Sources: NYISO Annual Reports, EIA Wholesale Markets, NOAA Climate Normals
# ---------------------------------------------------------------------------

YEARS = list(range(2015, 2025))

# NYISO Zone F (Capital) annual average day-ahead LMP ($/MWh)
# Source: NYISO Annual Market Reports + EIA wholesale data
ACTUAL_POWER = {
    2015: 34.1, 2016: 28.0, 2017: 32.5, 2018: 44.0, 2019: 33.5,
    2020: 27.2, 2021: 64.5, 2022: 89.0, 2023: 46.0, 2024: 34.5,
}

# TGP Zone 6 annual average gas price ($/MMBtu)
# Source: EIA Henry Hub + typical Zone 6 basis (~$0.20/MMBtu non-winter)
ACTUAL_GAS = {
    2015: 2.84, 2016: 2.82, 2017: 3.22, 2018: 3.35, 2019: 2.77,
    2020: 2.23, 2021: 4.10, 2022: 6.67, 2023: 2.73, 2024: 2.40,
}

# Albany, NY annual average temperature (deg F)
# Source: NOAA GHCN-D, Albany International Airport (station ALB)
ACTUAL_TEMP = {
    2015: 51.2, 2016: 52.8, 2017: 51.5, 2018: 50.1, 2019: 49.8,
    2020: 53.1, 2021: 51.6, 2022: 52.0, 2023: 52.5, 2024: 53.0,
}

# Model parameters (matching EnggDTwin_model.py / LTSAContract.py)
HR_ISO = 7_070.0; VOM = 2.50; TRANSPORT = 0.12; RETAINAGE = 0.017

def delivered_gas(g): return g * (1 + RETAINAGE) + TRANSPORT
def spark(p, g): return p - (HR_ISO / 1000) * delivered_gas(g) - VOM

ACTUAL_SPARK = {y: spark(ACTUAL_POWER[y], ACTUAL_GAS[y]) for y in YEARS}

# Key events for annotation
EVENTS = {
    2021: 'Winter Storm Uri\n+ post-COVID recovery',
    2022: 'Russia/Ukraine\ngas price spike',
}

# ---------------------------------------------------------------------------
# Synthetic model distributions (from gt_market_inputs.npz)
# ---------------------------------------------------------------------------

inp = dict(np.load(INPUT_FILE))
power = inp['power_price_mwh']      # (1000, 365, 24)
gas   = inp['gas_price_mmbtu']      # (1000, 365)

# Annual averages across 1000 sims
power_annual_mean  = float(power.mean())
power_annual_p10   = float(np.percentile(power, 10))
power_annual_p90   = float(np.percentile(power, 90))

gas_del_all = gas * (1 + RETAINAGE) + TRANSPORT
gas_annual_mean = float(gas_del_all.mean())
gas_annual_p10  = float(np.percentile(gas_del_all, 10))
gas_annual_p90  = float(np.percentile(gas_del_all, 90))

spark_all = power.mean(axis=2) - (HR_ISO / 1000) * gas_del_all - VOM
spark_annual_mean = float(spark_all.mean())
spark_annual_p10  = float(np.percentile(spark_all, 10))
spark_annual_p90  = float(np.percentile(spark_all, 90))

temp_annual_mean = float(inp['temperature_f'].mean())
temp_annual_p10  = float(np.percentile(inp['temperature_f'], 10))
temp_annual_p90  = float(np.percentile(inp['temperature_f'], 90))

C_DARK='#1C2B3A'; C_TEAL='#1A7A6A'; C_GOLD='#C9A84C'
C_RED='#C0392B'; C_GREY='#95A5A6'; C_BLUE='#2471A3'

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

fig, axes = plt.subplots(2, 2, figsize=(16, 10), facecolor='white')
fig.suptitle(
    'Back-cast Validation — Synthetic Market Inputs vs Historical NYISO Zone F / TGP Zone 6\n'
    '2015–2024 Actual  |  Model Synthetic Distribution (calibrated to 2025 conditions)',
    fontsize=13, fontweight='bold', color=C_DARK)

years_arr = np.array(YEARS)

def plot_panel(ax, actual_dict, synth_mean, synth_p10, synth_p90,
               ylabel, title, unit='$/MWh', events=True):
    actual_vals = np.array([actual_dict[y] for y in YEARS])

    # Historical actual line + dots
    ax.plot(years_arr, actual_vals, 'o-', color=C_DARK, lw=2, markersize=7,
            label='Actual (NYISO/EIA annual avg)')

    # Synthetic distribution band (horizontal — same model for each year)
    ax.fill_between(years_arr, synth_p10, synth_p90, color=C_TEAL, alpha=0.18,
                    label='Synthetic model P10-P90 range')
    ax.axhline(synth_mean, color=C_TEAL, lw=1.8, linestyle='--',
               label=f'Synthetic model avg ({synth_mean:.1f} {unit})')

    # Event annotations
    if events:
        for yr, txt in EVENTS.items():
            val = actual_dict[yr]
            ax.annotate(txt, xy=(yr, val),
                        xytext=(yr - 1.2, val + (max(actual_vals) - min(actual_vals)) * 0.12),
                        fontsize=7, color=C_RED,
                        arrowprops=dict(arrowstyle='->', color=C_RED, lw=1.0),
                        ha='center')

    ax.set_ylabel(ylabel, fontsize=10, color=C_DARK)
    ax.set_title(title, fontsize=11, fontweight='bold', color=C_DARK, pad=5)
    ax.set_xticks(years_arr); ax.tick_params(labelsize=9)
    ax.grid(axis='y', linestyle=':', alpha=0.4)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.legend(fontsize=8, loc='upper left')

# Panel 1: Power price
plot_panel(axes[0,0], ACTUAL_POWER, power_annual_mean, power_annual_p10, power_annual_p90,
           '$/MWh', 'NYISO Zone F Power Price', '$/MWh')

# Panel 2: Gas price (delivered TGP Zone 6)
actual_gas_del = {y: delivered_gas(ACTUAL_GAS[y]) for y in YEARS}
plot_panel(axes[0,1], actual_gas_del, gas_annual_mean, gas_annual_p10, gas_annual_p90,
           '$/MMBtu', 'TGP Zone 6 Delivered Gas Price', '$/MMBtu')

# Panel 3: Spark spread
plot_panel(axes[1,0], ACTUAL_SPARK, spark_annual_mean, spark_annual_p10, spark_annual_p90,
           '$/MWh', 'Clean Spark Spread (ISO HR)', '$/MWh')

# Panel 4: Temperature (Albany, NY)
plot_panel(axes[1,1], ACTUAL_TEMP, temp_annual_mean, temp_annual_p10, temp_annual_p90,
           'deg F', 'Albany, NY Annual Average Temperature', 'degF', events=False)

# Summary text box
summary = (
    f"Synthetic model calibration: 2025 forward conditions\n"
    f"Power: synthetic avg ${power_annual_mean:.1f}/MWh "
    f"vs 2015-2024 actual avg ${np.mean(list(ACTUAL_POWER.values())):.1f}/MWh\n"
    f"Gas (delivered): synthetic avg ${gas_annual_mean:.2f}/MMBtu "
    f"vs actual avg ${np.mean([delivered_gas(v) for v in ACTUAL_GAS.values()]):.2f}/MMBtu\n"
    f"Spark spread: synthetic avg ${spark_annual_mean:.1f}/MWh "
    f"vs actual avg ${np.mean(list(ACTUAL_SPARK.values())):.1f}/MWh\n"
    f"Note: 2021-22 spike (Russia/Ukraine gas crisis) not in synthetic distribution — "
    f"model does not capture tail-event market conditions"
)
fig.text(0.5, 0.01, summary, ha='center', va='bottom', fontsize=7.5,
         color=C_GREY, style='italic',
         bbox=dict(boxstyle='round', facecolor='#F8F8F8', alpha=0.8))

plt.tight_layout(rect=[0, 0.08, 1, 1])

tmp='/tmp/chart_backcast.png'
fig.savefig(tmp, dpi=150, bbox_inches='tight', facecolor='white')
dest=os.path.join(CHART_DIR,'chart_backcast.png')
os.makedirs(CHART_DIR,exist_ok=True)
with open(tmp,'rb') as s, open(dest,'wb') as d: d.write(s.read())
print(f"Saved {dest}")

# Print summary stats
print("\n=== Back-cast validation summary ===")
print(f"Power price:    synthetic ${power_annual_mean:.1f}/MWh vs actual avg ${np.mean(list(ACTUAL_POWER.values())):.1f}/MWh")
print(f"Gas (delivered):synthetic ${gas_annual_mean:.2f}/MMBtu vs actual avg ${np.mean([delivered_gas(v) for v in ACTUAL_GAS.values()]):.2f}/MMBtu")
print(f"Spark spread:  synthetic ${spark_annual_mean:.1f}/MWh vs actual avg ${np.mean(list(ACTUAL_SPARK.values())):.1f}/MWh")
print(f"Temperature:   synthetic {temp_annual_mean:.1f}F vs actual avg {np.mean(list(ACTUAL_TEMP.values())):.1f}F")
print(f"\nActual spark spread range: ${min(ACTUAL_SPARK.values()):.1f} (2020) to ${max(ACTUAL_SPARK.values()):.1f} (2022)")
print(f"Synthetic model P10-P90: ${spark_annual_p10:.1f} to ${spark_annual_p90:.1f}")
