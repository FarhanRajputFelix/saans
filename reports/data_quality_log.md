# Data Quality Log: what the data threw at us

The numeric before/after statistics for every cleaning step are in the generated [Data Quality Report](data_quality_report.md). This log records the **findings**: each surprise, the evidence, and what was done about it. They are listed roughly in the order they were found.

## Weather (Open-Meteo / ERA5)

| ID | Finding | Evidence | Fix |
|---|---|---|---|
| W1 | Boundary layer height missing 1 Jan to 30 Jun 2024 in all 5 cities | 21,840 cells; the same hole in every model Open-Meteo serves (`best_match`, `era5`, `era5_seamless`, `ecmwf_ifs`) | Imputed with LightGBM from the 12 complete variables; validated on hidden Jan-Jun 2023 (r = 0.91, MAE 148 m); `blh_imputed` flag |
| W2 | BLH bottoms out at exactly 10 m | 35 hours in Lahore, Nov 2024 | Read as "10 m or less" (a model floor); no change needed for tree models |

## Air quality (OpenAQ)

| ID | Finding | Evidence | Fix |
|---|---|---|---|
| A1 | The US diplomatic-post monitors (the only long reference records) stopped publishing on 4 Mar 2025 | Coverage table: last reading 2025-03-04 in Lahore, Islamabad, Karachi | Design change: train 2020 to Sep 2024, test 2024-25 on reference data, test 2025-26 on low-cost networks |
| A2 | Faisalabad and Multan have no data before June 2025 | Longest sensor history 222 and 229 days (AirGradient) | Used as **unseen cities**: a stricter test of generalisation |
| A3 | "Negative values" were really empty readings | 25,555 nulls, all from reference monitors (their missing-hour marker); zero true negatives | Separate cleaning rules for nulls and negatives |
| A4 | OpenAQ's `percentComplete` is wrong for the Clarity monitor | Clarity reports every 15-20 min (3-4 readings/hour); OpenAQ assumes 12, so every good hour shows 25% | Completeness judged against each sensor's own typical count; this saved Lahore's only reference-quality record after Mar 2025 |
| A5 | Lahore US monitor stuck at 67.0 ug/m3 | 105 consecutive hours, 29 May to 1 Jun 2024 | Stuck-run rule (6+ identical hours) removes it |
| A6 | Islamabad's two reference "monitors" are one monitor published twice (StateAir and AirNow) | 15,925 overlapping hours, 87% identical, r = 0.978 | Averaged into one series |
| A7 | AirGradient's OpenAQ data is already humidity-corrected | Raw mean 36.0 vs reference 34.0; EPA correction would drop it to 18.6 and raise MAE from 9.8 to 15.6 | Correction applied per provider only where a pre-test check shows it helps; it hurts AirGradient and Clarity, so neither is corrected (Hawanama: see A11) |
| A8 | Clarity reads ~32% below the reference monitor | 6,331 overlapping hours: 83.6 vs 122.4 ug/m3 | Not corrected (no reliable formula); see L1 |
| A9 | Sensor dropouts: readings that fall to near zero for one hour in the middle of heavy smog | Found on the deployed dashboard: Lahore showed 0 ug/m3 at 10:00 on 3 Nov 2024 (Clarity reported 0.0 between 374 and 334 while the reference monitor was offline). Dozens of exact-zero city-hours elsewhere | Three rules added in step 3/5: readings below 1 ug/m3 dropped (instrument floor); sensor-level dropout test (1,114 readings) and 1,020 zero readings; a second dropout pass on the combined city series |
| A11 | The humidity correction was applied by default to a network that was never checked, creating a fake 40% drop in Lahore | Found by an external review of the repository: when 56 Hawanama sensors joined Lahore on 19 Nov 2025, the cleaned city PM2.5 fell from about 250 to 149 ug/m3 overnight. Hawanama had no reference overlap before the test seasons, so the old rule ("correct unless a check shows it hurts") corrected it. A diagnosis on Islamabad's reference monitor (test-season hours, used only to confirm, not to set the rule): reference 112, Hawanama raw 90, corrected 47 | Rule changed to "correct only where a pre-test check shows it helps"; no provider qualifies, so none is corrected. The decision is saved (`humidity_correction.json`) and read by the live forecast. Fixing it moved Lahore 2025-26 from -33% to -12.6% skill vs persistence (bias +24.6 to +21.0 ug/m3); the rest of that weakness is L1 |
| A10 | NO2 does not exist in OpenAQ near the five cities; PM10 barely does | Coverage table: 0 NO2 sensors, 5 PM10 sensors (2 Clarity, 3 short-lived AirGradient) | PM10 downloaded (5,904 hours), cleaned and added to the master table as context; NO2 reported as unavailable |

## Fires (NASA FIRMS)

| ID | Finding | Evidence | Fix |
|---|---|---|---|
| F1 | Industrial heat sources and offshore flares in the fire data | NASA `type` 2 and 3: 36,311 detections | Kept only `type = 0` (vegetation fires) |
| F2 | The same fire is seen by several satellite passes | 139,394 fires seen by more than one pass | One fire per ~1 km cell, day and day/night pass (strongest FRP kept) |
| F3 | FIRMS answers "Invalid MAP_KEY" when the 5,000-per-10-minutes quota is used up | Key status read 4,886/5,000 at the time of the error | Downloader waits and retries instead of stopping |
| F5 | One month of VIIRS (Aug 2023, 1,019 detections) finished downloading after the fire table was first built | Raw file on disk, absent from the first `firms_fires.parquet` (1,184,817 rows) | Fixed in the re-evaluation: table rebuilt (1,185,836 detections) and the whole pipeline re-run |
| F6 | NASA FIRMS stopped accepting connections from the development machine on 24 Oct 2026, after the archive downloads | Connection timeouts on every FIRMS URL while other NASA sites answered | The live forecast reports "no fresh fire data" on screen instead of silently assuming no fires; the deployed app runs from a different network |
| F4 | VIIRS on NOAA-20 was ~3x slower to download (an estimated 5 hours) | 7 months in 30 minutes | Dropped; VIIRS S-NPP + MODIS kept (as in the proposal). A partial year would have biased the fire index |

## News and LLM

| ID | Finding | Evidence | Fix |
|---|---|---|---|
| N1 | GDELT throttles hard | Repeated HTTP 429 even at one request per 10 s | Fewer, wider windows (Oct-Nov, Dec-Jan per season) |
| N2 | Gemini free tier: `gemini-2.5-flash` closed to new keys; `gemini-3.5-flash` allows 20 requests a day | HTTP 404 and 429 "per day" messages | Client walks a chain: gemini-3.5-flash-lite, gemini-3.1-flash-lite, Groq `gpt-oss-120b`; every answer cached |
| N3 | The API key appeared in an error message (sent in the URL) | Seen once in local notebook output, never committed | Key moved to a request header |
| N4 | LLM event extraction was 65% fully correct on a random 20 (first prompt) | Misses: inverted meaning ("lift lockdown", "schools reopen"), inferred place, non-smog items | Each error type became a prompt rule; re-checked on a larger random 50: 76% (95% interval 64-88%). Remaining errors: future dates read as the publication day, new school timings read as closures, fireworks bans read as fireworks nights. Event flags are yes/no; the first 20 verdicts kept in `event_extraction_check_v1.csv` |

## Modelling

| ID | Finding | Evidence | Fix |
|---|---|---|---|
| L1 | Lahore 2025-26 forecasts run high | Mean bias +21 ug/m3 (skill -12.6%) when Lahore's data come only from low-cost networks (A1, A8); on the reference monitor in 2024-25 the bias was -1.7. A cleaning bug first made it look worse (A11) | Reported as a limitation: losing a reference monitor degrades forecasts. Recalibration on the new networks is future work |
| L3 | The what-if on fires was not always monotonic | Multan 2025-26: removing 100% of fires raised one forecast by 5 ug/m3. Tree models do not enforce "more fire, more smoke" | Fixed: LightGBM monotone constraints on the three fire features (the quantile band models cannot take constraints) |
| L4 | The first dashboard only replayed past seasons: no forecast for today | User review of the deployed app | Live mode built (`saans/live.py`, notebook 07): fetches the last 4 days of sensors, weather and fires, cleans them with the same rules, forecasts the next 24/48 h. A parity check shows live features equal training features exactly (0.0 difference on 266,760 rows x 44 features) |
| L5 | Live mode differs from training in two inputs | Weather comes from the Open-Meteo forecast model instead of ERA5; the news event calendar is not updated live | Stated on the dashboard; event features are zero in live runs |
| L2 | Predicting PM2.5 levels directly clipped the record days | 6 Nov 2024: forecast 283 vs observed 510 | Models predict the change from the last 24 h instead; same day now 392, overall skill vs persistence up from 6% to 13.7% (2024-25, 24 h) |
| L6 | Do the fire features add skill? (asked by an external review, since SHAP gives fires a small share) | Ablation, same model without the three fire features: 2024-25 MAE 28.28 with vs 28.22 without; 2025-26 25.13 vs 27.11 (-7%) | Kept. Reported as found: fires help in one test season of two. SHAP: fires 3.7% of the whole forecast, 10.5% of the predicted change |
| L7 | The hazard warning raises more false alarms than persistence | False alarm rate 9.5% vs 5.3% (2024-25), 15.0% vs 8.0% (2025-26), for a hit rate of 92% vs 75% | Deliberate: threshold 0.30 chosen on the 2023-24 validation season (chart `hazard_threshold_choice.png`), since a missed hazardous day costs more than a false alarm; 96% of false-alarm days were still Very Unhealthy (median 197 ug/m3) |
| L8 | The AQI number and its category could disagree at a boundary | 55.46 ug/m3 is AQI 150 (EPA truncates to one decimal) but was labelled "Unhealthy" (151+). Seen on Islamabad's live forecast, 25 Oct 2026; 2 of 930 daily forecasts affected | `category()` truncates the same way as the AQI; notebooks 05-07 re-run |
