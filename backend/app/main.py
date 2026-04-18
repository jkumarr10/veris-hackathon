import logging
import json
import asyncio
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.models import (
    GeocodeRequest,
    GeocodeResult,
    RunDecisionByAddressRequest,
    RunDecisionByAddressResponse,
    RunDecisionRequest,
    RunDecisionResponse,
)
from app.orchestrator import (
    geocode_address,
    run_decision_loop,
    run_decision_loop_by_address,
    run_decision_loop_by_address_with_events,
)

app = FastAPI(title="Solar Soiling & Yield Optimizer", version="0.1.0")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/decision/run", response_model=RunDecisionResponse)
async def run_decision(payload: RunDecisionRequest) -> RunDecisionResponse:
    try:
        return await run_decision_loop(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/geocode", response_model=GeocodeResult)
async def geocode(payload: GeocodeRequest) -> GeocodeResult:
    try:
        return await geocode_address(payload.address)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/decision/run-by-address", response_model=RunDecisionByAddressResponse)
async def run_decision_by_address(
    payload: RunDecisionByAddressRequest,
) -> RunDecisionByAddressResponse:
    try:
        return await run_decision_loop_by_address(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@app.post("/decision/run-by-address/stream")
async def run_decision_by_address_stream(payload: RunDecisionByAddressRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def emit(event_payload: dict) -> None:
            await queue.put(event_payload)

        async def worker() -> None:
            try:
                result = await run_decision_loop_by_address_with_events(payload, event_callback=emit)
                await queue.put({"type": "final", "result": result.model_dump()})
            except Exception as exc:
                await queue.put({"type": "error", "message": str(exc)})
            finally:
                await queue.put({"type": "_done"})

        task = asyncio.create_task(worker())
        try:
            while True:
                event_payload = await queue.get()
                event_type = str(event_payload.get("type", "message"))
                if event_type == "_done":
                    break
                yield _sse(event_type, event_payload)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
