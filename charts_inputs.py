"""
charts_inputs.py  —  InfraSure GT Digital Twin
========================================================
Shows how the 100 market simulations are assembled into
10 long paths of 10 years each.

Path j chains: sim j (yr1), sim j+10 (yr2), ..., sim j+90 (yr10).

Five panels (daily average across 24hrs, then plotted over 3650 days):
  Power price | Gas price | Spark spread | Temperature | Air quality index

Average line + P10/P90 shading across 10 paths.
"""
import numpy as np, matplotlib, os
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import date, timedelta

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, 'gt_market_inputs.npz')
CHART_DIR  = os.path.join(BASE_DIR, 'charts')

HR_ISO=7070.0; VOM_BASE=2.50; TRANSPORT=0.12; RETAINAGE=0.017

N_LONG=100; N_YEARS=10; N_DAYS=365; TOTAL=N_YEARS*N_DAYS
SIM_START = date(2025,1,1)

C_GOLD='#C9A84C'; C_DARK='#1C2B3A'; C_TEAL='#1A7A6A'
C_RED='#D75A4A'; C_PURPLE='#7D3C98'

def make_days():
    return [SIM_START+timedelta(days=i) for i in range(TOTAL)]

def build_paths(arr_hourly, arr_daily=None):
    """
    Build (N_LONG, TOTAL) daily arrays from 1-year simulation inputs.
    arr_hourly: (100, 365, 24) — averaged over 24h axis to give (100, 365)
    arr_daily:  (100, 365)     — used as-is
    Returns (N_LONG, TOTAL) daily array.
    """
    if arr_hourly is not None:
        src = arr_hourly.mean(axis=2)   # (100, 365)
    else:
        src = arr_daily                  # (100, 365)

    out = np.empty((N_LONG, TOTAL), dtype=np.float32)
    for j in range(N_LONG):
        for y in range(N_YEARS):
            sim = j + y * 10            # which sim to use for this year
            gd_start = y * N_DAYS
            out[j, gd_start:gd_start+N_DAYS] = src[sim]
    return out

def run():
    print(f"Loading {INPUT_FILE} ...")
    inp = np.load(INPUT_FILE)
    temp   = inp['temperature_f']    # (100,365,24)
    power  = inp['power_price_mwh']  # (100,365,24)
    gas    = inp['gas_price_mmbtu']  # (100,365)
    aqi    = inp['air_quality_idx']  # (100,365,24)

    temp_d  = build_paths(temp)
    power_d = build_paths(power)
    gas_d   = build_paths(None, gas)
    aqi_d   = build_paths(aqi)

    gas_del = gas_d * (1 + RETAINAGE) + TRANSPORT
    spark_d = power_d - (HR_ISO/1000) * gas_del - VOM_BASE

    days = make_days()

    def band(ax, data, color, alpha=0.18):
        lo=np.percentile(data,10,axis=0); hi=np.percentile(data,90,axis=0)
        mn=data.mean(axis=0)
        ax.fill_between(days,lo,hi,color=color,alpha=alpha,linewidth=0)
        ax.plot(days,mn,color=color,linewidth=1.5)

    def fmt(ax,unit,title,zero=False):
        ax.set_ylabel(unit,fontsize=10,color=C_DARK)
        ax.set_title(title,fontsize=11,fontweight='bold',color=C_DARK,pad=4)
        ax.set_xlim(days[0],days[-1])
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.tick_params(labelsize=9)
        ax.grid(axis='y',linestyle=':',alpha=0.4)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        if zero: ax.axhline(0,color='#999',lw=0.8,ls='--',alpha=0.7)
        ax.text(0.99,0.93,'Shaded: P10-P90',transform=ax.transAxes,
                fontsize=8,color='#666',ha='right',va='top')

    fig,axes = plt.subplots(5,1,figsize=(14,20),facecolor='white')
    fig.suptitle(
        'Market & Climate Inputs — 10 Simulation Paths × 10 Years\n'
        'NYISO Zone F  |  Average across paths + P10–P90 shading  |  2025–2034',
        fontsize=14,fontweight='bold',color=C_DARK,y=0.98)

    panels = [
        (power_d, '$/MWh',  'Power price ($/MWh)',          C_GOLD,   False),
        (gas_d,   '$/MMBtu','Gas price ($/MMBtu)',            C_RED,    False),
        (spark_d, '$/MWh',  'Clean spark spread ($/MWh)',    C_TEAL,   True),
        (temp_d,  'deg F',  'Temperature (deg F)',            C_DARK,   False),
        (aqi_d,   'AQI',    'Air quality index (AQI)',        C_PURPLE, False),
    ]

    for ax,(data,unit,title,color,zero) in zip(axes,panels):
        band(ax,data,color)
        fmt(ax,unit,title,zero)

    plt.tight_layout(rect=[0,0,1,0.97])
    os.makedirs(os.path.join(CHART_DIR,'tmp'),exist_ok=True)
    tmp=os.path.join(CHART_DIR,'tmp','chart_inputs.png')
    plt.savefig(tmp,dpi=150,bbox_inches='tight',facecolor='white')
    plt.close()
    dest=os.path.join(CHART_DIR,'chart_inputs_new.png')
    os.makedirs(CHART_DIR,exist_ok=True)
    with open(tmp,'rb') as s, open(dest,'wb') as d: d.write(s.read())
    print(f"Saved {dest}")

if __name__=='__main__': run()
