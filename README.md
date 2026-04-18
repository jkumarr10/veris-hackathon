# Solar Soiling Detection Agent

Hackathon project with a two-app structure:
- `backend/` FastAPI + OpenAI Agents SDK + uv
- `frontend/` React (Vite)

The app geocodes a solar farm address, fetches live environmental signals, analyzes yield from CSV data, and produces an operational cleaning recommendation.

## What It Does
- Accepts a solar farm address from the frontend.
- Resolves address to coordinates (Open-Meteo geocoding, fallback to Nominatim).
- Pulls weather + air quality + rainfall signals from Open-Meteo.
- Analyzes solar generation/yield data from CSV.
- Runs an agentic manager loop (2 iterations: plan -> action) via Baseten/OpenAI-compatible API.
- Streams manager reasoning tokens and iteration updates to the UI.

## Decision Outputs
Manager returns one of:
- `deploy_crew`
- `wait_and_monitor`
- `alert_only`

And includes:
- projected loss if not cleaned (lookahead horizon)
- projected gain if cleaned (**fixed 30-day horizon**)
- cleaning cost
- ROI ratio

## Project Structure
```text
veris-hackathon/
  backend/
    app/
    data/
    scripts/
    pyproject.toml
    uv.lock
  frontend/
    src/
    package.json
```

## Backend Setup (uv)
```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Backend URL: `http://127.0.0.1:8000`

## Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Frontend URL (usually): `http://127.0.0.1:5173`

## Environment Variables
Create this file at `backend/.env`:

```bash
# Baseten (preferred)
BASETEN_API_KEY=
BASETEN_MODEL=openai/gpt-oss-120b
BASETEN_BASE_URL=https://inference.baseten.co/v1

# Optional OpenAI fallback
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.3

# Backend defaults
DEFAULT_PANEL_CSV=data/Plant_1_Generation_Data.csv
DEFAULT_CLEANING_COST_USD=5000
DEFAULT_LOOKAHEAD_DAYS=7
DEFAULT_ENERGY_PRICE_PER_KWH=0.11
```

## API Endpoints
- `GET /health`
- `POST /geocode`
- `POST /decision/run`
- `POST /decision/run-by-address`
- `POST /decision/run-by-address/stream` (SSE streaming for manager trace)

## Example Request (Address Flow)
```bash
curl -X POST http://127.0.0.1:8000/decision/run-by-address \
  -H "Content-Type: application/json" \
  -d '{
    "address": "California Valley Solar Ranch, 13155 Boulder Creek Rd, Santa Margarita, CA 93453",
    "cleaning_cost_usd": 15000,
    "lookahead_days": 7,
    "energy_price_per_kwh": 0.08,
    "use_llm_manager": true
  }'
```

## Data Sources
- Open-Meteo Forecast API
- Open-Meteo Air Quality API
- Open-Meteo Archive API (past rainfall)
- Open-Meteo Geocoding API
- Nominatim (fallback geocoder)
- Kaggle solar generation + weather CSVs in `backend/data/`

## Notes
- Frontend always sends `use_llm_manager: true` (Baseten manager loop by default).
- If model credentials are missing, backend can still fall back to deterministic manager behavior.
- OpenAI Agents SDK tracing is disabled for hackathon simplicity.

## Additional Documentation
- Detailed formulas, worker inputs/outputs, and API field usage:
  - `backend/AGENT_DATA_FLOW.md`
