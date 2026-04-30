"""charts_outputs.py  —  InfraSure GT Digital Twin  (v7 — quarterly spark, Mode B blue)"""
import numpy as np, matplotlib, os
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import date, timedelta

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
NPZ_A     = os.path.join(BASE_DIR,'outputs','gt_outputs_10yr.npz')
NPZ_MODES = os.path.join(BASE_DIR,'outputs','gt_mode_comparison.npz')
CHART_DIR = os.path.join(BASE_DIR,'charts')

N_PATHS=50; N_YEARS=10; N_DAYS=365; TOTAL=N_YEARS*N_DAYS
C_DARK='#1C2B3A'; C_TEAL='#1A7A6A'; C_GOLD='#C9A84C'
C_RED='#C0392B'; C_ORANGE='#E67E22'; C_PURPLE='#7D3C98'
C_BLUE='#2471A3'; C_GREY='#95A5A6'; C_GREEN='#1E8449'; C_C='#7D3C98'

_start=date(2025,1,1)
_MIDX=np.array([(((_start+timedelta(days=d)).year-2025)*12
                 +(_start+timedelta(days=d)).month-1)
                for d in range(TOTAL)],dtype=np.int32)
N_MONTHS=120

def to_monthly(arr):
    out=np.zeros((N_PATHS,N_MONTHS))
    for m in range(N_MONTHS): out[:,m]=arr[:,_MIDX==m].sum(axis=1)
    return out

def to_annual(arr): return arr.reshape(N_PATHS,N_YEARS,N_DAYS).sum(axis=2)

def to_quarterly(arr):
    q_starts=[]; q_ends=[]
    for y in range(N_YEARS):
        for m in [1,4,7,10]:
            qs=date(2025+y,m,1)
            m2=m+3 if m<10 else 1; y2=2025+y if m<10 else 2025+y+1
            q_starts.append(qs); q_ends.append(date(y2,m2,1))
    out=np.zeros((N_PATHS,40))
    for qi,(qs,qe) in enumerate(zip(q_starts,q_ends)):
        g0=max(0,min((qs-_start).days,TOTAL))
        g1=max(0,min((qe-_start).days,TOTAL))
        if g1>g0: out[:,qi]=arr[:,g0:g1].sum(axis=1)
    return out, q_starts

def month_dates(): return [_start+timedelta(days=int(np.where(_MIDX==m)[0][0])) for m in range(N_MONTHS)]
def days_pm(): return np.array([(_MIDX==m).sum() for m in range(N_MONTHS)],dtype=float)
def avg(a,axis=0): return np.mean(a,axis=axis)
def p(a,q,axis=0): return np.percentile(a,q,axis=axis)

def save_fig(fig,fname):
    tmp=f'/tmp/{fname}'
    fig.savefig(tmp,dpi=150,bbox_inches='tight',facecolor='white')
    with open(tmp,'rb') as s, open(os.path.join(CHART_DIR,fname),'wb') as d: d.write(s.read())
    print(f'Saved {fname}')

def fig1_spark(out_A, modes):
    SC_q,qdates=to_quarterly(out_A['spark_actual']/1e6)
    LP_q,_     =to_quarterly(out_A['loss_planned']/1e6)
    LD_q,_     =to_quarterly(out_A['loss_degradation']/1e6)
    LF_q,_     =to_quarterly(out_A['loss_forced']/1e6)
    CL_q=SC_q+LP_q+LD_q+LF_q
    sp_B_q,_=to_quarterly(modes['spark'][1]/1e6)
    sp_C_q,_=to_quarterly(modes['spark'][2]/1e6)
    asc=avg(SC_q); ald=avg(LD_q); alf=avg(LF_q); acl=avg(CL_q)
    l1=asc+ald; l2=asc+ald+alf; l3=acl
    fig,ax=plt.subplots(figsize=(14,6.5),facecolor='white')
    fig.suptitle('Quarterly Spark Spread Revenue Attribution (10-Year)\n'
                 'Average across 50 paths  |  Calendar-based maintenance  |  2025-2034',
                 fontsize=13,fontweight='bold',color=C_DARK)
    ax.fill_between(qdates,0,asc,color=C_TEAL,alpha=0.45,label='Dispatched spark spread (Mode A)')
    ax.plot(qdates,asc,color=C_TEAL,lw=1.2,alpha=0.6)
    ax.plot(qdates,l1,color=C_ORANGE,lw=2.0,label='+ Degradation Loss (HR+dispatch)')
    ax.plot(qdates,l2,color=C_RED,   lw=2.0,label='+ Forced Outage Loss')
    ax.plot(qdates,l3,color=C_GOLD,  lw=2.0,label='+ Planned Outage Loss (= Clean reference)')
    ax.fill_between(qdates,p(CL_q,10),p(CL_q,90),color=C_DARK,alpha=0.07,linewidth=0,
                    label='Base Spark Spread P10-P90 Range')
    ax.plot(qdates,avg(sp_B_q),'--',color=C_BLUE,lw=2.0,zorder=7,
            label=f'Mode B (avg ${avg(sp_B_q).mean():.1f}M/qtr)')
    ax.plot(qdates,avg(sp_C_q),'--',color=C_C,lw=2.0,zorder=7,
            label=f'Mode C (avg ${avg(sp_C_q).mean():.1f}M/qtr)')
    ax.set_ylabel('$M / quarter',fontsize=11)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4,7,10]))
    ax.tick_params(labelsize=10); ax.grid(axis='y',linestyle=':',alpha=0.4)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.legend(loc='upper left',bbox_to_anchor=(0.0,-0.14),ncol=3,fontsize=8,
              borderaxespad=0,frameon=True)
    ax.set_title('Teal area = Mode A dispatched  |  Loss lines stack to clean reference  |  Mode B (blue) and C (purple) dashed',
                 fontsize=8.5,color=C_GREY,pad=3)
    plt.tight_layout(); plt.subplots_adjust(bottom=0.22)
    save_fig(fig,'chart_spark.png'); plt.close()

def fig2_cf(out_A, modes):
    dpm=days_pm()*24
    HAC=to_monthly(out_A['hrs_actual'])/dpm; HPL=to_monthly(out_A['hrs_planned'])/dpm
    HFO=(to_monthly(out_A['hrs_forced_gt'])+to_monthly(out_A['hrs_forced_hrsg'])
        +to_monthly(out_A['hrs_forced_bop']))/dpm
    hm_B=to_monthly(modes['hrs'][1])/dpm; hm_C=to_monthly(modes['hrs'][2])/dpm
    mds=month_dates(); bar_w=timedelta(days=26)
    a_ac=avg(HAC)*100; a_pl=avg(HPL)*100; a_fo=avg(HFO)*100
    fig,ax=plt.subplots(figsize=(14,6),facecolor='white')
    fig.suptitle('Monthly Availability Breakdown (10-Year)\n'
                 'Average across 50 paths  |  Calendar-based maintenance  |  2025-2034',
                 fontsize=13,fontweight='bold',color=C_DARK)
    ax.bar(mds,a_ac,width=bar_w,color=C_TEAL,alpha=0.85,label='Dispatched (Mode A)')
    ax.bar(mds,a_pl,width=bar_w,bottom=a_ac,color=C_GOLD,alpha=0.85,label='Planned outage')
    ax.bar(mds,a_fo,width=bar_w,bottom=a_ac+a_pl,color=C_RED,alpha=0.85,label='Forced outage')
    ax.plot(mds,avg(hm_B)*100,'--',color=C_BLUE,lw=1.8,
            label=f'Mode B dispatch (avg {avg(hm_B).mean()*100:.0f}%)',zorder=6)
    ax.plot(mds,avg(hm_C)*100,'--',color=C_C,lw=1.8,
            label=f'Mode C dispatch (avg {avg(hm_C).mean()*100:.0f}%)',zorder=6)
    for y in range(N_YEARS):
        sl=slice(y*12,(y+1)*12)
        ac_ann=float(avg(HAC[:,sl].mean(axis=1)))*100
        mid=mds[y*12+6]
        ax.text(mid,ac_ann+3,f'{ac_ann:.0f}%',ha='center',va='bottom',fontsize=8,color=C_DARK,
                fontweight='bold',bbox=dict(boxstyle='round,pad=0.15',fc='white',ec='#CCC',alpha=0.8))
    ax.set_ylabel('% of hours / month',fontsize=10); ax.set_ylim(0,80)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.tick_params(labelsize=9); ax.grid(axis='y',linestyle=':',alpha=0.4)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.legend(loc='upper left',bbox_to_anchor=(0.0,-0.12),ncol=3,fontsize=8,
              borderaxespad=0,frameon=True)
    ax.set_title('Mode B/C dashed lines show conservative dispatch reduction near EOH thresholds',
                 fontsize=8.5,color=C_GREY,pad=3)
    plt.tight_layout(); plt.subplots_adjust(bottom=0.20)
    save_fig(fig,'chart_cf.png'); plt.close()

def fig3_ltsa(out_A, modes):
    def ann(k): return to_annual(out_A[k])/1e6
    fix=ann('ltsa_fixed'); eoh=ann('ltsa_eoh_reserve')
    cov=ann('ltsa_major_cov'); unc=ann('ltsa_major_uncov')
    ov=ann('ltsa_overage'); ap=ann('ltsa_avail_penalty')
    total_ov=unc+ov+ap
    lt_B=to_annual(modes['ltsa'][1])/1e6; lt_C=to_annual(modes['ltsa'][2])/1e6
    years=np.arange(2025,2035); w=0.55
    fig,ax=plt.subplots(figsize=(14,6.5),facecolor='white')
    fig.suptitle('Annual LTSA Cost Build (10-Year)\n'
                 'Average across 50 paths  |  Calendar-based maintenance  |  2025-2034',
                 fontsize=13,fontweight='bold',color=C_DARK)
    comps=[(fix,C_BLUE,'Fixed monthly fee'),(eoh,C_TEAL,'EOH reserve'),
           (cov,C_GREEN,'Major work - OEM covered'),(unc,C_RED,'Major work - LTSA overage (owner share)'),
           (ov,C_ORANGE,'Start overage charges'),(ap,C_PURPLE,'Availability penalty')]
    bottom=np.zeros(N_YEARS)
    for arr,color,label in comps:
        v=avg(arr); ax.bar(years,v,w,bottom=bottom,color=color,label=label,alpha=0.87); bottom+=v
    for i,yr in enumerate(years):
        ax.text(yr,bottom[i]+0.3,f'${bottom[i]:.0f}M',ha='center',va='bottom',fontsize=8,
                color=C_DARK,fontweight='bold')
    ax.plot(years,avg(total_ov),'o-',color=C_DARK,lw=2,markersize=6,zorder=5,
            label=f'Mode A owner overages avg (${avg(total_ov).mean():.0f}M/yr)')
    ax.plot(years,avg(lt_B),'s--',color=C_BLUE,lw=1.8,markersize=6,zorder=4,
            label=f'Mode B total LTSA (avg ${avg(lt_B).mean():.0f}M/yr)')
    ax.plot(years,avg(lt_C),'D--',color=C_C,lw=1.8,markersize=6,zorder=4,
            label=f'Mode C total LTSA (avg ${avg(lt_C).mean():.0f}M/yr)')
    ax.set_ylabel('$M / year',fontsize=11); ax.set_xticks(years); ax.tick_params(labelsize=10)
    ax.grid(axis='y',linestyle=':',alpha=0.4)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.legend(loc='upper left',bbox_to_anchor=(0.0,-0.16),ncol=3,fontsize=8,
              borderaxespad=0,frameon=True)
    ax.set_title('Mode C saves ~$75M in LTSA vs Mode A (6 fewer inspections) at cost of ~$13M spark spread over 10 yrs',
                 fontsize=8.5,color=C_GREY,pad=3)
    plt.tight_layout(); plt.subplots_adjust(bottom=0.24)
    save_fig(fig,'chart_ltsa.png'); plt.close()

def run():
    print('Loading outputs...')
    out_A=dict(np.load(NPZ_A)); raw=np.load(NPZ_MODES)
    modes=dict(spark=raw['spark'],hrs=raw['hrs'],ltsa=raw['ltsa'])
    os.makedirs(CHART_DIR,exist_ok=True)
    fig1_spark(out_A,modes); fig2_cf(out_A,modes); fig3_ltsa(out_A,modes)
    print('Done')

if __name__=='__main__': run()
