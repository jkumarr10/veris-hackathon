# Solar Soiling Optimizer: APIs, Workers, and Formulas

This document describes:
- External APIs used
- What each API returns (fields we consume)
- Each worker/node input and output
- Core calculations and formulas (especially Yield + Manager)

## 1) External APIs Used

## A) Open-Meteo Forecast API
- Endpoint: `https://api.open-meteo.com/v1/forecast`
- Used by: `OpenMeteoClient.fetch_environment_report(...)`
- Request inputs:
  - `latitude`
  - `longitude`
  - `daily=sunshine_duration,shortwave_radiation_sum,precipitation_probability_max,precipitation_sum`
  - `hourly=relative_humidity_2m,wind_speed_10m,wind_direction_10m`
  - `forecast_days` (clamped to 1..14 here)
  - `timezone=auto`
- Output fields consumed:
  - `daily.sunshine_duration`
  - `daily.shortwave_radiation_sum`
  - `daily.precipitation_probability_max`
  - `daily.precipitation_sum`
  - `hourly.time`
  - `hourly.relative_humidity_2m`
  - `hourly.wind_speed_10m`
  - `hourly.wind_direction_10m`

## B) Open-Meteo Air Quality API
- Endpoint: `https://air-quality-api.open-meteo.com/v1/air-quality`
- Used by: `OpenMeteoClient.fetch_environment_report(...)`
- Request inputs:
  - `latitude`
  - `longitude`
  - `hourly=pm2_5,pm10`
  - `forecast_days` (tries requested up to 7, then fallback to 3, then provider default)
  - `timezone=auto`
- Output fields consumed:
  - `hourly.time`
  - `hourly.pm2_5`
  - `hourly.pm10`

## C) Open-Meteo Archive API (Past Rain)
- Endpoint: `https://archive-api.open-meteo.com/v1/archive`
- Used by: `OpenMeteoClient._fetch_past_rain_7_days(...)`
- Request inputs:
  - `latitude`
  - `longitude`
  - `start_date` = (yesterday - 6 days)
  - `end_date` = yesterday
  - `daily=precipitation_sum`
  - `timezone=auto`
- Output fields consumed:
  - `daily.precipitation_sum`

## D) Open-Meteo Geocoding API
- Endpoint: `https://geocoding-api.open-meteo.com/v1/search`
- Used by: `GeocodingClient._try_open_meteo(...)`
- Request inputs:
  - `name=<address query>`
  - `count=1`
  - `language=en`
  - `format=json`
- Output fields consumed:
  - `results[0].name`
  - `results[0].latitude`
  - `results[0].longitude`
  - `results[0].country`
  - `results[0].admin1`
  - `results[0].timezone`

## E) Nominatim (OpenStreetMap) Geocoding Fallback
- Endpoint: `https://nominatim.openstreetmap.org/search`
- Used by: `GeocodingClient._try_nominatim(...)` when Open-Meteo geocoding has no match
- Request inputs:
  - `q=<address query>`
  - `format=jsonv2`
  - `limit=1`
  - `addressdetails=1`
- Output fields consumed:
  - `[0].display_name`
  - `[0].lat`
  - `[0].lon`
  - `[0].address.country`
  - `[0].address.state`

## F) Baseten OpenAI-compatible Chat Completions
- Base URL: `https://inference.baseten.co/v1`
- Used by: Manager agent in `DecisionManagerAgent._propose_decision(...)` via OpenAI Agents SDK
- Purpose:
  - Generates candidate JSON decision:
    - `decision` in `{deploy_crew, wait_and_monitor, alert_only}`
    - `reasoning` text
- Also used for streaming token deltas in manager iterations.

## 2) Data Processing Workers / Nodes

## A) Geocoding Node (`GeocodingClient`)
- Input:
  - `address` (string)
- Output (`GeocodeResult`):
  - `address_input`
  - `name`
  - `latitude`
  - `longitude`
  - `country`
  - `admin1`
  - `timezone`
- Logic:
  - Try Open-Meteo geocoder with multiple query variants
  - If no match, fallback to Nominatim with same variants

## B) Environmental Worker (`EnvironmentalAgent` + `OpenMeteoClient`)
- Input:
  - `latitude`
  - `longitude`
  - `lookahead_days`
- Output (`EnvironmentReport`):
  - `latitude`, `longitude`
  - `pm25`, `pm10` (today average from hourly)
  - `humidity_pct` (today average from hourly)
  - `wind_speed_kmh` (today average from hourly)
  - `wind_direction_deg` (today average from hourly)
  - `rain_in_next_7_days`
  - `rainy_days_next_7_days`
  - `total_precipitation_next_7_days_mm`
  - `rain_in_prev_7_days`
  - `rainy_days_prev_7_days`
  - `total_precipitation_prev_7_days_mm`
  - `sun_hours_next_n_days`
  - `avg_shortwave_radiation_wm2_next_n_days`
  - `lookahead_days`

### Environmental formulas
- `sun_hours_next_n_days = sum(daily.sunshine_duration[0:lookahead_days]) / 3600`
- `avg_shortwave_radiation_wm2_next_n_days = mean(daily.shortwave_radiation_sum[0:lookahead_days])`
- `rain_in_next_7_days = any(precip_probability_max >= 50) OR any(precipitation_sum >= 1.0 mm)`
- `rainy_days_next_7_days = count of days where (probability >= 50 OR precipitation_sum >= 1.0 mm)`
- `total_precipitation_next_7_days_mm = sum(precipitation_sum[0:7])`
- `rainy_days_prev_7_days = count(daily precipitation_sum >= 1.0 mm)`
- `rain_in_prev_7_days = rainy_days_prev_7_days > 0`
- `total_precipitation_prev_7_days_mm = sum(past 7-day precipitation_sum)`
- For PM/humidity/wind:
  - Take hourly values for current local day only and compute mean.

## C) Yield Worker (`YieldAnalyzerAgent`)
- Input:
  - `panel_csv_path`
  - `energy_price_per_kwh`
- Output (`YieldReport`):
  - `panel_count`
  - `avg_soiling_loss_pct`
  - `worst_zone`
  - `zone_loss_pct`
  - `estimated_daily_loss_usd`
  - `estimated_daily_lost_kwh`
  - `estimated_plant_capacity_mw`

The worker supports 2 schemas:

### Schema 1: Panel schema
- Required columns:
  - `panel_id, zone, expected_kwh, actual_kwh`

### Panel-schema formulas
- `lost_kwh = max(expected_kwh - actual_kwh, 0)`
- `total_expected = sum(expected_kwh)`
- `total_lost = sum(lost_kwh)`
- Per zone:
  - `zone_loss_pct = (sum(zone_lost_kwh) / sum(zone_expected_kwh)) * 100`
- `worst_zone = zone with max(zone_loss_pct)`
- `avg_soiling_loss_pct = (total_lost / total_expected) * 100`
- `estimated_daily_lost_kwh = total_lost`
- `estimated_daily_loss_usd = total_lost * energy_price_per_kwh`
- `estimated_plant_capacity_mw = null` (not inferable from this schema alone)

### Schema 2: Kaggle generation schema
- Required generation columns:
  - `DATE_TIME, PLANT_ID, SOURCE_KEY, AC_POWER`
- Paired weather file required (inferred from filename):
  - `DATE_TIME, PLANT_ID, IRRADIATION`

### Kaggle-schema formulas (main calculations)
1. Datetime parse + clean:
   - Parse `DATE_TIME` for generation and weather
   - Drop invalid rows
2. Align weather and generation:
   - Weather grouped by (`DATE_TIME`, `PLANT_ID`) mean `IRRADIATION`
   - Merge with generation on (`DATE_TIME`, `PLANT_ID`)
3. Interval duration:
   - `interval_hours = diff(DATE_TIME by SOURCE_KEY) in hours`
   - Fill first row with `0.25`
   - Clamp to `[0.05, 1.0]`
4. Expected power model:
   - `max_irr = max(IRRADIATION)`
   - `peak_ac_by_source = max(AC_POWER per SOURCE_KEY)`
   - `performance_ratio = 0.9` (fixed constant)
   - `expected_power_kw = peak_ac_by_source * (IRRADIATION / max_irr) * performance_ratio`
5. Energy conversion:
   - `actual_kwh = AC_POWER * interval_hours`
   - `expected_kwh = expected_power_kw * interval_hours`
6. Loss:
   - `lost_kwh = max(expected_kwh - actual_kwh, 0)`
7. Zone mapping (deterministic demo grouping):
   - Each `SOURCE_KEY` mapped to one of `Block A/B/C/D` by hash-like char sum modulo 4
8. Aggregate outputs:
   - `total_expected = sum(expected_kwh)`
   - `total_lost = sum(lost_kwh)`
   - `avg_soiling_loss_pct = (total_lost / total_expected) * 100`
   - Per-zone `loss_pct = (sum(zone_lost_kwh) / sum(zone_expected_kwh)) * 100`
   - `worst_zone = max(zone_loss_pct)`
   - `estimated_daily_lost_kwh = total_lost`
   - `estimated_daily_loss_usd = total_lost * energy_price_per_kwh`
   - `panel_count = number of unique SOURCE_KEY`
   - `estimated_plant_capacity_mw = sum(max AC_POWER per SOURCE_KEY) / 1000`

## D) Data Manager Node / Decision Manager (`DecisionManagerAgent`)
- Input:
  - `EnvironmentReport`
  - `YieldReport`
  - `cleaning_cost_usd`
  - `lookahead_days`
  - `use_agentic_loop`
- Output (`ManagerDecision`):
  - `decision` (`deploy_crew | wait_and_monitor | alert_only`)
  - `reasoning`
  - `gain_horizon_days` (fixed to 30)
  - `projected_loss_without_cleaning_usd`
  - `projected_gain_usd`
  - `clean_cost_usd`
  - `roi_ratio`
  - `break_even_days`

### Manager metric formulas
- `sun_ref_hours = max(lookahead_days * 6.0, 1.0)`
- `sun_factor = sun_hours_next_n_days / sun_ref_hours`
- `pm_factor =`
  - `1.15` if `pm25 >= 45`
  - `1.08` if `25 <= pm25 < 45`
  - `0.98` if `pm25 < 25`
- `sun_boost = clamp(sun_factor * pm_factor, 0.7, 1.35)`
- `recent_rain_penalty = 0.85 if rain_in_prev_7_days else 1.0`
- `rain_penalty = 0.75 if rain_in_next_7_days else 1.0`
- `projected_loss_without_cleaning_usd = estimated_daily_loss_usd * lookahead_days`
- `projected_gain_usd = estimated_daily_loss_usd * 30 * sun_boost * rain_penalty * recent_rain_penalty`
- `roi_ratio = projected_gain_usd / cleaning_cost_usd` (if cleaning_cost_usd > 0 else 0)
- `break_even_days = cleaning_cost_usd / estimated_daily_loss_usd` (if estimated_daily_loss_usd > 0 else null)

### Manager decision policy (validator / deterministic baseline)
- `SOILING_ALERT_THRESHOLD_PCT = 12.0`
- `DEPLOY_ROI_THRESHOLD = 0.9` (30-day gain horizon)
- `ALERT_ROI_THRESHOLD = 0.75`
- `RAIN_DEPLOY_ROI_THRESHOLD = 1.0`
- Rules:
  - If `avg_soiling_loss_pct < 12.0` -> `wait_and_monitor`
  - Else if `rain_in_next_7_days` and `roi_ratio < 1.0` -> `wait_and_monitor`
  - Else if `roi_ratio >= 0.9` and `net_gain_usd >= 0` -> `deploy_crew`
  - Else if `0.75 <= roi_ratio < 0.9` -> `alert_only`
  - Else -> `wait_and_monitor`

### Agentic loop behavior
- Max iterations: `2`
- Iteration 1 phase: `plan`
- Iteration 2 phase: `action`
- For each iteration:
  - LLM proposes `decision + reasoning` JSON
  - Candidate is validated against deterministic policy
  - If invalid, feedback is sent to next iteration
- If final candidate still conflicts, code corrects decision to policy-expected class.

## 3) Orchestrator Data Flow

`AgentsSDKOrchestrator` sequence:
1. Environmental worker runs
2. Yield worker runs
3. Manager node runs (deterministic or agentic loop)

Final API response includes:
- `environment`
- `yield_report`
- `manager_decision`
- `data_sources`
- `assumptions`

# Formula
## estimated_plant_capacity_mw = sum(max AC_POWER per inverter SOURCE_KEY) / 1000
