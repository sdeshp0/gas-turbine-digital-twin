# InfraSure — Gas Turbine Long-Term Performance Model

## Probabilistic Performance & Cashflow Framework

---

## 1\. Executive summary

InfraSure's Gas Turbine Long-Term Performance Model is a probabilistic framework for projecting the operating performance, maintenance cost trajectory, and cashflow distribution of gas-fired generation assets over a **10-year investment horizon**.

The model combines four analytical layers:

- **Forward-looking climate simulations** that drive ambient temperature profiles and air quality inputs, and their impact on plant capacity and heat rate across the projection period.  
- **Correlated forward energy market simulations** that generate hourly power prices (NYISO zonal) and daily gas prices (TGP Zone 6 delivered), preserving the correlation structure that drives dispatch economics.  
- **Engineering specifications** — a simplified digital twin that tracks thermal and mechanical stress accumulation, performance degradation, and component life consumption on a daily time step, without requiring proprietary OEM data.  
- **Contractual terms and limitations** from the Long-Term Service Agreement (LTSA / CSA) that constrain the maintenance schedule, define coverage boundaries, and determine the allocation of cost and risk between the OEM and the asset owner.

The climate simulation, forward energy market, and dispatch models together generate **1,000 correlated simulation paths** across the 10-year horizon. For each simulation path, the engineering model steps through each day sequentially, receiving as inputs the day's hourly dispatch schedule, hourly climate variables (temperature and air quality), hourly power prices, and daily gas price. The engineering model updates the plant's degraded state and feeds back the resulting degraded heat rate, effective capacity, variable O&M, and start costs to the dispatch model for the following day's schedule.

The output is a full probability distribution of key investor metrics — EBITDA, operating cashflow, DSCR, capacity factor, and insurance adequacy — at P10 / P50 / P90 confidence levels, across the 1,000 simulation paths and multiple dispatch operating modes.

---

## 2\. Model framework — overall architecture

The model flows left to right through five stages. The climate simulation, dispatch model, and financial/investment metrics layers are treated as pre-built modules. The core analytical contribution of this framework is the **Engineering Model** (stages 3–4), which sits between the dispatch output and the financial projections.

![InfraSure Model Framework — Technical Pipeline](./charts/infrasure_pipeline.png)

*Figure: InfraSure Model Framework — Technical Pipeline. The five-stage pipeline flows from climate and energy market inputs through the dispatch model (unit commitment and economic dispatch), into the engineering model (creep-fatigue interaction, compressor fouling, TBC Weibull failure, HRSG cycling), and through the maintenance and failure module (LTSA inspection schedule, stochastic failure events, forced outage duration sampling, and cost classification). Degraded plant parameters (HR, capacity, start costs, VOM) feed back daily to the dispatch model. See Section 2 for detailed description of each stage.*

**Key design principle:** The model runs at daily resolution. Each day, the dispatch model receives the plant's current degraded state — effective capacity, heat rate, start costs (adjusted for EOH proximity), and variable O&M — from the prior day's engineering model output. The dispatch model uses this updated plant state to generate the next day's hourly commitment and dispatch schedule. This sequential daily feedback eliminates the need for an explicit simultaneous solver and naturally captures how degradation and EOH proximity progressively reshape dispatch economics over the 10-year horizon.

---

## 3\. Engineering model — simplified digital twin

### 3.1 Concept

The engineering model is a **simplified digital twin** that tracks the accumulation of thermal and mechanical stress on the gas turbine and combined-cycle plant without access to the OEM's proprietary design data, FEA models, or material property databases.

It operates within the constraints of the LTSA/CSA contract, which defines:

- How operating hours and starts convert to **Equivalent Operating Hours (EOH)** via contractual multipliers.  
- When **scheduled inspections** (CI, HGP, Major) are triggered based on EOH or factored-start thresholds.  
- What maintenance scope is **covered vs. excluded**, determining which costs fall on the OEM and which on the asset owner.  
- **Performance guarantees** (availability, heat rate) that create contractual exposure if the plant underperforms.

The digital twin carries a **state vector** that is updated at the end of each simulated day and carried forward to the next. The state vector captures everything the dispatch model and financial layer need to know about the plant's current condition.

### 3.2 Operating stress factors

The engineering model tracks eight stress factors that impact plant performance, maintenance costs, or downtime risk. Each factor has a distinct causal mechanism, data source, and estimation methodology.

A critical design decision: **creep and fatigue damage are not tracked independently.** The literature demonstrates that creep-LCF interaction produces synergistic damage — components fail earlier than either mechanism alone would predict. The model uses a coupled damage interaction envelope rather than parallel accumulators (see section 3.2.1).

#### Priority: High

| Stress factor | Primary causal variables | Source | Impact | Estimation methodology |
| :---- | :---- | :---- | :---- | :---- |
| **EOH accumulation with creep-fatigue coupling** (hot gas path life consumption) | Fired hours, start count & type, fuel type, load factor, trip events, load swing cycles | Dispatch model, LTSA terms | Maintenance cost timing, planned outage scheduling, parts replacement cost, unplanned outage risk | GER-3620 factored-hours formula for contractual EOH tracking. Parallel physics-based damage model using coupled creep (Robinson life-fraction) \+ fatigue (Miner's rule) evaluated against an ASME N-47 interaction envelope. See 3.2.1. |
| **Capacity derating** (ambient temperature) | Ambient temperature (hourly), humidity/altitude (site-fixed), inlet cooling system | Climate model, asset specs | Revenue loss (lower MW output), capacity market shortfall risk, higher dispatch cost per MWh | OEM correction curves (\~−0.5% per °F above 59°F ISO). Applied daily from climate simulation temperature series. |
| **Heat rate degradation** (time, temperature & fouling) | Cumulative fired hours, ambient temperature, compressor condition, time since last overhaul | Dispatch model, climate model, asset specs | Incremental fuel cost (+$400–600K/yr per 1%), CSA HR guarantee exposure, reduced dispatch competitiveness | Published degradation rate: 0.8–1.5% per year between overhauls. Sawtooth model with partial reset at each inspection tier. Ambient correction overlay. Compressor fouling component uses non-linear accumulation (see row below). |
| **Combustion cycling fatigue** (LCF on liners & transition pieces) | Start count & type, trip count, load swing magnitude & frequency, min-to-max ramp cycles per day | Dispatch model | Unplanned forced outage, accelerated CI schedule, uncovered repair cost | Simplified cycle counting with damage index per start type (hot=1.0, warm=2.5, cold=4.0, trip=5.0). Partial cycle credit for load swings \>40% rated (\~0.3). Fatigue damage is coupled with creep via interaction diagram — not evaluated independently. ¹ |
| **HRSG cycling damage** (HP drum fatigue, attemperator wear, header cracking) | Start count & type (temperature differential drives damage), ramp rate, hours since shutdown | Dispatch model | Combined-cycle start cost (40–60% of total), unplanned HRSG forced outage, ST rotor thermal stress | Simplified HP drum thermal cycle counting by start type. Damage indices calibrated to NREL cycling costs report (2012). HRSG start costs tracked separately from GT start costs to enable 1×1 dispatch modeling. ⁴ |

#### Priority: Medium

| Stress factor | Primary causal variables | Source | Impact | Estimation methodology |
| :---- | :---- | :---- | :---- | :---- |
| **Compressor degradation** (fouling recoverable \+ erosion non-recoverable) | Operating hours, site air quality / coastal proximity, water wash schedule | Dispatch model, climate model (air quality) | HR degradation (\~50% of total), mass flow / output reduction, gap between CSA HR guarantee and actual | Fouling: **non-linear** accumulation (exponential approach to asymptote) with sawtooth resets at water wash intervals. Recovery 60–80% per offline wash. Air quality index from climate simulation scales fouling rate coefficient dynamically. ² Erosion: non-recoverable linear trend, reset only at major overhaul. |
| **Thermal barrier coating life** (TBC spallation on blades & vanes) | Peak firing temperature, thermal cycling severity, fuel contaminants, cumulative fired hours at temperature | Dispatch model, asset specs | Accelerated base-metal oxidation, forced outage between inspections, blade replacement cost | **Weibull failure model** with shape parameter β ≈ 2.5–4.0 and scale parameter (characteristic life) calibrated to EPRI fleet data. ³ On each simulation path, a TBC failure threshold is sampled from the Weibull CDF at path initialization; when accumulated time-at-temperature exceeds the threshold, a forced outage is triggered. Fuel quality treated as fixed site assumption (adjustable severity multiplier). |

#### Priority: Lower (tail risk)

| Stress factor | Primary causal variables | Source | Impact | Estimation methodology |
| :---- | :---- | :---- | :---- | :---- |
| **Rotor life consumption** (centrifugal stress & thermal fatigue on discs) | Total start-stop cycles, thermal transient severity, cumulative hours at speed | Dispatch model | Catastrophic failure risk (low probability / extreme cost), rotor replacement (6–12 month lead time) | Cycle-weighted life fraction consumed per start type. Linear accumulation against OEM-published rotor design life (5,000–10,000 equivalent starts). Contributes to endogenous forced outage probability (see 3.2.2). |

### 3.2.1 Creep-fatigue interaction model

Standard EOH counting tracks creep (time-at-temperature) and fatigue (start/stop cycles) as independent metrics, triggering inspections when either threshold is reached first. This approach ignores the synergistic interaction between the two damage mechanisms, which the materials science literature has shown to be significant for Ni-base superalloy components operating at elevated temperatures.

The model implements a **coupled damage interaction envelope** based on the ASME N-47 / RCC-MRx methodology:

**Creep damage fraction (D\_c):** Calculated daily using the Robinson life-fraction rule. Each day's creep damage increment is the ratio of time spent at the effective metal temperature to the rupture life at that temperature and stress level, estimated from published Larson-Miller parameters for IN738/GTD111 (typical 7FA blade alloys).

`D_c = Σ (Δt_i / t_r(T_i, σ_i))`

where Δt\_i is operating time at condition i, and t\_r is the creep rupture life from the Larson-Miller correlation.

**Fatigue damage fraction (D\_f):** Calculated using Miner's linear damage rule applied to the simplified cycle counting methodology. Each start or load swing cycle contributes a damage increment based on the cycle severity relative to the allowable cycles from generic S-N curves for the blade alloy.

`D_f = Σ (n_j / N_f(Δε_j))`

where n\_j is the number of cycles at strain range j, and N\_f is the cycles to failure from the S-N curve.

**Interaction envelope:** Rather than checking D\_c \< 1.0 and D\_f \< 1.0 independently, the combined damage must satisfy:

`D_c + D_f ≤ D_interaction`

where D\_interaction is defined by a bilinear envelope: D\_interaction \= 1.0 when either D\_c or D\_f dominates, but D\_interaction \= 0.6–0.8 in the region where both mechanisms contribute significantly. This captures the accelerated failure observed when creep and fatigue act simultaneously.

**Practical implementation:** The model maintains two parallel tracking systems: (1) the contractual EOH counter that drives the LTSA inspection schedule and billing, and (2) the physics-based creep-fatigue interaction damage that drives the endogenous forced outage probability. These may diverge — a heavily cycled unit can exhaust its physics-based damage budget before reaching the contractual EOH threshold, resulting in elevated forced outage risk between scheduled inspections.

### 3.2.2 Endogenous forced outage prediction

The engineering model generates forced outage events predictively from the stress state rather than imposing a static forced outage rate (FOR) assumption. On each simulated day, the model evaluates a composite daily forced outage probability:

`P_forced(day) = 1 - (1 - P_GT)(1 - P_HRSG)(1 - P_background)`

where:

**P\_GT** — GT-related forced outage probability, driven by the engineering stress state:

`P_GT = P_combustion(fatigue_index) + P_TBC(Weibull_state) + P_rotor(life_fraction)`

- P\_combustion rises as the combustion fatigue damage index approaches the budget threshold — modeled as a hockey-stick function that is near zero below 60% of budget, then rises steeply.  
- P\_TBC is determined by the Weibull sampling: if the accumulated time-at-temperature has exceeded the path-specific failure threshold, P\_TBC jumps to \~1.0 (forced outage occurs). Below threshold, P\_TBC represents the conditional hazard rate from the Weibull distribution.  
- P\_rotor is a very low daily probability (\~0.001–0.005% per day) that scales with rotor life fraction consumed, representing the tail risk of disc cracking.

**P\_HRSG** — HRSG-related forced outage probability, driven by HP drum cycle count and attemperator condition. Modeled as a baseline rate (\~0.5–1.0% per day during operation) that scales with cumulative thermal cycles and plant age.

**P\_background** — Residual non-GT, non-HRSG forced outage rate for causes the engineering model does not track (controls system failures, generator faults, BOP electrical, human error). Modeled as a constant baseline (\~0.3–0.5% per operating day) that increases modestly with plant age (×1.0 at year 0, ×1.5 at year 10).

When a forced outage is triggered (random draw against P\_forced), the model assigns an outage duration sampled from a lognormal distribution (median 5–15 days depending on cause) and classifies the repair cost as covered or uncovered per the LTSA terms. The forced outage also impacts the EOH proximity — the unit loses operating days, which may shift the timing of the next scheduled inspection.

**Reference notes:**

¹ **Damage indices — guidance references:** The simplified damage indices (hot=1.0, warm=2.5, cold=4.0, trip=5.0) are derived from GE's GER-3620K maintenance guidelines. EPRI report 1012586 ("Combustion Turbine Starts Modeling") and ASME GT papers on LCF life of F-class combustion hardware provide supporting calibration. The partial-cycle credit for load swings (\~0.3) is the least well-established parameter and should be sensitivity-tested. Per the creep-fatigue interaction model (3.2.1), these fatigue damage increments are evaluated against the coupled interaction envelope, not independently.

² **Compressor fouling model (revised):** Field data (Texas A\&M Turbomachinery Lab, IJISRT SGT-400 study) shows fouling rates significantly higher than previously assumed, with non-linear accumulation — rapid initial degradation that decelerates as deposits reach equilibrium. The model uses an exponential approach: `fouling_loss(t) = A × (1 - e^(-t/τ))` where A is the site-dependent asymptotic loss (1.5–4.0% HR impact) and τ is the time constant (500–1,500 fired hours). Offline water wash recovery is 60–80% of accumulated losses. Online wash provides \~40–50% of offline wash benefit. The air quality index provided by the climate simulation is used to dynamically scale the fouling rate coefficient each day: clean inland (A=1.5%, τ=1500h), humid coastal (A=2.5%, τ=1000h), industrial/dusty (A=4.0%, τ=500h).

³ **TBC Weibull model:** Coating failure distributions are drawn from EPRI's Gas Turbine Experience and Intelligence Reports (EPRI 1026609, 1025357). The Weibull shape parameter β ≈ 2.5–4.0 captures the infant mortality tail that a linear life-fraction approach misses. Scale parameter (characteristic life) is calibrated to median coating life of 24,000–32,000 equivalent fired hours, varying with firing temperature regime and fuel quality.

⁴ **HRSG cycling damage:** Cost and damage data from NREL/TP-5500-55433 (Kumar et al., 2012), which quantifies HRSG/ST cycling costs at 40–60% of total CC start costs. HP drum fatigue life is primarily driven by the temperature differential at restart — cold starts impose 3–5× the drum fatigue damage of hot starts.

---

### 3.3 Daily time-stepping with dynamic feedback

For each of the 1,000 simulation paths, the model steps sequentially through each day of the 10-year horizon. On each day, the engineering model receives inputs from the upstream pre-built modules and returns an updated plant state to the dispatch model for the following day.

**Inputs received each day (from pre-built modules):**
- **Hourly dispatch schedule** (from dispatch model): fired hours, start type, load profile per hour
- **Hourly temperature °F** (from climate simulation): drives capacity derating and creep rate
- **Hourly air quality index** (from climate simulation): drives compressor fouling rate coefficient
- **Hourly power price $/MWh** (from energy market simulation): for revenue calculation
- **Daily gas price $/MMBtu** (from gas market simulation): for fuel cost and spark spread

**Outputs returned each day (fed back to dispatch model for day+1):**
- Effective capacity (MW) — degraded by ambient and compressor erosion
- Effective heat rate (BTU/kWh) — degraded by fouling, HGP wear, ambient correction
- Start costs by type — GT wear component adjusted by EOH proximity penalty multiplier
- Variable O&M ($/MWh) — base plus any LTSA escalation


**Key design decisions in the daily loop:**

- **Forced outage check occurs before executing the dispatch schedule.** On each day, the model first evaluates P\_forced from the current stress state (section 3.2.2). If a forced outage is triggered by the random draw, the unit is unavailable for that day regardless of the dispatch schedule received.  
- **Creep and fatigue are updated as coupled quantities** evaluated against the interaction envelope, not as independent accumulators.  
- **Compressor fouling uses non-linear accumulation** (exponential approach to asymptote) scaled daily by the air quality index from the climate simulation.  
- **HRSG drum cycles are tracked** as a separate stress accumulator, and start costs are split into GT and HRSG/ST components.  
- **TBC uses a Weibull threshold** sampled at path initialization, making TBC failure timing path-specific rather than deterministic.
- **Feedback to the dispatch model** is the mechanism by which degradation progressively changes dispatch economics — as HR worsens and start costs rise with EOH proximity, the dispatch model naturally curtails marginal runs.

### 3.4 Simulation structure

The daily loop runs across 1,000 correlated simulation paths generated by the pre-built climate simulation, forward energy market, and dispatch models. The engineering model does not generate these paths — it processes each path through the daily time-stepping engine and aggregates the outputs into a probability distribution.


**Dispatch operating modes** — the simulation matrix is run under three dispatch modes that vary how aggressively EOH proximity penalizes marginal dispatch decisions:

| Mode | EOH proximity penalty | Start cost adjustment | Dispatch behaviour |
| :---- | :---- | :---- | :---- |
| **A — Maximize dispatch** | None (1.0×) | Base start costs only | Dispatches whenever energy margin \> 0\. Maximises gross revenue. Accelerates EOH accumulation and inspection timing. |
| **B — Balanced** | Non-linear: 1.0× when \>4,000 EOH from threshold, scaling to 2.5× within 1,000 EOH | Wear component scales with proximity | Dispatches freely when far from thresholds. Progressively self-curtails on marginal days as inspections approach. |
| **C — Minimize LTSA cost** | Steep: 1.0× when \>4,000 EOH from threshold, scaling to 4.0× within 2,000 EOH | Wear component scales aggressively; cold starts strongly penalized | Only dispatches on high-margin days near thresholds. Maximises interval between inspections. Sacrifices gross revenue to defer maintenance cost. |

The investor insight is the shape of the trade-off across modes: how much gross margin is sacrificed to improve tail risk, and whether the LTSA structure makes conservative dispatch clearly dominant or genuinely ambiguous.

**Prototype configuration:** The initial prototype runs **100 simulation paths × 1 year** with static dispatch schedules (pre-computed, not dynamically updated based on degradation feedback). The dispatch feedback loop will be connected in a subsequent build phase, at which point the dispatch model will re-optimize each day's schedule using the prior day's degraded plant state.

---

## 4\. Pilot implementation — Athens-type GE 7FA plant

We propose using an Athens-type GE 7FA combined cycle plant in NYISO Zone F as the pilot asset, paired with the InfraSure LTSA Summary of Terms template to define the contractual parameters.

### 4.1 Plant identity

| Parameter | Value |
| :---- | :---- |
| Reference plant | Athens-type, Selkirk NY |
| NYISO zone | Zone F (Capital) |
| Commercial operation | 2004 (\~22 years in service) |
| Configuration | 2×1 combined cycle (2 GT \+ 1 ST \+ 2 HRSG) |
| GT model | GE 7FA.03 (×2) |
| Cooling | Mechanical draft cooling towers |
| Gas interconnect | Tennessee Gas Pipeline |
| Fuel | Natural gas (no distillate backup) |
| Emissions | DLN 2.6 combustion \+ SCR \+ CO catalyst |

### 4.2 Performance parameters

**Capacity vs. ambient temperature (net plant output):**

| Ambient (°F) | GT output (each) | ST output | Net plant (MW) | Δ vs ISO |
| :---- | :---- | :---- | :---- | :---- |
| 0°F | 185 MW | 195 MW | 565 MW | \+4.6% |
| 20°F | 180 MW | 192 MW | 552 MW | \+2.2% |
| 59°F (ISO) | 171 MW | 189 MW | 531 MW | baseline |
| 80°F | 159 MW | 181 MW | 499 MW | −7.6% |
| 95°F | 148 MW | 173 MW | 469 MW | −13.1% |

**Heat rate (HHV, net) at full load:**

| Condition | HR (BTU/kWh) | Notes |
| :---- | :---- | :---- |
| Post-HGP baseline at ISO | 7,070 | Reflects 22-year non-recoverable degradation (+270 vs. new-and-clean) |
| At 90°F ambient | 7,230 | \+2.3% ambient correction |
| At 50% min load, ISO | 8,215 | 1.162× part-load multiplier |

**Heat rate degradation (between inspections) — revised per literature validation:**

| Component | Model | Recovery at offline wash | Recovery at CI | Recovery at HGP | Recovery at MI |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Compressor fouling (recoverable) | Non-linear: `A × (1 - e^(-t/τ))`, Hudson Valley class \= humid coastal (A=2.5%, τ=1000h); dynamically scaled by daily AQI input | 60–80% | 70–85% | 90% | 95% |
| Hot gas path (recoverable) | 0.2–0.4%/yr linear | — | Partial (nozzle clean) | 70–80% | 90% |
| Compressor erosion (non-recoverable) | 0.05–0.1%/yr linear | None | None | None | Partial |
| HRSG / BOP (non-recoverable) | 0.02–0.05%/yr linear | None | None | None | None |
| **Total first-year range** | **0.8–1.5%** (higher in year 1 due to non-linear fouling; decelerating thereafter) |  |  |  |  |

### 4.3 Operational constraints

| Parameter | Value |
| :---- | :---- |
| Minimum stable load | 50% (\~265 MW at ISO) |
| Ramp rate | 15 MW/min up, 20 MW/min down |
| Min run time | 4 hr (hot) / 6 hr (warm) / 8 hr (cold) |
| Min down time | 2 hr (hot) / 6 hr (warm) / 12 hr (cold) |
| Start-to-full-load | Hot \~1 hr / Warm \~2 hr / Cold \~4 hr |
| 1×1 operation | Permitted at \~55% plant capacity |

### 4.4 LTSA / CSA contract parameters — Athens pilot

The following section documents the assumed GE Contractual Service Agreement (CSA) terms for the Athens pilot asset. Parameters are structured to feed directly into `LTSAContract.py`. All assumptions are flagged and should be replaced with actual contract values when the CSA is available for review. The full due-diligence framework is documented separately in *InfraSure\_LTSA\_SummaryOfTerms\_GE7FA.docx*.

#### 4.4.1 Contract overview

| Parameter | Value |
| :---- | :---- |
| Contract type | GE Contractual Service Agreement (CSA) — Comprehensive |
| OEM provider | GE Vernova / GE Gas Power |
| Units covered | GT-A and GT-B (GE 7FA.03 ×2) |
| Billing structure | Hybrid: fixed monthly base + variable per EOH |
| Contract term | Through 2 Major Inspections (∼16 years from now, to ∼2041) |
| Escalation index | US PPI (Industrial Machinery), capped at 3.5%/year |
| Base year for escalation | 2025 |

#### 4.4.2 Inspection schedule and OEM/owner cost split

The plant has just completed a Hot Gas Path (HGP) inspection at 24,000 cumulative EOH. The next inspection cycle:

| Event | EOH trigger | EOH from now | Est. total cost (2 GTs) | OEM covers | Owner pays (uncovered) | Outage duration |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| Combustion inspection (CI) | 32,000 | 8,000 | $3.0–4.5M | 75% (∼$2.5M) | 25% (∼$0.9M) | 10–15 days |
| Combustion inspection (CI) | 40,000 | 16,000 | $3.0–4.5M | 75% (∼$2.5M) | 25% (∼$0.9M) | 10–15 days |
| Major inspection (MI) | 48,000 | 24,000 | $25–35M | 65% (∼$19.5M) | 35% (∼$10M) | 45–60 days |

**OEM coverage scope per tier:**
- **CI:** Combustion liners, transition pieces, fuel nozzles, crossfire tubes, flow sleeves. Labor included.
- **MI:** Full CI scope + turbine stage 1 & 2 blades/nozzles/shrouds (repair or new as required), compressor blade inspection, rotor inspection, bearings, labyrinth seals. Labor included.
- **Generator, HRSG, steam turbine:** Excluded from CSA scope — see Section 4.4.6.

**EOH counting rules (per GER-3620):**

| Operation | EOH rate |
| :---- | :---- |
| Fired hour — natural gas, base load | 1.0 EOH/hr |
| Hot start (\< 8 hrs shutdown) | +50 EOH per start |
| Warm start (8–72 hrs shutdown) | +150 EOH per start |
| Cold start (\> 72 hrs shutdown) | +350 EOH per start |
| Emergency trip (from full load) | +500 EOH per event |
| Load swing \> 40% rated | +0.3 EOH per swing cycle |

#### 4.4.3 Payment structure

| Component | Rate | Billing frequency | Notes |
| :---- | :---- | :---- | :---- |
| Fixed base fee | $850,000/month | Monthly | Covers OEM availability, remote monitoring, technical support, inspection labor within covered scope |
| Variable EOH reserve | $175/EOH accrued | Monthly (actual EOH that month) | Builds the major inspection parts reserve; reconciled at each inspection event |
| Variable O&M (LTSA portion) | $1.50/MWh dispatched | Monthly | Covers consumables, routine parts, field service; tracked within VOM |

**True-up mechanism:** At each inspection event, the cumulative EOH reserve balance is reconciled against actual inspection cost. If the balance exceeds actual covered cost, the surplus rolls forward. If the balance is insufficient, a catch-up invoice is issued for the uncovered owner portion plus any balance shortfall.

**Escalation:** Fixed base fee and variable EOH rate escalate annually by US PPI, capped at 3.5%/year. VOM LTSA component does not escalate separately (included in overall VOM escalation).

#### 4.4.4 Contracted start baseline and overage charges

The CSA baseline payment assumes the following annual start volumes. When cumulative YTD starts exceed these thresholds, an overage charge is applied as an uplift on the next monthly invoice.

| Start type | Annual contracted limit | Overage charge per excess event |
| :---- | :---- | :---- |
| Hot start (\< 8 hrs) | 150 starts/yr | $8,500/excess start |
| Warm start (8–72 hrs) | 35 starts/yr | $42,000/excess start |
| Cold start (\> 72 hrs) | 5 starts/yr | $125,000/excess start |
| Emergency trip | 3 events/yr | $80,000/excess event |

**Overage tracking:** Cumulative YTD start counts are compared against the pro-rated annual threshold at each month-end. Overages are billed quarterly and reset at the contract anniversary date.

*Note: The static prototype dispatch schedule generates approximately 285 hot / 69 warm / 5 cold starts per simulation per year, implying material overage charges on hot starts (∼135 excess × $8,500 = ∼$1.1M/yr). The full dispatch model with EOH proximity penalties (Mode B/C) is expected to reduce starts toward the contracted baseline.*

#### 4.4.5 Performance guarantees

| Guarantee | Contracted level | Measurement basis | Consequence of breach |
| :---- | :---- | :---- | :---- |
| Availability (excl. planned outages) | ≥ 95.0% | Annual rolling | Owner pays additional monthly fee (availability penalty uplift) |
| Heat rate | Within 2.0% of post-HGP baseline (7,070 BTU/kWh) | Per inspection cycle average | Owner pays HR penalty if degradation exceeds guarantee |
| CI outage duration | ≤ 15 days per event | Per event | OEM pays liquidated damages at $75,000/day overrun |
| MI outage duration | ≤ 60 days per event | Per event | OEM pays liquidated damages at $150,000/day overrun |

**Availability penalty mechanism:** If annual availability falls below 95%, the owner pays an uplift on the following month's fixed fee. The uplift is calculated as:

`Availability_penalty = ($850,000 / 12) × (0.95 - actual_availability) × 10`

This applies only when the shortfall is attributable to within-scope CSA failures, not excluded causes (BOP, controls, owner-caused events).

**Heat rate penalty mechanism:** If the cycle-average heat rate exceeds the contracted guarantee by more than 2.0%, the owner pays a heat rate penalty per inspection cycle:

`HR_penalty = excess_fuel_cost × penalty_factor (1.25×)`

Excess fuel cost is calculated as the MWh-weighted average HR overage multiplied by delivered gas price over the cycle.

#### 4.4.6 Coverage exclusions (Athens pilot)

The following items are excluded from CSA scope. Each exclusion requires a separate budget provision or insurance coverage:

| Excluded category | Estimated provision | Coverage source |
| :---- | :---- | :---- |
| Generator rotor/stator repair | $400,000/yr reserve | Owner O&M budget |
| HRSG (HP drum, headers, attemperators) | Covered in HRSG cycling cost model (Sections 3.2, 4.5) | Owner O&M budget |
| Steam turbine rotor, seals | $250,000/yr reserve | Owner O&M budget |
| Cooling tower, BOP electrical | $150,000/yr reserve | Owner O&M budget |
| Mark VIe controls / DCS upgrades | $100,000/yr reserve | Owner O&M budget |
| Foreign object damage (FOD) | Covered by property damage insurance | Insurance |
| Over-temperature / over-firing damage | Covered by property damage insurance (verify) | Insurance |
| Fuel system modifications | Estimated case-by-case | Owner capital budget |

#### 4.4.7 Model parameters summary (LTSAContract.py)

This table consolidates all LTSA parameters in the format consumed by `LTSAContract.py`. Values marked [ASSUME] are modelling assumptions pending actual contract review.

| Parameter | Symbol | Value | Source |
| :---- | :---- | :---- | :---- |
| Fixed monthly base fee | `LTSA_FIXED_MONTHLY` | $850,000 | [ASSUME] |
| Variable EOH reserve rate | `LTSA_EOH_RATE` | $175/EOH | [ASSUME] |
| LTSA VOM component | `LTSA_VOM` | $1.50/MWh | Framework Section 4.6 |
| PPI escalation rate (annual) | `LTSA_ESCALATION` | 3.5% cap | [ASSUME] |
| CI total cost (2 GTs, mid) | `CI_COST_TOTAL` | $3.75M | Framework Section 4.4.2 |
| CI OEM coverage fraction | `CI_OEM_FRACTION` | 0.75 | [ASSUME] |
| CI outage duration (mid) | `CI_OUTAGE_DAYS` | 12 days | Framework Section 4.4.2 |
| MI total cost (2 GTs, mid) | `MI_COST_TOTAL` | $30M | Framework Section 4.4.2 |
| MI OEM coverage fraction | `MI_OEM_FRACTION` | 0.65 | [ASSUME] |
| MI outage duration (mid) | `MI_OUTAGE_DAYS` | 52 days | Framework Section 4.4.2 |
| Contracted hot starts/yr | `BASELINE_HOT` | 150 | [ASSUME] |
| Contracted warm starts/yr | `BASELINE_WARM` | 35 | [ASSUME] |
| Contracted cold starts/yr | `BASELINE_COLD` | 5 | [ASSUME] |
| Contracted trips/yr | `BASELINE_TRIP` | 3 | [ASSUME] |
| Hot start overage charge | `OVERAGE_HOT` | $8,500 | [ASSUME] |
| Warm start overage charge | `OVERAGE_WARM` | $42,000 | [ASSUME] |
| Cold start overage charge | `OVERAGE_COLD` | $125,000 | [ASSUME] |
| Trip overage charge | `OVERAGE_TRIP` | $80,000 | [ASSUME] |
| Availability guarantee | `AVAIL_GUARANTEE` | 95.0% | [ASSUME] |
| Heat rate guarantee (vs. baseline) | `HR_GUARANTEE_PCT` | 2.0% | [ASSUME] |
| CI EOH trigger | `EOH_CI_1` | 32,000 | Framework Section 4.4.2 |
| CI EOH trigger (2nd) | `EOH_CI_2` | 40,000 | Framework Section 4.4.2 |
| MI EOH trigger | `EOH_MI` | 48,000 | Framework Section 4.4.2 |

### 4.5 Start costs (split GT and HRSG/ST)

Start costs are decomposed into GT and HRSG/ST components to enable proper 1×1 dispatch modeling and to reflect the distinct damage mechanisms (GT wear scales with EOH; HRSG/ST damage scales with temperature differential).

**GT start costs (both units):**

| Start type | Definition | GT fuel | GT wear (EOH) | GT aux | GT subtotal | EOH charged (per GT) |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| Hot | \< 8 hrs shutdown | $12K | $15K | $3K | $30K | 50 |
| Warm | 8–72 hrs shutdown | $22K | $45K | $5K | $72K | 150 |
| Cold | \> 72 hrs shutdown | $35K | $105K | $8K | $148K | 350 |
| Trip | Emergency shutdown | — | $150K | $10K | $160K | 500 |

**HRSG/ST start costs (plant-level):**

| Start type | HRSG thermal stress | ST warming | Attemperator wear | HRSG/ST subtotal | HRSG drum fatigue index |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Hot | $3K | $2K | $1K | $6K | 1.0 |
| Warm | $8K | $5K | $3K | $16K | 2.5 |
| Cold | $15K | $8K | $5K | $28K | 5.0 |
| Trip | $5K | $3K | $2K | $10K | 3.0 |

**Combined plant start costs:**

| Start type | GT subtotal | HRSG/ST subtotal | Plant total | Notes |
| :---- | :---- | :---- | :---- | :---- |
| Hot | $30K | $6K | $36K |  |
| Warm | $72K | $16K | $88K |  |
| Cold | $148K | $28K | $176K |  |
| Trip | $160K | $10K | $170K |  |
| **1×1 hot start** | **$15K** | **$4K** | **$19K** | Single GT \+ partial HRSG; enables low-cost partial dispatch |

The GT wear cost component is subject to dynamic adjustment via the dispatch mode's EOH proximity penalty multiplier. HRSG/ST costs are not penalized by EOH proximity — they scale with thermal differential only.

### 4.6 Variable O\&M

| Component | $/MWh |
| :---- | :---- |
| LTSA variable component | $1.50 |
| Non-LTSA consumables | $0.40 |
| Water / cooling | $0.25 |
| Emissions compliance | $0.15 |
| BOP wear allowance | $0.20 |
| **Total base V-O\&M** | **$2.50/MWh** |

**Part-load heat rate adjustment (polynomial):** Rather than a step table, the model uses a fitted quadratic for continuous evaluation within the dispatch optimizer:

`HR_multiplier(L) = 2.648 - 4.296×L + 2.648×L²` where L is fractional load (0.5 ≤ L ≤ 1.0)

This yields: 1.000× at 100%, 1.015× at 90%, 1.038× at 80%, 1.068× at 70%, 1.107× at 60%, 1.162× at 50%. The polynomial captures the non-convexity of CC heat rate at part load, which affects unit commitment decisions near minimum load.

### 4.7 Gas supply

Gas is delivered at TGP Zone 6\. The model only captures last-mile transport to the plant gate:

| Component | Rate | Basis |
| :---- | :---- | :---- |
| Commodity (Zone 6 delivered) | varies | $/MMBtu, daily — from gas market simulation |
| Firm lateral transport | $0.08–0.12 | $/MMBtu |
| Fuel-in-kind (retainage) | 1.5–2.0% | % of delivered volume |
| Scheduling / balancing | $0.02–0.03 | $/MMBtu |
| **Total transport adder** | **\~$0.10–0.15** | **$/MMBtu \+ retainage % on commodity** |

**Delivered cost formula:** Gas\_delivered \= Zone6\_price × (1 \+ retainage%) \+ transport\_adder \+ scheduling

### 4.8 Initial state vector (day 0\)

| State variable | Initial value | Notes |
| :---- | :---- | :---- |
| Contractual EOH (GT-A) | 24,000 | HGP just completed |
| Contractual EOH (GT-B) | 24,000 | HGP just completed |
| Next inspection threshold | 32,000 EOH (CI) | 8,000 EOH headroom |
| Creep damage fraction D\_c | 0.0 | Reset at HGP (new blades/vanes) |
| Fatigue damage fraction D\_f | 0.0 | Reset at HGP (new combustion hardware) |
| Interaction damage D\_c \+ D\_f | 0.0 | Within envelope |
| HR at ISO (post-HGP baseline) | 7,070 BTU/kWh (HHV) | Includes non-recoverable degradation |
| Cumulative HR degradation (recoverable) | 0.0% | Reset at HGP |
| Compressor fouling index | 0.0% | Water washed during HGP outage |
| Compressor fouling model params | A=2.5%, τ=1000h | Hudson Valley \= humid coastal class; dynamically scaled by AQI |
| Compressor erosion (non-recoverable) | \+1.8% HR penalty | 22 years accumulated |
| TBC time-at-temperature | 0.0 hrs | New/refurbished blades at HGP |
| TBC Weibull failure threshold | Sampled per path | β=3.0, η=28,000 equiv. fired hrs |
| HRSG drum cycle count | 0.0 | Reset to zero (drum not replaced, but cycle count restarts for tracking interval) |
| HRSG drum fatigue life fraction | \~0.30 | Estimated cumulative from 22 years |
| Rotor life fraction consumed | \~0.35 | Estimated, 22 years of service |
| Hours since last shutdown | 720+ hrs | Cold state after HGP outage |
| Model start date | Day after HGP outage completion |  |

---

## 5\. What this framework achieves without OEM data

The simplified digital twin approach provides an approximation sufficient for investor due diligence and portfolio risk assessment without requiring access to:

- OEM proprietary material property databases or component-specific S-N curves  
- Finite element stress analysis models or thermal FEA  
- Detailed coating composition or blade-specific life data  
- Real-time sensor data streams (vibration, exhaust temperature spread, combustion dynamics)

Instead, it relies on:

- **Published OEM maintenance guidelines** (GER-3620K) for EOH counting and inspection intervals  
- **EPRI fleet experience reports** (1026609, 1025357, 1012586\) for failure distributions, degradation benchmarks, and Weibull parameters for TBC life  
- **ASME and industry literature** for creep-fatigue interaction methodology (N-47 interaction diagram), simplified cycle counting calibration, and published Larson-Miller parameters for standard blade alloys (IN738, GTD111)  
- **NREL cycling costs data** (TP-5500-55433) for HRSG/ST damage quantification and start cost decomposition  
- **The LTSA contract itself** for the commercial framework that translates engineering stress into financial exposure

The daily time-stepping across 1,000 correlated simulation paths and dispatch modes produces a probabilistic picture of the plant's operating trajectory that captures the key risk factors — EOH acceleration, creep-fatigue interaction damage, degradation-driven margin erosion, inspection timing uncertainty, endogenous forced outage prediction, and HRSG cycling exposure — at a level of fidelity appropriate for investment decisions.

### 5.1 Future upgrade path — physics-informed neural networks

Recent work (MDPI Energies, 2025\) demonstrates that physics-informed neural networks (PINNs) combined with particle swarm optimization can achieve near-FEA accuracy for thermodynamic and life prediction modeling without OEM proprietary data. This represents a natural v2 upgrade from the current analytical approach, particularly if plant-specific operating data (historian exports, DCS data) becomes available. The PINN approach would replace the simplified creep-fatigue interaction model with a trained surrogate that captures non-linear material response more accurately while maintaining the daily time-stepping architecture.

---

## 6\. Literature validation summary

A review of academic papers, industry studies, and practitioner methodologies was conducted to validate this framework against the state of the art. The assessment found the architecture to be structurally sound and aligned with how industry practitioners (Timera Energy, LPTi, EPRI) approach CCGT asset valuation and life consumption modeling. No fatal architectural flaws were identified.

The following issues were identified in the initial framework draft and have been **incorporated into this version** (v1.1):

| Issue | Severity | Resolution in this document |
| :---- | :---- | :---- |
| Creep and fatigue tracked as independent accumulators; Miner's linear rule insufficient | Serious | Replaced with coupled creep-fatigue interaction model using Robinson \+ Miner evaluated against ASME N-47 interaction envelope (section 3.2.1) |
| Compressor fouling rate underestimated; wash recovery overstated | Serious | Revised to non-linear exponential model with site-class coefficients; recovery corrected to 60–80% (section 3.2, note ²; section 4.2) |
| HRSG and steam turbine cycling damage absent | Significant | Added HRSG cycling stress tracker, HRSG drum fatigue index, and split GT/HRSG start cost tables (sections 3.2, 4.5) |
| Forced outage rate imposed exogenously rather than predicted | Significant | Replaced with endogenous forced outage prediction from stress state: P\_forced \= f(combustion fatigue, TBC Weibull state, rotor life, HRSG condition, plant age) (section 3.2.2) |
| TBC failure model used linear life-fraction, missing early failure tail | Significant | Replaced with Weibull failure model (β ≈ 2.5–4.0), sampled per simulation path (section 3.2, note ³) |
| Part-load HR modeled as step table | Refinement | Replaced with fitted quadratic polynomial for continuous evaluation (section 4.6) |
| PINNs as future upgrade path | Refinement | Documented as v2 upgrade path in section 5.1 |
| Simulation horizon stated as 10–20 years | Corrected | Updated to 10-year projection horizon throughout |
| Monte Carlo paths implied to be generated by engineering model | Corrected | Clarified that 1,000 paths are generated by upstream pre-built modules (climate sim, energy market sim, dispatch model); engineering model processes each path sequentially |
| Feedback loop description incomplete | Corrected | Clarified that feedback to dispatch model includes degraded HR, effective capacity, start costs (with EOH proximity penalty), and variable O&M (sections 2, 3.3) |
| Air quality treated as fixed site assumption | Enhanced | Air quality index now provided as hourly input from climate simulation, used to dynamically scale compressor fouling rate coefficient each day |

### Issues reviewed and found to be already addressed

**Plant optionality / extrinsic value:** The daily dispatch simulation across 1,000 correlated climate and price paths inherently captures the extrinsic value of the plant's flexibility. Each simulation path produces different realized prices, and the dispatch model responds optimally (or per mode) to each realization. The distribution of cashflows across the ensemble embeds the optionality. This approach is consistent with the Timera Energy stochastic simulation methodology for CCGT valuation.

**Climate temperature autocorrelation and heat-wave persistence:** The climate simulation module generates correlated daily temperature series that preserve multi-day persistence structures (heat waves, cold snaps). This is confirmed as a feature of the pre-built climate model and does not require additional treatment in the engineering model.

---

## Appendix A — References

### Gas turbine life prediction and damage mechanics

- Abdul Ghafir, M.F. et al. (2025). "Gas turbine equivalent operating hour estimation considering creep-LCF interactions." *The Aeronautical Journal*, Cambridge University Press. [https://www.cambridge.org/core/journals/aeronautical-journal/article/gas-turbine-equivalent-operating-hour-estimation-considering-creeplcf-interactions/71B12D0158F2AD4FEC97A50B214AB918](https://www.cambridge.org/core/journals/aeronautical-journal/article/gas-turbine-equivalent-operating-hour-estimation-considering-creeplcf-interactions/71B12D0158F2AD4FEC97A50B214AB918)  
- Abdulsalam, I. & Orisaleye, J. (2023). "Creep-Fatigue Interaction Life Consumption of Industrial Gas Turbine Blades." *Academia*. [https://www.academia.edu/48345689/Creep\_Fatigue\_Interaction\_Life\_Consumption\_of\_Industrial\_Gas\_Turbine\_Blades](https://www.academia.edu/48345689/Creep_Fatigue_Interaction_Life_Consumption_of_Industrial_Gas_Turbine_Blades)  
- Omidiyan, M. et al. (2026). "A climate-adaptive thermo-mechanical mathematical model for predicting cumulative creep damage in gas turbine blades." *Journal of Engineering and Applied Science*, Springer. [https://link.springer.com/article/10.1186/s44147-026-00986-9](https://link.springer.com/article/10.1186/s44147-026-00986-9)  
- NASA (2006). "NASALife — Component Fatigue and Creep Life Prediction Program." NASA Technical Reports. [https://ntrs.nasa.gov/api/citations/20060013345/downloads/20060013345.pdf](https://ntrs.nasa.gov/api/citations/20060013345/downloads/20060013345.pdf)  
- NASA (2012). "Determination of Turbine Blade Life from Engine Field Data." [https://ntrs.nasa.gov/api/citations/20120007098/downloads/20120007098.pdf](https://ntrs.nasa.gov/api/citations/20120007098/downloads/20120007098.pdf)  
- Life Prediction Technologies Inc. "XactLIFE Digital Twin Platform" — physics-based predictive maintenance for gas turbines. [https://www.lifepredictiontech.com/xactlife-platform](https://www.lifepredictiontech.com/xactlife-platform)

### Digital twin and performance modeling

- Karakurt, S.A. et al. (2025). "Towards a Digital Twin for Gas Turbines: Thermodynamic Modeling, Critical Parameter Estimation, and Performance Optimization Using PINN and PSO." *MDPI Energies* 18(14), 3721\. [https://www.mdpi.com/1996-1073/18/14/3721](https://www.mdpi.com/1996-1073/18/14/3721)  
- Yildirim, M.T. & Kurt, B. (2024). "A Novel Data-Driven Approach for Predicting the Performance Degradation of a Gas Turbine." *MDPI Energies* 17(4), 781\. [https://www.mdpi.com/1996-1073/17/4/781](https://www.mdpi.com/1996-1073/17/4/781)  
- Gannan, A. (2023). "Gas turbine degradation." In *Innovation and Technological Advances for Gas Turbines*, Taylor & Francis. [https://www.taylorfrancis.com/chapters/oa-edit/10.1201/9781003496724-8/gas-turbine-degradation-aiyad-gannan](https://www.taylorfrancis.com/chapters/oa-edit/10.1201/9781003496724-8/gas-turbine-degradation-aiyad-gannan)

### Compressor fouling and degradation

- Kurz, R. & Brun, K. "Gas Turbine Performance Deterioration and Compressor Washing." Texas A\&M Turbomachinery Laboratory. [https://turbolab.tamu.edu/wp-content/uploads/2018/08/METS2Tutorial5.pdf](https://turbolab.tamu.edu/wp-content/uploads/2018/08/METS2Tutorial5.pdf)  
- Okonkwo, U. et al. (2023). "Evaluation of Offline Compressor Water Washing and its Effect on Siemens SGT-400 Gas Turbine Performance." *IJISRT*. [https://www.ijisrt.com/assets/upload/files/IJISRT23AUG626.pdf](https://www.ijisrt.com/assets/upload/files/IJISRT23AUG626.pdf)  
- Igie, U. et al. "Gas turbine axial compressor fouling and washing." *ResearchGate*. [https://www.researchgate.net/publication/285465709\_Gas\_turbine\_axial\_compressor\_fouling\_and\_washing](https://www.researchgate.net/publication/285465709_Gas_turbine_axial_compressor_fouling_and_washing)

### Power plant cycling costs

- Kumar, N., Besuner, P., Lefton, S., Agan, D., & Hilleman, D. (2012). "Power Plant Cycling Costs." NREL/TP-5500-55433. [https://docs.nrel.gov/docs/fy12osti/55433.pdf](https://docs.nrel.gov/docs/fy12osti/55433.pdf)  
- Lew, D. et al. (2012). "Impacts of Renewable Generation on Fossil Fuel Unit Cycling: Costs and Emissions." NREL. [https://docs.nrel.gov/docs/fy12osti/55828.pdf](https://docs.nrel.gov/docs/fy12osti/55828.pdf)  
- Intertek APTECH. "Power Plant Cycling Cost and Flexible Generation." [https://www.intertek.com/power-generation/cost-of-cycling-analysis/](https://www.intertek.com/power-generation/cost-of-cycling-analysis/)

### CCGT valuation, optionality, and dispatch optimization

- Timera Energy. "Getting comfortable with CCGT extrinsic value." [https://timera-energy.com/blog/getting-comfortable-with-ccgt-extrinsic-value/](https://timera-energy.com/blog/getting-comfortable-with-ccgt-extrinsic-value/)  
- Timera Energy. "Power plant optionality & dispatch cost hurdles." [https://timera-energy.com/blog/power-plant-optionality-dispatch-cost-hurdles/](https://timera-energy.com/blog/power-plant-optionality-dispatch-cost-hurdles/)  
- Timera Energy. "Monetising the value of flexible gas & power assets." [https://timera-energy.com/blog/monetising-the-value-of-flexible-gas-power-assets/](https://timera-energy.com/blog/monetising-the-value-of-flexible-gas-power-assets/)  
- Nasakkala, E. & Fleten, S.-E. (2004). "Flexibility and Technology Choice in Gas Fired Power Plant Investments." *Real Options Conference*. [https://www.realoptions.org/papers2004/NasakkalaGasPlant.pdf](https://www.realoptions.org/papers2004/NasakkalaGasPlant.pdf)  
- Deng, S. & Oren, S.S. (2006). "Valuation of Spark-Spread Options with Mean Reversion and Stochastic Volatility." *ResearchGate*. [https://www.researchgate.net/publication/26542269\_Valuation\_of\_Spark-Spread\_Options\_with\_Mean\_Reversion\_and\_Stochastic\_Volatility](https://www.researchgate.net/publication/26542269_Valuation_of_Spark-Spread_Options_with_Mean_Reversion_and_Stochastic_Volatility)  
- Tofighi-Niaki, A. (2024). "Economic Dispatch of Combined Cycle Power Plant: A Mixed-Integer Programming Approach." *MDPI Processes* 12(6), 1199\. [https://www.mdpi.com/2227-9717/12/6/1199](https://www.mdpi.com/2227-9717/12/6/1199)

### EOH methodology and LTSA structures

- ASME (1999). "Total Equivalent Operating Hours (TEOH)." ASME Turbo Expo. [https://asmedigitalcollection.asme.org/GT/proceedings-pdf/GT1999/78606/V003T02A010/2412397/v003t02a010-99-gt-244.pdf](https://asmedigitalcollection.asme.org/GT/proceedings-pdf/GT1999/78606/V003T02A010/2412397/v003t02a010-99-gt-244.pdf)  
- Power Magazine. "Extend EOH tracking to the entire plant." [https://www.powermag.com/extend-eoh-tracking-to-the-entire-plant/](https://www.powermag.com/extend-eoh-tracking-to-the-entire-plant/)  
- KBR (2023). "An Approach for Gas Turbine Life Extension." [https://www.kbr.com/sites/default/files/documents/2023-09/1006\_ENG\_Myers\_Approach\_Gas\_Turbine.pdf](https://www.kbr.com/sites/default/files/documents/2023-09/1006_ENG_Myers_Approach\_Gas_Turbine.pdf)

### Fleet experience and reliability

- EPRI. "Integrated Approach to Gas Turbine Rotor Reliability." ETN Global presentation. [https://etn.global/wp-content/uploads/2017/11/21\_EPRI\_JS.pdf](https://etn.global/wp-content/uploads/2017/11/21_EPRI_JS.pdf)  
- Combined Cycle Journal. "7F Users Group — field experience and fleet issues." [https://www.ccj-online.com/4q-2014/7f-users-group/](https://www.ccj-online.com/4q-2014/7f-users-group/)  
- Combined Cycle Journal. "Combustion Dynamics Monitoring: Advanced CDM detects impending combustor failure." [https://www.ccj-online.com/combustion-dynamics-monitoring-advanced-cdm-detects-impending-combustor-failure-prevents-forced-outage/](https://www.ccj-online.com/combustion-dynamics-monitoring-advanced-cdm-detects-impending-combustor-failure-prevents-forced-outage/)

---


---

## Appendix B — Methodology assumptions register

Assumptions embedded in the engineering model methodology. Distinct from simulated inputs, asset parameters (Section 4), and LTSA contract terms (Section 4.4). All values are prototype calibrations; update as asset-specific data becomes available.

**Certainty ratings:** Green — well-established published literature | Amber — industry benchmark, moderate uncertainty | Red — sensitivity-test required before investment decisions.

### B.1 Creep-fatigue interaction model

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| Interaction envelope `D_interaction` | 0.60–0.80 in mixed region; 1.0 when one mechanism dominates | Combined damage threshold where creep and fatigue act simultaneously (ASME N-47 bilinear envelope) | Amber | ASME N-47 / RCC-MRx; Abdul Ghafir et al. (2025) *Aeronautical J.*; Abdulsalam & Orisaleye (2023) |
| Larson-Miller parameters | IN738 / GTD111 published values | Creep rupture life t\_r for Robinson life-fraction rule | Green | Abdul Ghafir et al. (2025); NASA (2006) NASALife; NASA (2012) blade life report |
| Effective metal temperature estimation | Inferred from load factor + ambient temp; not directly measured | Controls creep rate; key input to Larson-Miller correlation | Amber | Modelling assumption; Omidiyan et al. (2026) *Springer J. Eng.* |

### B.2 Combustion fatigue cycle counting

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| Hot start damage index | 1.0 (reference) | Miner’s rule cycle damage per hot start against S-N budget | Green | GE GER-3620K; EPRI 1012586 |
| Warm start damage index | 2.5 | 2.5× hot start damage; moderate thermal gradient | Green | GE GER-3620K; EPRI 1012586 |
| Cold start damage index | 4.0 | 4× hot start damage; high thermal gradient | Green | GE GER-3620K; EPRI 1012586 |
| Trip damage index | 5.0 | Highest LCF damage; emergency shutdown from full load | Amber | GE GER-3620K (derived); ASME GT papers on F-class combustion LCF |
| Load swing partial cycle credit | 0.3 per swing >40% rated | Partial fatigue damage from large intra-day load swings | **Red** — sensitivity-test required | Engineering judgment; no primary reference |
| P\_combustion hockey stick inflection | Near zero below 60% of damage budget; rises steeply above | Converts combustion fatigue index to daily forced outage probability | Amber | Engineering judgment; calibrated to expected failure distribution |

### B.3 Compressor degradation

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| Fouling model form | Exponential: `A × (1 − e^(−t/τ))` | Non-linear accumulation decelerating to asymptote | Green | Kurz & Brun (Texas A&M TurboLab); Okonkwo et al. (2023 IJISRT) |
| Site class coefficients (Hudson Valley) | A = 2.5% HR impact, τ = 1,000 fired hours | Humid coastal fouling rate; AQI input scales daily rate | Amber | Igie et al. (ResearchGate); Okonkwo et al. (2023 IJISRT); field calibration |
| Offline wash recovery fraction | 70% mid-point (range 60–80%) | Resets recoverable fouling at offline wash events | Amber | Kurz & Brun (Texas A&M TurboLab); Okonkwo et al. (2023) |
| Online wash benefit vs. offline | 45% of offline wash benefit | Partial recovery during operation | Amber | Kurz & Brun (Texas A&M TurboLab) |
| Non-recoverable erosion rate | 0.075%/yr HR impact (range 0.05–0.10%) | Permanent compressor loss; resets only at MI | Amber | Gannan (2023, Taylor & Francis); Yildirim & Kurt (2024 MDPI Energies) |

### B.4 Heat rate degradation

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| HGP recoverable degradation rate | 0.3%/yr (range 0.2–0.4%) | Linear HR increase between overhauls from hot gas path wear | Green | Yildirim & Kurt (2024 *MDPI Energies* 17(4)); published OEM benchmarks |
| CI partial recovery (HGP component) | ∼30% of accumulated HGP degradation | Nozzle clean at CI provides partial but not full HR restoration | Amber | Engineering judgment; OEM field practice |
| HGP recovery fraction | 75% (range 70–80%) | HR restoration via blade/nozzle replacement at HGP | Green | GE GER-3620K; EPRI fleet experience reports |
| MI recovery fraction | 90% | Full overhaul; residual from non-recoverable erosion | Green | GE GER-3620K; EPRI fleet experience reports |
| HRSG/BOP non-recoverable degradation | 0.035%/yr (range 0.02–0.05%) | Permanent plant-level efficiency loss; not reset by any inspection | Amber | Gannan (2023, Taylor & Francis); industry benchmarks |

### B.5 Capacity derating

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| Ambient temperature derating coefficient | −0.5%/°F above 59°F ISO | Reduces effective plant capacity each hour from climate temperature input | Green | GE 7FA OEM correction curves; ISO 2314 performance methodology |
| Derating bounds applied in code | Clipped to [0.80, 1.05] × ISO capacity | Physical constraint at temperature extremes; 1.05 captures cold-weather uprating | Amber | Engineering constraint; consistent with OEM cold-weather uprating specifications |

### B.6 Part-load heat rate polynomial

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| HR multiplier polynomial coefficients | `2.648 − 4.296L + 2.648L²` for L ∈ [0.5, 1.0] | Continuous part-load HR correction; captures non-convexity near minimum load | Green | Fitted to GE 7FA.03 OEM part-load data; Tofighi-Niaki (2024 *MDPI Processes* 12(6)) |

### B.7 TBC failure model

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| Weibull shape parameter β | 3.0 (range 2.5–4.0) | Controls early-failure tail; sampled per simulation path at initialisation | Amber | EPRI 1026609; EPRI 1025357 (*Gas Turbine Experience & Intelligence Reports*) |
| Weibull scale parameter η (characteristic life) | 28,000 equivalent fired hours | Median TBC coating life calibrated to EPRI fleet data | Amber | EPRI 1026609; EPRI 1025357 |

### B.8 Endogenous forced outage probabilities

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| P\_rotor baseline daily probability | 0.003%/day (range 0.001–0.005%) | Very low tail-risk of disc cracking; scales with rotor life fraction | **Red** — sensitivity-test required | EPRI rotor reliability study (ETN Global presentation); engineering judgment |
| P\_HRSG baseline daily probability | 0.75%/day (range 0.5–1.0%) | HP drum, attemperator and header failure; scales with age and thermal cycles | Amber | NREL TP-5500-55433 (Kumar et al. 2012); industry benchmarks |
| P\_background baseline daily probability | 0.4%/day (range 0.3–0.5%) | Residual non-GT/HRSG outage risk (controls, generator, BOP, human error) | Amber | NERC GADS data ranges; industry practice |
| P\_background age multiplier | Linear: 1.0× (year 0) → 1.5× (year 10) | Captures increasing background failure rate as plant and controls age | **Red** — sensitivity-test required | Engineering judgment; no primary reference |

### B.9 Forced outage duration

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| Outage duration distribution | Lognormal | Right-skewed; most events short, rare events very long | Green | NERC GADS historical data; standard industry practice |
| GT-related outage median duration | 8 days (range 5–12) | Duration sampled for GT failure mode forced outage events | Amber | NERC GADS; EPRI fleet experience; CCJ 7F Users Group |
| HRSG-related outage median duration | 12 days (range 8–15) | Duration sampled for HRSG/ST forced outage events | Amber | NREL TP-5500-55433 (Kumar et al. 2012); NERC GADS |
| BOP/background outage median duration | 5 days (range 3–7) | Duration sampled for controls, electrical and human-error events | Amber | NERC GADS; industry practice |

### B.10 HRSG cycling damage

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| HP drum fatigue index — hot start | 1.0 (reference) | Thermal cycle damage per start type; drives HRSG forced outage probability | Green | NREL TP-5500-55433 (Kumar et al. 2012) |
| HP drum fatigue index — warm start | 2.5 | Higher temperature differential on restart vs. hot start | Green | NREL TP-5500-55433 (Kumar et al. 2012) |
| HP drum fatigue index — cold start | 5.0 | Maximum drum thermal shock; 3–5× hot start damage | Green | NREL TP-5500-55433 (Kumar et al. 2012) |
| HP drum fatigue index — trip | 3.0 | Rapid pressure transient on emergency shutdown | Amber | Engineering judgment; NREL TP-5500-55433 (partial basis) |

### B.11 Rotor life consumption

| Assumption / variable | Value | Purpose in model | Certainty | Reference / source |
| :---- | :---- | :---- | :---- | :---- |
| Rotor design life | 7,500 equivalent starts (range 5,000–10,000) | OEM-published design life benchmark; denominates life fraction calculation | Amber | EPRI rotor reliability study (ETN Global); GE 7FA fleet data |
| Rotor cycle weighting by start type | Hot = 1×, warm = 2×, cold = 4× against design life | Weighted life fraction consumed per start; heavier for high-thermal-gradient starts | Amber | Engineering judgment; consistent with GER-3620K severity factors |


---

## Appendix C — Athens pilot simulation run

### C.1 Overview

This appendix documents the prototype simulation for the Athens-type GE 7FA.03 2×1 combined cycle asset in NYISO Zone F, conducted as the inaugural pilot of the InfraSure Gas Turbine Long-Term Performance Model.

**Configuration:**

| Parameter | Value |
| :---- | :---- |
| Asset | GE 7FA.03 ×2, 531 MW net at ISO |
| Location | NYISO Zone F (Capital / Hudson Valley) |
| Projection horizon | 10 years (2025–2034) |
| Simulation paths | 50 paths (from 1,000 synthetic market simulations, 10 per year) |
| Starting state | Post-HGP at 24,000 EOH, all stress accumulators reset |
| Dispatch modes | A (maximize), B (balanced), C (minimize LTSA cost) |
| Maintenance scheduling | Calendar-based: April / October shoulder months |

**Key pilot outputs (Mode A, 50-path average):**

| Metric | Value |
| :---- | :---- |
| Average annual spark spread | $33.6M/yr |
| Average capacity factor (dispatched) | 28.0% |
| Planned outage | 13.0% of hours |
| Forced outage (HRSG + BOP) | ~13% of hours |
| Total LTSA cost (10 years) | ~$430M |
| Owner uncovered LTSA costs | ~$90M |
| CI inspections (10 years) | 12 |
| MI inspections (10 years) | 6 |

**Mode comparison:**

| Mode | Annual spark spread | Annual CF | Total LTSA (10 yr) |
| :---- | :---- | :---- | :---- |
| A — Maximize dispatch | $33.6M/yr | 28.0% | ~$430M |
| B — Balanced | $33.7M/yr | 27.9% | ~$396M |
| C — Minimize LTSA | $32.3M/yr | 26.5% | ~$350M |

Mode C sacrifices ~$1.3M/yr in spark spread to save ~$80M in LTSA over 10 years (net benefit ~$67M), achieved by deferring inspections through lower EOH accumulation near thresholds.

### C.2 Market and climate input validation

![Market and climate inputs: 10 paths x 10 years with P10-P90 shading](./charts/chart_inputs_new.png)

*Figure C.1: Synthetic market and climate inputs across 10 simulation paths × 10 years (2025–2034). Average + P10–P90 shading. Panels: power price, gas price, clean spark spread, temperature, air quality index.*

### C.3 Quarterly spark spread revenue attribution

![Quarterly spark spread attribution: teal area + stacked loss lines + Mode B and C dashed](./charts/chart_spark.png)

*Figure C.2: Quarterly spark spread revenue attribution (Mode A bars, Mode B blue dashed, Mode C purple dashed). Stacked loss lines from actual dispatch to clean reference: degradation loss, forced outage loss, planned outage loss.*

### C.4 Monthly availability breakdown

![Monthly availability stacked bar chart with Mode B and C dashed lines](./charts/chart_cf.png)

*Figure C.3: Monthly availability breakdown (2025–2034). Stacked bars: dispatched (teal), planned outage (gold), forced outage (red). Mode B/C dashed lines show conservative dispatch reduction.*

### C.5 Annual LTSA cost build

![Annual LTSA cost build with Mode B and C comparison lines](./charts/chart_ltsa.png)

*Figure C.4: Annual LTSA cost build (2025–2034). Mode A stacked bars (fixed fee, EOH reserve, OEM-covered work, owner-uncovered, start overages). Mode B/C dashed lines show total LTSA for conservative modes. Note the alternating CI (lower) and MI (higher) inspection cost pattern.*

---

## Appendix D — Assumption sensitivity analysis

### D.1 Methodology

A standard one-at-a-time tornado sensitivity analysis was conducted across the 17 highest-priority assumptions from the register in Appendix B. Each assumption was perturbed independently by:
- **±20%** for Amber and Green assumptions
- **±50%** for Red assumptions (wider acknowledged uncertainty range)

Impact was measured on three output metrics: average annual spark spread, average capacity factor, and average annual LTSA cost. Run configuration: 10 simulation paths, Mode A only, 10-year horizon.

### D.2 Key findings

**Dominant driver — P\_background age multiplier (Red, ±50%):** Impact −2.0M to +$1.6M/yr on spark spread. This is the linear aging factor scaling background forced outage probability from 1.0× (year 0) to 1.5× (year 10). As flagged in Appendix B, there is no primary reference supporting this specific aging curve and it requires dedicated stress testing.

**Second tier — HRSG and background outage rates (Amber, ±20%):** P\_HRSG\_baseline (−0.96M to +$0.42M/yr) and P\_background\_baseline (−0.77M to +$0.31M/yr) are the next most impactful, driven by their direct effect on available dispatch hours.

**Ambient derating (Green, ±20%):** Larger-than-expected impact (−0.53M to +$0.65M/yr), driven by seasonal dispatch sensitivity to plant output at elevated summer temperatures.

**Near-zero impact on spark spread:** LTSA inspection costs, fixed fees, and start overage charges correctly show zero impact on spark spread (spark spread excludes LTSA costs). TBC and combustion parameters show near-zero impact because the plant recently completed an HGP and stress accumulators are near zero at the start of the projection.

![Tornado sensitivity chart: three panels for spark spread, capacity factor, LTSA cost](./charts/chart_sensitivity.png)

*Figure D.1: Tornado sensitivity analysis. Solid bars = impact of +pct perturbation; lighter bars = -pct perturbation. Bars right = positive impact; bars left = negative impact. Sorted by absolute impact on spark spread (largest at bottom).*

### D.3 Priority recommendations

| Priority | Assumption | Certainty | Recommended action |
| :---- | :---- | :---- | :---- |
| 1 | P\_background age multiplier | **Red** | Monte Carlo over [1.0×, 2.0×]; seek fleet aging data |
| 2 | P\_HRSG baseline (/day) | Amber | Calibrate against NERC GADS HRSG data for similar CC fleet |
| 3 | P\_background baseline (/day) | Amber | Calibrate against NERC GADS BOP/controls failure statistics |
| 4 | Offline wash recovery (70%) | Amber | Request compressor wash records from OEM/operator |

---

## Appendix E — Back-cast validation

### E.1 Overview

The back-cast validation compares the model’s synthetic market input distributions against actual historical market and climate data for NYISO Zone F and TGP Zone 6 over 2015–2024.

**Data sources:**

| Variable | Source | Period |
| :---- | :---- | :---- |
| NYISO Zone F power price | NYISO Annual Market Reports; EIA Wholesale Markets | 2015–2024 |
| TGP Zone 6 gas price | Henry Hub (EIA) + Zone 6 basis (~$0.20/MMBtu) | 2015–2024 |
| Albany, NY temperature | NOAA GHCN-D, Albany International Airport | 2015–2024 |

*Hourly zonal NYISO data is not accessible via public API; annual averages sourced from NYISO published reports. TGP Zone 6 spot prices are not publicly available; Henry Hub + basis used as proxy.*

### E.2 Validation chart

![Back-cast validation: four panels showing actual vs synthetic for power price, gas price, spark spread, temperature](./charts/chart_backcast.png)

*Figure E.1: Back-cast validation (2015–2024). Black line = actual annual averages. Teal dashed line = synthetic model average. Teal shaded band = synthetic model P10–P90 range.*

### E.3 Findings

| Variable | Synthetic avg | Historical avg (2015–2024) | Assessment |
| :---- | :---- | :---- | :---- |
| Power price | $41.8/MWh | $43.3/MWh | **Excellent match** (−4%) |
| Gas price (delivered) | $4.14/MMBtu | $3.49/MMBtu | **+19% above historical avg** — appropriate; model calibrated to 2025 forward levels, which are above the historically low 2015–2020 period |
| Spark spread | $10.0/MWh | $16.2/MWh | Lower in model due to higher gas calibration; synthetic P10–P90 range (-$11 to +$31) encompasses most of the historical range |
| Temperature | 53.0°F | 51.8°F | **Excellent match** (-1.2°F) |

### E.4 Tail-event gap — 2021–2022 crisis

The 2021–2022 period (Winter Storm Uri + Russia/Ukraine gas price shock) drove NYISO Zone F spark spreads to **$25–38/MWh** — at or above the synthetic model P90. The synthetic stochastic model is calibrated to normal market conditions and does not include correlated commodity price shock scenarios of this severity.

**Implication:** A dedicated stress scenario using 2022-type gas prices ($6–10/MMBtu) should be run to assess: (a) the upside on spark spread revenues (high gas prices favour efficient plant dispatch); and (b) the downside on LTSA overage costs (higher dispatch at elevated prices accelerates EOH accumulation). This stress scenario can be generated by adjusting the gas price distribution parameters without changing any engineering assumptions.

*InfraSure | Confidential | Model Framework v1.4 — Appendices C–E added*  
  
