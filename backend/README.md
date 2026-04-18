# Solar Soiling & Yield Optimizer

FastAPI multi-agent MVP for hackathon demos, orchestrated with the **OpenAI Agents SDK**.

## Architecture
- Data Processing Worker 1(`Environmental Agent`): uses Open-Meteo weather + air-quality data.
- Data Processing Worker 2 (`Yield Analyzer Agent`): analyzes Generation Data CSV from Kaggle.
- Agent (`Decision Manager Agent`): computes ROI decision (`deploy_crew`, `wait_and_monitor`, `alert_only`).

All 3 stages are executed through `agents.Agent` + `agents.Runner` in [`app/agents_sdk_pipeline.py`](app/agents_sdk_pipeline.py).

## Quickstart (uv)
1. Install deps:
   ```bash
   uv sync
   ```
2. (Optional) regenerate synthetic panel data:
   ```bash
   uv run python scripts/generate_synthetic_panels.py --output data/panels.csv
   ```
3. Start API:
   ```bash
   uv run uvicorn app.main:app --reload
   ```

## Frontend (React)
1. Install frontend dependencies:
   ```bash
   cd frontend
   npm install
   ```
2. Start frontend:
   ```bash
   npm run dev
   ```
3. Open the local Vite URL (usually `http://127.0.0.1:5173`).

The UI is prefilled with:
`California Valley Solar Ranch, 13155 Boulder Creek Rd, Santa Margarita, CA 93453`

## Environment Variables
Create `.env` in project root:

```bash
# Preferred: Baseten OpenAI-compatible endpoint
BASETEN_API_KEY=
BASETEN_MODEL=
BASETEN_BASE_URL=https://inference.baseten.co/v1

# Optional direct OpenAI fallback
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini

# Defaults for endpoint
DEFAULT_PANEL_CSV=data/Plant_1_Generation_Data.csv
DEFAULT_CLEANING_COST_USD=5000
DEFAULT_LOOKAHEAD_DAYS=7
DEFAULT_ENERGY_PRICE_PER_KWH=0.11
```

## Main Endpoint
`POST /decision/run`

Example:
```bash
curl -X POST http://127.0.0.1:8000/decision/run \
  -H 'Content-Type: application/json' \
  -d '{
    "latitude": 35.2828,
    "longitude": -120.6596,
    "panel_csv_path": "data/panels.csv",
    "cleaning_cost_usd": 5000,
    "lookahead_days": 7,
    "energy_price_per_kwh": 0.11,
    "use_llm_manager": true
  }'
```

## Panel CSV Schema
Required columns:
- `panel_id`
- `zone`
- `expected_kwh`
- `actual_kwh`

## Address-First Endpoint
`POST /decision/run-by-address`

Example:
```bash
curl -X POST http://127.0.0.1:8000/decision/run-by-address \
  -H 'Content-Type: application/json' \
  -d '{
    "address": "California Valley Solar Ranch, 13155 Boulder Creek Rd, Santa Margarita, CA 93453",
    "cleaning_cost_usd": 5000,
    "lookahead_days": 7,
    "energy_price_per_kwh": 0.11,
    "use_llm_manager": true
  }'
```

## Notes
- If no `BASETEN_API_KEY`/`BASETEN_MODEL` (and no `OPENAI_API_KEY`) is set, the app automatically falls back to deterministic non-LLM decision logic.
- OpenAI Agents SDK tracing is disabled in code for hackathon simplicity.
