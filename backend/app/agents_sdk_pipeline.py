import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agents import set_tracing_disabled
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from app.agents.environment_agent import EnvironmentalAgent
from app.agents.manager_agent import DecisionManagerAgent
from app.agents.yield_agent import YieldAnalyzerAgent
from app.config import settings
from app.models import EnvironmentReport, ManagerDecision, YieldReport

set_tracing_disabled(True)
logger = logging.getLogger(__name__)
PipelineEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class AgentsSDKOrchestrator:
    def __init__(self) -> None:
        self.model = self._build_model()

    async def run(
        self,
        latitude: float,
        longitude: float,
        panel_csv_path: str,
        cleaning_cost_usd: float,
        lookahead_days: int,
        energy_price_per_kwh: float,
        use_llm_manager: bool,
        event_callback: PipelineEventCallback | None = None,
    ) -> tuple[EnvironmentReport, YieldReport, ManagerDecision]:
        return await self._run_pipeline(
            latitude=latitude,
            longitude=longitude,
            panel_csv_path=panel_csv_path,
            cleaning_cost_usd=cleaning_cost_usd,
            lookahead_days=lookahead_days,
            energy_price_per_kwh=energy_price_per_kwh,
            use_llm_manager=use_llm_manager,
            event_callback=event_callback,
        )

    def _build_model(self) -> OpenAIChatCompletionsModel | str | None:
        if settings.baseten_api_key and settings.baseten_model:
            baseten_client = AsyncOpenAI(
                api_key=settings.baseten_api_key,
                base_url=settings.baseten_base_url,
            )
            return OpenAIChatCompletionsModel(
                model=settings.baseten_model,
                openai_client=baseten_client,
            )

        if settings.openai_api_key:
            return settings.openai_model

        return None

    async def _run_pipeline(
        self,
        latitude: float,
        longitude: float,
        panel_csv_path: str,
        cleaning_cost_usd: float,
        lookahead_days: int,
        energy_price_per_kwh: float,
        use_llm_manager: bool,
        event_callback: PipelineEventCallback | None = None,
    ) -> tuple[EnvironmentReport, YieldReport, ManagerDecision]:
        environment_worker = EnvironmentalAgent()
        yield_worker = YieldAnalyzerAgent()
        manager = DecisionManagerAgent(model=self.model, max_iterations=2)

        if event_callback:
            await event_callback({"type": "status", "step": "environment", "message": "Fetching environment data."})
        environment = await environment_worker.run(latitude, longitude, lookahead_days)
        if event_callback:
            await event_callback({"type": "environment_done", "environment": environment.model_dump()})

        if event_callback:
            await event_callback({"type": "status", "step": "yield", "message": "Analyzing plant yield data."})
        yield_report = yield_worker.run(panel_csv_path, energy_price_per_kwh)
        if event_callback:
            await event_callback({"type": "yield_done", "yield_report": yield_report.model_dump()})

        if event_callback:
            await event_callback(
                {
                    "type": "status",
                    "step": "manager",
                    "message": "Manager agent is planning and deciding.",
                }
            )
        manager_decision = await manager.run(
            environment=environment,
            yield_report=yield_report,
            cleaning_cost_usd=cleaning_cost_usd,
            lookahead_days=environment.lookahead_days,
            use_agentic_loop=use_llm_manager,
            event_callback=event_callback,
        )

        logger.info(
            "AgentsSDKOrchestrator deterministic manager math inputs: %s",
            {
                "estimated_daily_loss_usd": yield_report.estimated_daily_loss_usd,
                "lookahead_days": environment.lookahead_days,
                "cleaning_cost_usd": cleaning_cost_usd,
                "avg_soiling_loss_pct": yield_report.avg_soiling_loss_pct,
                "projected_loss_without_cleaning_usd": round(
                    yield_report.estimated_daily_loss_usd * environment.lookahead_days, 2
                ),
                "projected_gain_if_cleaned_usd": manager_decision.projected_gain_usd,
                "rain_in_next_7_days": environment.rain_in_next_7_days,
                "rainy_days_next_7_days": environment.rainy_days_next_7_days,
                "rain_in_prev_7_days": environment.rain_in_prev_7_days,
                "rainy_days_prev_7_days": environment.rainy_days_prev_7_days,
                "pm25": environment.pm25,
                "sun_hours_next_n_days": environment.sun_hours_next_n_days,
            },
        )

        return environment, yield_report, manager_decision
