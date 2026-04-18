import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents_sdk_pipeline import AgentsSDKOrchestrator
from app.clients.geocoding import GeocodingClient
from app.config import settings
from app.models import (
    GeocodeResult,
    RunDecisionByAddressRequest,
    RunDecisionByAddressResponse,
    RunDecisionRequest,
    RunDecisionResponse,
)

logger = logging.getLogger(__name__)
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def run_decision_loop(req: RunDecisionRequest) -> RunDecisionResponse:
    latitude = req.latitude
    longitude = req.longitude
    panel_csv_path = req.panel_csv_path or settings.default_panel_csv
    cleaning_cost_usd = (
        req.cleaning_cost_usd if req.cleaning_cost_usd is not None else settings.default_cleaning_cost_usd
    )
    lookahead_days = req.lookahead_days or settings.default_lookahead_days
    energy_price_per_kwh = req.energy_price_per_kwh or settings.default_energy_price_per_kwh

    orchestrator = AgentsSDKOrchestrator()

    logger.info(
        "Orchestrator inputs: %s",
        {
            "latitude": latitude,
            "longitude": longitude,
            "panel_csv_path": panel_csv_path,
            "cleaning_cost_usd": cleaning_cost_usd,
            "lookahead_days": lookahead_days,
            "energy_price_per_kwh": energy_price_per_kwh,
            "use_llm_manager": req.use_llm_manager,
        },
    )

    environment, yield_report, manager_decision = await orchestrator.run(
        latitude=latitude,
        longitude=longitude,
        panel_csv_path=panel_csv_path,
        cleaning_cost_usd=cleaning_cost_usd,
        lookahead_days=lookahead_days,
        energy_price_per_kwh=energy_price_per_kwh,
        use_llm_manager=req.use_llm_manager,
    )
    return RunDecisionResponse(
        environment=environment,
        yield_report=yield_report,
        manager_decision=manager_decision,
        data_sources=[
            "Open-Meteo forecast API (weather, irradiance, rain probability)",
            "Open-Meteo air-quality API (PM2.5, PM10)",
            "Open-Meteo archive API (past 10-day rainfall)",
            f"Panel CSV: {panel_csv_path}",
        ],
        assumptions=[
            "Panel expected vs actual kWh deltas approximate soiling-related loss.",
            f"Energy price is set to ${energy_price_per_kwh}/kWh (input or backend default).",
            f"Cleaning cost is set to ${cleaning_cost_usd} (input or backend default).",
            "Recent rain and near-term rain can reduce cleaning urgency via manager penalties.",
        ],
    )


async def run_decision_loop_with_events(
    req: RunDecisionRequest,
    event_callback: EventCallback | None = None,
) -> RunDecisionResponse:
    latitude = req.latitude
    longitude = req.longitude
    panel_csv_path = req.panel_csv_path or settings.default_panel_csv
    cleaning_cost_usd = (
        req.cleaning_cost_usd if req.cleaning_cost_usd is not None else settings.default_cleaning_cost_usd
    )
    lookahead_days = req.lookahead_days or settings.default_lookahead_days
    energy_price_per_kwh = req.energy_price_per_kwh or settings.default_energy_price_per_kwh

    orchestrator = AgentsSDKOrchestrator()
    environment, yield_report, manager_decision = await orchestrator.run(
        latitude=latitude,
        longitude=longitude,
        panel_csv_path=panel_csv_path,
        cleaning_cost_usd=cleaning_cost_usd,
        lookahead_days=lookahead_days,
        energy_price_per_kwh=energy_price_per_kwh,
        use_llm_manager=req.use_llm_manager,
        event_callback=event_callback,
    )
    return RunDecisionResponse(
        environment=environment,
        yield_report=yield_report,
        manager_decision=manager_decision,
        data_sources=[
            "Open-Meteo forecast API (weather, irradiance, rain probability)",
            "Open-Meteo air-quality API (PM2.5, PM10)",
            "Open-Meteo archive API (past 10-day rainfall)",
            f"Panel CSV: {panel_csv_path}",
        ],
        assumptions=[
            "Panel expected vs actual kWh deltas approximate soiling-related loss.",
            f"Energy price is set to ${energy_price_per_kwh}/kWh (input or backend default).",
            f"Cleaning cost is set to ${cleaning_cost_usd} (input or backend default).",
            "Recent rain and near-term rain can reduce cleaning urgency via manager penalties.",
        ],
    )


async def geocode_address(address: str) -> GeocodeResult:
    return await GeocodingClient().geocode_address(address)


async def run_decision_loop_by_address(
    req: RunDecisionByAddressRequest,
) -> RunDecisionByAddressResponse:
    resolved = await geocode_address(req.address)
    core_req = RunDecisionRequest(
        latitude=resolved.latitude,
        longitude=resolved.longitude,
        panel_csv_path=req.panel_csv_path,
        cleaning_cost_usd=req.cleaning_cost_usd,
        lookahead_days=req.lookahead_days,
        energy_price_per_kwh=req.energy_price_per_kwh,
        use_llm_manager=req.use_llm_manager,
    )
    result = await run_decision_loop(core_req)
    return RunDecisionByAddressResponse(
        input_address=req.address,
        resolved_location=resolved,
        environment=result.environment,
        yield_report=result.yield_report,
        manager_decision=result.manager_decision,
        data_sources=result.data_sources,
        assumptions=result.assumptions,
    )


async def run_decision_loop_by_address_with_events(
    req: RunDecisionByAddressRequest,
    event_callback: EventCallback | None = None,
) -> RunDecisionByAddressResponse:
    if event_callback:
        await event_callback({"type": "status", "step": "geocoding", "message": "Resolving farm address."})

    resolved = await geocode_address(req.address)
    if event_callback:
        await event_callback({"type": "geocode_done", "resolved_location": resolved.model_dump()})

    core_req = RunDecisionRequest(
        latitude=resolved.latitude,
        longitude=resolved.longitude,
        panel_csv_path=req.panel_csv_path,
        cleaning_cost_usd=req.cleaning_cost_usd,
        lookahead_days=req.lookahead_days,
        energy_price_per_kwh=req.energy_price_per_kwh,
        use_llm_manager=req.use_llm_manager,
    )
    result = await run_decision_loop_with_events(core_req, event_callback=event_callback)
    return RunDecisionByAddressResponse(
        input_address=req.address,
        resolved_location=resolved,
        environment=result.environment,
        yield_report=result.yield_report,
        manager_decision=result.manager_decision,
        data_sources=result.data_sources,
        assumptions=result.assumptions,
    )
