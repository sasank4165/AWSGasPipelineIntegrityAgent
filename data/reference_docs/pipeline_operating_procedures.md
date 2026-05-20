# Natural Gas Transmission Pipeline — Operating Procedures
## 200-Mile, 24-Inch Diameter System | ST-01 through ST-08
### Normal Operations, Abnormal Conditions & Emergency Response

---

## 1. System Overview

### 1.1 Pipeline Description
- Total length: 200 miles
- Pipe diameter: 24 inches nominal
- Wall thickness: 0.375 inches
- Material grade: API 5L X65
- Maximum Allowable Operating Pressure (MAOP): 850 psi
- Design pressure: 900 psi
- Normal operating pressure range: 700–800 psi
- Normal throughput: 5.5–6.5 MMSCFD

### 1.2 Station Summary

| Station | Type | Mile Marker | Normal Pressure (psi) | Normal Flow (MMSCFD) |
|---|---|---|---|---|
| ST-01 | Compressor | 0 | 760–800 | 6.0–6.5 |
| ST-02 | Meter | 28 | 745–785 | 5.9–6.4 |
| ST-03 | Meter | 52 | 735–775 | 5.9–6.4 |
| ST-04 | Compressor | 78 | 755–795 | 5.9–6.4 |
| ST-05 | Meter | 104 | 740–780 | 5.8–6.3 |
| ST-06 | Custody Transfer | 130 | 730–770 | 5.8–6.3 |
| ST-07 | Meter | 158 | 720–760 | 5.7–6.2 |
| ST-08 | Custody Transfer | 200 | 710–750 | 5.7–6.2 |

### 1.3 Isolation Valve Locations
Key mainline valves (remotely operable from SCADA):

| Valve ID | Mile Marker | Segment | Normal Position |
|---|---|---|---|
| V-08 | 8 | SEG-01 | Open |
| V-18 | 18 | SEG-01 | Open |
| V-38 | 38 | SEG-02 | Open |
| V-48 | 48 | SEG-02 | Open |
| V-52 | 52 | SEG-02/03 boundary | Open |
| V-60 | 60 | SEG-03 | Open |
| V-70 | 70 | SEG-03 | Open |
| V-88 | 88 | SEG-04 | Open |
| V-100 | 100 | SEG-04 | Open |
| V-112 | 112 | SEG-05 | Open |
| V-122 | 122 | SEG-05 | Open |
| V-138 | 138 | SEG-06 | Open |
| V-150 | 150 | SEG-06 | Open |
| V-168 | 168 | SEG-07 | Open |
| V-182 | 182 | SEG-07 | Open |
| V-192 | 192 | SEG-07 | Open |

---

## 2. Normal Operating Procedures

### 2.1 Shift Handover Checklist
Before accepting shift, verify:
- [ ] All station pressures within normal operating range (see Section 1.2)
- [ ] All flow rates within normal range
- [ ] No active alarms on SCADA
- [ ] All isolation valves in correct position (open/closed per operating plan)
- [ ] Compressor status at ST-01 and ST-04 (running/standby)
- [ ] No open work orders affecting pipeline integrity
- [ ] Weather forecast reviewed (temperature drops >15°F overnight require line pack monitoring)

### 2.2 Compressor Start Procedure (ST-01 and ST-04)
**Expected transient**: Compressor start causes a pressure surge of 15–25 psi at the station and a flow increase of 0.3–0.5 MMSCFD. This is a normal false-positive trigger for leak detection algorithms. Log all compressor starts in the SCADA event log.

1. Verify suction pressure ≥ 650 psi before start
2. Verify discharge check valve is closed
3. Start compressor at minimum speed (idle)
4. Ramp to operating speed over 3–5 minutes
5. Monitor discharge pressure — do not exceed MAOP (850 psi)
6. Log start time, suction pressure, discharge pressure in SCADA
7. Notify leak detection system operator of planned start (prevents false alarm)

### 2.3 Valve Operation Procedure
**Expected transient**: Control valve position changes cause pressure redistribution of 8–15 psi across the affected segment. Duration: 8–20 minutes until system re-equilibrates. Log all valve changes.

1. Confirm authorization from shift supervisor before any mainline valve operation
2. Operate valve slowly — no faster than 10% position change per minute
3. Monitor upstream and downstream pressures during operation
4. Log valve ID, time, old position, new position in SCADA
5. Notify leak detection system operator of planned valve change

### 2.4 Line Pack Calculation
Line pack is the volume of gas stored in the pipeline at operating pressure. Temperature drops cause gas contraction, reducing line pack and creating a pressure drop that mimics a leak signature.

**Line pack calculation (simplified):**
```
LP (MMSCF) = (P_avg_psi / 14.696) × (519.67 / T_avg_R) × (1 / Z) × V_pipe_MMSCF
```
Where:
- P_avg = average pressure in segment (psi)
- T_avg_R = average gas temperature (Rankine = °F + 459.67)
- Z = compressibility factor (from gas composition data)
- V_pipe = physical pipe volume (MMSCF)

**Temperature correction rule of thumb:**
- Every 10°F temperature drop reduces line pack by approximately 0.18–0.22 MMSCF per 26-mile segment
- A 20°F overnight temperature drop can create a mass balance deficit of 0.35–0.45 MMSCFD — this is a false positive, not a leak
- Always check overnight temperature delta before declaring a pressure anomaly as a leak

---

## 3. Abnormal Operating Conditions

### 3.1 Pressure Anomaly Response Procedure
When SCADA detects a pressure drop or mass balance deficit:

**Step 1 — Initial Assessment (0–5 minutes)**
1. Identify affected station(s) and segment
2. Check SCADA event log: any compressor starts or valve changes in last 2 hours?
3. Check weather data: overnight temperature drop >10°F?
4. Calculate temperature-corrected line pack change
5. If anomaly explained by operations or temperature: log as false positive, continue monitoring

**Step 2 — Anomaly Confirmation (5–15 minutes)**
If anomaly is NOT explained by operations or temperature:
1. Calculate mass balance deficit across affected segment:
   ```
   Deficit (MMSCFD) = Flow_in (MMSCFD) - Flow_out (MMSCFD)
   ```
2. If deficit > 0.15 MMSCFD sustained for >10 minutes: escalate to potential leak
3. Notify shift supervisor and on-call pipeline integrity engineer

**Step 3 — Leak Localization (15–30 minutes)**
1. Analyze pressure gradient across all stations in affected segment
2. Pressure drop will be steepest at the station nearest the leak
3. Estimate leak location using pressure wave arrival time difference (if available)
4. Cross-reference with pipeline inspection data (ILI results, known anomalies)

**Step 4 — Isolation Decision**
- If leak rate estimated >0.3 MMSCFD: isolate segment (see Section 3.2)
- If leak rate <0.3 MMSCFD: dispatch inspection crew; maintain reduced pressure (700 psi max)
- If near-rupture indicators (pressure drop >50 psi in <5 minutes): immediate isolation

### 3.2 Segment Isolation Procedure
1. Notify all downstream customers of potential interruption
2. Reduce compressor output to minimum
3. Close upstream isolation valve (nearest valve upstream of suspected leak)
4. Close downstream isolation valve (nearest valve downstream of suspected leak)
5. Monitor isolated segment pressure — if pressure holds, leak is outside isolated segment
6. If pressure continues to drop: leak is within isolated segment — confirmed
7. Vent isolated segment to safe level before dispatching repair crew
8. Document isolation time, valve IDs, and pressures in incident log

### 3.3 High Pressure Response
If any station pressure exceeds MAOP (850 psi):
1. Immediately reduce compressor output
2. Open pressure relief valve if available at station
3. If pressure exceeds 900 psi (design pressure): emergency shutdown of compressors
4. Do not resume operations until cause is identified and corrected
5. Notify DOT PHMSA if pressure exceeded MAOP for >1 hour (49 CFR 191.5)

---

## 4. Emergency Procedures

### 4.1 Emergency Shutdown (ESD) Procedure
Activate ESD when:
- Confirmed leak with estimated rate >1.0 MMSCFD
- Fire or explosion at any station
- Pressure exceeds design pressure (900 psi)
- Loss of SCADA communication for >30 minutes with no field confirmation of normal operations

ESD steps:
1. Activate ESD from SCADA console (closes all remotely operable valves simultaneously)
2. Shut down all compressors
3. Call 911 if fire, explosion, or injury
4. Notify DOT PHMSA National Response Center: **1-800-424-8802**
5. Notify company emergency response team
6. Establish 300-foot exclusion zone around suspected leak location
7. Do not re-energize system until authorized by pipeline integrity engineer

### 4.2 Fire or Explosion at Station
1. Evacuate all personnel from station
2. Call 911 immediately
3. Activate ESD from remote SCADA console
4. Do not attempt to fight gas fire — let it burn until gas supply is isolated
5. Notify DOT PHMSA NRC: 1-800-424-8802 (within 1 hour per 49 CFR 191.5)
6. Preserve SCADA data and event logs for incident investigation

### 4.3 Loss of SCADA Communication
1. Dispatch field operators to all stations within 30 minutes
2. Field operators manually read and record pressures and flows every 15 minutes
3. Operate valves manually if needed
4. Restore SCADA communication within 2 hours or activate contingency operating plan
5. Do not increase throughput above 80% of normal until SCADA is restored

---

## 5. Pressure Transient Reference

### 5.1 Normal Transient Signatures (False Positive Patterns)

| Event | Pressure Change | Duration | Flow Change | How to Distinguish from Leak |
|---|---|---|---|---|
| Compressor start (ST-01) | +15 to +25 psi at ST-01, -5 to -10 psi at ST-02 | 5–15 min | +0.3 to +0.5 MMSCFD | Logged in SCADA; pressure recovers; no sustained deficit |
| Compressor start (ST-04) | +15 to +25 psi at ST-04, -5 to -10 psi at ST-05 | 5–15 min | +0.3 to +0.5 MMSCFD | Logged in SCADA; pressure recovers; no sustained deficit |
| Valve position change | ±8 to ±15 psi across segment | 8–20 min | ±0.1 to ±0.3 MMSCFD | Logged in SCADA; pressure re-equilibrates; no sustained deficit |
| Temperature drop 10°F overnight | -5 to -12 psi across all segments | 4–8 hours | -0.15 to -0.25 MMSCFD apparent | Affects all segments equally; correlates with temperature data; no localized pressure gradient |
| Demand surge at ST-08 | -10 to -20 psi propagating upstream | 15–30 min | +0.2 to +0.4 MMSCFD | Originates at delivery point; pressure recovers after demand normalizes |

### 5.2 Real Leak Signatures

| Severity | Leak Rate | Pressure Drop | Mass Balance Deficit | Localization |
|---|---|---|---|---|
| Seep | <0.2 MMSCFD | 3–8 psi over 30 min | 0.1–0.2 MMSCFD | Localized to one segment |
| Moderate | 0.2–0.8 MMSCFD | 8–20 psi over 15 min | 0.2–0.8 MMSCFD | Clear segment isolation |
| Significant | 0.8–2.0 MMSCFD | 20–50 psi over 10 min | 0.8–2.0 MMSCFD | Rapid localization possible |
| Near-rupture | >2.0 MMSCFD | >50 psi in <5 min | >2.0 MMSCFD | Immediate ESD required |

Key distinguishing features of real leaks vs. false positives:
- Localized pressure gradient (one segment affected, not all)
- Sustained mass balance deficit (does not recover after 20 minutes)
- No corresponding SCADA event (no compressor start or valve change logged)
- Not correlated with temperature change
