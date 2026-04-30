"""
sensitivity_analysis.py  —  InfraSure GT Digital Twin
=====================================================
Perturbs each Appendix B methodology assumption by +/-20% (Amber/Green)
or +/-50% (Red) and measures impact on three key metrics:
  1. Average annual spark spread ($M/yr)
  2. Average capacity factor (%)
  3. Average annual LTSA cost ($M/yr)

Runs 10 simulation paths, Mode A only for speed (~20s total).
Outputs a tornado chart: chart_sensitivity.png
"""

import numpy as np, time, os, sys
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import EnggDTwin_model as EM
import LTSAContract   as LC
from LTSAContract import (LTSAParams, daily_fixed_fee, daily_eoh_reserve,
                          inspection_cost, overage_charge,
                          availability_penalty_annual, classify_forced_outage_cost)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, 'gt_market_inputs.npz')
CHART_DIR  = os.path.join(BASE_DIR, 'charts')

N_PATHS = 10; N_YEARS = 10; N_DAYS = 365; TOTAL = N_YEARS * N_DAYS

C_TEAL='#1A7A6A'; C_RED='#C0392B'; C_GREY='#95A5A6'; C_DARK='#1C2B3A'

# ---------------------------------------------------------------------------
# Assumptions to perturb — (label, module_attr, module, baseline, pct, color)
# ---------------------------------------------------------------------------
PARAMS = [
    # Engineering — Green
    ('HGP degradation rate',         'HGP_DEG_RATE',   'EM', EM.HGP_DEG_RATE,   0.20, 'Green'),
    ('Ambient derating coeff',        'DERATE_COEFF',   'EM', EM.DERATE_COEFF,   0.20, 'Green'),
    ('HR ambient correction',         'HR_AMBIENT_COEFF','EM',EM.HR_AMBIENT_COEFF,0.20,'Green'),
    # Engineering — Amber
    ('Compressor fouling asymptote',  'FOULING_A',      'EM', EM.FOULING_A,      0.20, 'Amber'),
    ('Fouling time constant (tau)',   'FOULING_TAU',    'EM', EM.FOULING_TAU,    0.20, 'Amber'),
    ('Offline wash recovery',         'WASH_RECOVERY',  'EM', EM.WASH_RECOVERY,  0.20, 'Amber'),
    ('P_HRSG baseline (/day)',        'P_HRSG_BASE',    'EM', EM.P_HRSG_BASE,    0.20, 'Amber'),
    ('P_background baseline (/day)',  'P_BG_BASE',      'EM', EM.P_BG_BASE,      0.20, 'Amber'),
    ('TBC characteristic life (hrs)', 'TBC_ETA',        'EM', EM.TBC_ETA,        0.20, 'Amber'),
    ('TBC shape parameter (beta)',    'TBC_BETA',       'EM', EM.TBC_BETA,        0.20, 'Amber'),
    # Engineering — Red
    ('Combustion hockey stick inflect.','HOCKEY_INFLECTION','EM',EM.HOCKEY_INFLECTION,0.50,'Red'),
    ('P_rotor baseline (/day)',       'P_ROTOR_BASE',   'EM', EM.P_ROTOR_BASE,   0.50, 'Red'),
    ('P_bg age multiplier (yr 10)',   'P_BG_AGE_MAX',   'EM', EM.P_BG_AGE_MAX,   0.50, 'Red'),
    # LTSA — [ASSUME]
    ('CI inspection cost',            'CI_COST_TOTAL',  'LC', LTSAParams.CI_COST_TOTAL,   0.20, 'LTSA'),
    ('MI inspection cost',            'MI_COST_TOTAL',  'LC', LTSAParams.MI_COST_TOTAL,   0.20, 'LTSA'),
    ('Monthly LTSA fixed fee',        'FIXED_MONTHLY',  'LC', LTSAParams.FIXED_MONTHLY,   0.20, 'LTSA'),
    ('Hot start overage charge',      'OVERAGE_HOT',    'LC', LTSAParams.OVERAGE_HOT,     0.20, 'LTSA'),
]

# ---------------------------------------------------------------------------
# Lightweight single-mode run (Mode A, no file I/O)
# ---------------------------------------------------------------------------
def run_metrics(inp, maint_sched, seed=42, em_overrides=None, lc_overrides=None):
    if em_overrides:
        for k,v in em_overrides.items(): setattr(EM, k, v)
    if lc_overrides:
        for k,v in lc_overrides.items(): setattr(LTSAParams, k, v)

    rng = np.random.default_rng(seed)
    maint = list(maint_sched)

    temp_arr  = inp['temperature_f']
    aqi_arr   = inp['air_quality_idx']
    power_arr = inp['power_price_mwh']
    gas_arr   = inp['gas_price_mmbtu']

    total_spark=0.0; total_hrs=0.0; total_ltsa=0.0

    for j in range(N_PATHS):
        st = EM.init_state(rng); pending=list(maint)
        cyc_mwh=cyc_hw=cyc_g=0.0; cyc_gd=0
        op=False; hrs_off=720.0; run_hrs=0; min_run=0; last_st=3
        ytd_h=ytd_w=ytd_c=ytd_t=0; prev_ov=0.0; avail_h=0.0

        for y in range(N_YEARS):
            sim = j + y * 10
            y0  = y * N_DAYS
            for d in range(N_DAYS):
                gd=y0+d; doy=d+1
                th=temp_arr[sim,d,:]; ph=power_arr[sim,d,:]
                gas_d=float(gas_arr[sim,d])
                avg_t=float(th.mean()); avg_aqi=float(aqi_arr[sim,d,:].mean())
                gas_del=gas_d*(1+EM.RETAINAGE)+EM.TRANSPORT
                fix_fee=daily_fixed_fee(d,year=y)
                hr_dg=EM.hr_degraded(st['hr_recov'],st['fouling'],avg_t)
                cap_d=EM.cap_eff(avg_t)
                fuel_c=hr_dg/1000*gas_del

                # continuing outage
                if st['outage_days']>0:
                    st['outage_days']-=1
                    ot=st['outage_type']
                    if st['outage_days']==0:
                        if ot and 'planned' in ot:
                            itype=ot.replace('planned_','').upper()
                            EM.apply_inspection_reset(st,itype,rng,cyc_mwh,cyc_hw,cyc_g,cyc_gd)
                            cyc_mwh=cyc_hw=cyc_g=0.0; cyc_gd=0
                        st['op']=False; st['hrs_off']=24.0; st['run_hrs']=0; st['outage_type']=None
                    if ot and 'planned' not in str(ot or ''):
                        avail_h+=24
                    total_ltsa+=fix_fee; continue

                # planned outage trigger
                if pending and st['eoh']>=pending[0][2]+1500.0:
                    gd2,it,thr=pending.pop(0)
                    cost=inspection_cost(it)
                    total_ltsa+=cost['oem_covered']+cost['owner_uncovered']+fix_fee
                    st['outage_type']=f'planned_{it.lower()}'; st['outage_days']=cost['outage_days']
                    continue
                if pending and gd>=pending[0][0]:
                    gd2,it,thr=pending.pop(0)
                    cost=inspection_cost(it)
                    total_ltsa+=cost['oem_covered']+cost['owner_uncovered']+fix_fee
                    st['outage_type']=f'planned_{it.lower()}'; st['outage_days']=cost['outage_days']
                    continue

                # forced outage
                avail_h+=24
                yr_frac=(y*N_DAYS+d)/TOTAL
                p_tot,p_gt,p_hr,p_bg=EM.p_forced_outage(st,yr_frac)
                ovmult=1+(2.5-1)*min(1,
                    max(0,st['eoh']-(pending[0][2] if pending else 1e9))/1500.0)
                if rng.random()<min(1.0,p_tot*ovmult):
                    wts=np.array([p_gt,p_hr,p_bg]); wts/=wts.sum()
                    cause=['gt','hrsg','bop'][rng.choice(3,p=wts)]
                    rep={'gt':EM.FO_GT_REPAIR,'hrsg':EM.FO_HRSG_REPAIR,'bop':EM.FO_BOP_REPAIR}[cause]
                    cs=classify_forced_outage_cost('gt_covered' if cause=='gt' else cause,rep)
                    total_ltsa+=cs['oem_covered']+cs['owner_uncovered']+fix_fee
                    st['outage_type']=f'forced_{cause}'
                    st['outage_days']=EM.sample_fo_duration(rng,cause)
                    st['op']=False; continue

                # dispatch
                starts=[]; fired=0; mwh=0.0; rev=0.0
                cur_op=op; cur_off=hrs_off; cur_run=run_hrs; cur_mr=min_run; cur_ls=last_st
                for h in range(24):
                    sp=ph[h]-fuel_c-EM.VOM_BASE
                    if not cur_op:
                        stype=1 if cur_off<8 else (2 if cur_off<72 else 3)
                        hurdle=EM.START_COST[stype]/(cap_d*EM.MIN_RUN[stype])
                        commit=cur_off>=EM.MIN_DOWN[stype] and sp>hurdle
                    else:
                        stype=cur_ls; commit=(cur_run<cur_mr) or (sp>0)
                    if commit:
                        if not cur_op:
                            starts.append(stype); cur_op=True; cur_run=1
                            cur_mr=EM.MIN_RUN[stype]; cur_ls=stype
                        else: cur_run+=1
                        mwh+=cap_d; rev+=ph[h]*cap_d; fired+=1; cur_off=0
                    else:
                        if cur_op: cur_op=False; cur_run=0
                        cur_off+=1
                op=cur_op; hrs_off=float(cur_off); run_hrs=cur_run; min_run=cur_mr; last_st=cur_ls

                fuel_mmbtu=mwh*hr_dg/1000; gas_cost=fuel_mmbtu*gas_del; vom=mwh*EM.VOM_BASE
                spark=rev-gas_cost-vom
                total_spark+=spark; total_hrs+=fired

                EM.update_stress(st,fired,starts,avg_t,avg_aqi)
                d_eoh=fired*EM.EOH_FIRED+sum(EM.EOH_START.get(int(c),0) for c in starts)
                eoh_res=daily_eoh_reserve(d_eoh,year=y)
                for c in starts:
                    if c==1: ytd_h+=1
                    elif c==2: ytd_w+=1
                    elif c==3: ytd_c+=1
                cum_ov=overage_charge(ytd_h,ytd_w,ytd_c,ytd_t,doy)
                total_ltsa+=fix_fee+eoh_res+max(0,cum_ov-prev_ov); prev_ov=cum_ov
                cyc_mwh+=mwh; cyc_hw+=mwh*hr_dg; cyc_g+=gas_d; cyc_gd+=1

            ann_av=avail_h/(N_DAYS*24)
            total_ltsa+=availability_penalty_annual(ann_av,year=y)

    # Reset overrides
    if em_overrides:
        for k,v in em_overrides.items(): setattr(EM,k,BASELINES_EM.get(k,v))
    if lc_overrides:
        for k,v in lc_overrides.items(): setattr(LTSAParams,k,BASELINES_LC.get(k,v))

    return (total_spark/N_PATHS/N_YEARS/1e6,
            total_hrs/N_PATHS/(TOTAL*24)*100,
            total_ltsa/N_PATHS/N_YEARS/1e6)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__=='__main__':
    t0=time.time()
    inp=dict(np.load(INPUT_FILE))
    print(f"Loaded inputs. Running sensitivity on {len(PARAMS)} assumptions...")

    # Store baselines for reset
    BASELINES_EM={k: getattr(EM,k) for _,k,m,_,_,_ in PARAMS if m=='EM'}
    BASELINES_LC={k: getattr(LTSAParams,k) for _,k,m,_,_,_ in PARAMS if m=='LC'}

    # Build maintenance schedule once
    from dispatch_model import build_maint_schedule, estimate_eoh_rate
    rate=estimate_eoh_rate(inp); sched=build_maint_schedule(rate)
    print(f"  Maintenance schedule: {len(sched)} events")
    # Baseline run
    base=run_metrics(inp,sched); print(f"  Baseline: spark=${base[0]:.2f}M/yr CF={base[1]:.1f}% LTSA=${base[2]:.1f}M/yr")

    results=[]
    for label,attr,mod,bval,pct,color in PARAMS:
        row={'label':label,'color':color,'pct':pct,'deltas':[[],[]]}
        for sign,si in [(+1,0),(-1,1)]:
            new_val=bval*(1+sign*pct)
            if mod=='EM':
                m=run_metrics(inp,sched,em_overrides={attr:new_val})
            else:
                m=run_metrics(inp,sched,lc_overrides={attr:new_val})
            row['deltas'][si]=[m[0]-base[0], m[1]-base[1], m[2]-base[2]]
        results.append(row)
        print(f"  {label[:40]:<40} +/-{pct*100:.0f}%  spark: {row['deltas'][0][0]:+.2f}/{row['deltas'][1][0]:+.2f}M/yr")

    print(f"Sensitivity done in {time.time()-t0:.1f}s")

    # Sort by abs impact on spark spread
    results.sort(key=lambda r: max(abs(r['deltas'][0][0]),abs(r['deltas'][1][0])), reverse=True)

    # Plot tornado charts for all 3 metrics
    metrics=['Avg Annual Spark Spread ($M/yr)','Avg Capacity Factor (%)','Avg Annual LTSA Cost ($M/yr)']
    units=['$M/yr','%pts','$M/yr']
    fig,axes=plt.subplots(1,3,figsize=(18,8),facecolor='white')
    fig.suptitle('Sensitivity Analysis — Impact of +/-20% Assumption Perturbation\n'
                 'Athens Pilot GE 7FA  |  Mode A  |  10-Year horizon',
                 fontsize=13,fontweight='bold',color=C_DARK)

    CMAP={'Green':'#1E8449','Amber':'#BA7517','Red':'#A32D2D','LTSA':'#2471A3'}

    for ax,mi,metric,unit in zip(axes,range(3),metrics,units):
        labels=[r['label'] for r in results]
        y=np.arange(len(labels))
        for ri,row in enumerate(results):
            d_up=row['deltas'][0][mi]; d_dn=row['deltas'][1][mi]
            c=CMAP.get(row['color'],C_GREY)
            d_up=row["deltas"][0][mi]  # impact of +pct perturbation
            d_dn=row["deltas"][1][mi]  # impact of -pct perturbation
            # Each bar starts at 0 and extends left/right
            ax.barh(ri+0.2, d_up, height=0.35,
                    color=C_TEAL if d_up>=0 else C_RED, alpha=0.88)
            ax.barh(ri-0.2, d_dn, height=0.35,
                    color=C_TEAL if d_dn>=0 else C_RED, alpha=0.50)
        ax.axvline(0,color=C_DARK,lw=0.8,alpha=0.6)
        ax.set_yticks(y-0.2); ax.set_yticklabels(labels,fontsize=8)
        ax.set_xlabel(unit,fontsize=9); ax.set_title(metric,fontsize=10,fontweight='bold',color=C_DARK)
        ax.grid(axis='x',linestyle=':',alpha=0.4)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        if mi==0:
            from matplotlib.patches import Patch
            ax.legend(handles=[Patch(color=C_TEAL,alpha=0.85,label='+20% perturbation (solid)'),
                                Patch(color=C_TEAL,alpha=0.55,label='-20% perturbation (light)'),
                                Patch(color=C_RED,alpha=0.85,label='Adverse impact')],
                      fontsize=7,loc='lower right')

    plt.tight_layout()
    tmp='/tmp/chart_sensitivity.png'
    fig.savefig(tmp,dpi=150,bbox_inches='tight',facecolor='white')
    dest=os.path.join(CHART_DIR,'chart_sensitivity.png')
    os.makedirs(CHART_DIR,exist_ok=True)
    with open(tmp,'rb') as s, open(dest,'wb') as d: d.write(s.read())
    print(f"Saved {dest}")
