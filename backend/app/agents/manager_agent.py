import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from agents import Agent, ModelSettings, Runner
from agents.stream_events import RawResponsesStreamEvent
from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent

from app.models import EnvironmentReport, ManagerDecision, YieldReport

logger = logging.getLogger(__name__)
SOILING_ALERT_THRESHOLD_PCT = 12.0
GAIN_HORIZON_DAYS = 30
ManagerEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class DecisionManagerAgent:
    def __init__(self, model: Any | None = None, max_iterations: int = 2) -> None:
        self.model = model
        self.max_iterations = max_iterations

    async def run(
        self,
        environment: EnvironmentReport,
        yield_report: YieldReport,
        cleaning_cost_usd: float,
        lookahead_days: int,
        use_agentic_loop: bool = True,
        event_callback: ManagerEventCallback | None = None,
    ) -> ManagerDecision:
        metrics = self._compute_metrics(
            environment=environment,
            yield_report=yield_report,
            cleaning_cost_usd=cleaning_cost_usd,
            lookahead_days=lookahead_days,
        )

        if use_agentic_loop and self.model:
            decision = await self._run_agentic_loop(environment, metrics, event_callback=event_callback)
            logger.info("DecisionManagerAgent (agentic loop) output: %s", decision.model_dump())
            return decision

        decision = self._deterministic_decision(environment, metrics)
        logger.info("DecisionManagerAgent (deterministic) output: %s", decision.model_dump())
        return decision

    async def _run_agentic_loop(
        self,
        environment: EnvironmentReport,
        metrics: dict[str, float | None],
        event_callback: ManagerEventCallback | None = None,
    ) -> ManagerDecision:
        feedback = ""
        final_candidate: dict[str, str] | None = None
        for i in range(1, self.max_iterations + 1):
            phase = "plan" if i == 1 else "action"
            if event_callback:
                await event_callback(
                    {
                        "type": "iteration_start",
                        "iteration": i,
                        "phase": phase,
                        "message": (
                            "Drafting an operational plan from metrics."
                            if i == 1
                            else "Finalizing recommendation and action."
                        ),
                    }
                )

            candidate = await self._propose_decision(
                metrics=metrics,
                feedback=feedback,
                iteration=i,
                phase=phase,
                event_callback=event_callback,
            )
            valid, critique, expected = self._validate_candidate(candidate["decision"], environment, metrics)

            logger.info(
                "DecisionManagerAgent loop iteration=%s candidate=%s valid=%s critique=%s",
                i,
                candidate,
                valid,
                critique,
            )

            final_candidate = candidate
            if event_callback:
                await event_callback(
                    {
                        "type": "iteration_done",
                        "iteration": i,
                        "phase": phase,
                        "candidate": candidate,
                        "valid": valid,
                        "critique": critique,
                        "expected_decision": expected,
                    }
                )

            if i == self.max_iterations and valid:
                return self._build_manager_decision(candidate, metrics)

            feedback = (
                f"Your previous decision was invalid. Policy critique: {critique}. "
                f"Expected decision class: {expected}. Revise your decision and keep JSON format."
            )

            if i == 1:
                feedback += " In iteration 2, provide the final action recommendation."

        if final_candidate:
            _, _, expected = self._validate_candidate(
                final_candidate["decision"],
                environment,
                metrics,
            )
            final_candidate["decision"] = expected
            final_candidate["reasoning"] = (
                f"{final_candidate['reasoning']} Final action is corrected to {expected} to satisfy policy."
            )
            return self._build_manager_decision(final_candidate, metrics)

        deterministic = self._deterministic_decision(environment, metrics)
        deterministic.reasoning = (
            f"Agentic loop fell back to deterministic policy after {self.max_iterations} iterations. "
            f"{deterministic.reasoning}"
        )
        return deterministic

    async def _propose_decision(
        self,
        metrics: dict[str, float | None],
        feedback: str,
        iteration: int,
        phase: str,
        event_callback: ManagerEventCallback | None = None,
    ) -> dict[str, str]:
        llm_metrics = {
            "lookahead_days": metrics.get("lookahead_days"),
            "gain_horizon_days": metrics.get("gain_horizon_days"),
            "projected_loss_without_cleaning_usd": metrics.get("projected_loss_without_cleaning_usd"),
            "projected_gain_usd": metrics.get("projected_gain_usd"),
            "clean_cost_usd": metrics.get("clean_cost_usd"),
            "roi_ratio": metrics.get("roi_ratio"),
            "avg_soiling_loss_pct": metrics.get("avg_soiling_loss_pct"),
            "rain_penalty": metrics.get("rain_penalty"),
            "recent_rain_penalty": metrics.get("recent_rain_penalty"),
        }

        decision_agent = Agent(
            name="Decision Manager Agent",
            instructions=(
                "You are an agentic solar-operations manager running a bounded decision loop.\n"
                "Your role is to choose exactly one action: deploy_crew, wait_and_monitor, or alert_only.\n"
                "Reason using this internal loop each attempt:\n"
                "1) Observe: compare projected_loss_without_cleaning_usd, projected_gain_usd, clean_cost_usd,\n"
                "   roi_ratio, avg_soiling_loss_pct, and rain penalties.\n"
                "2) Decide: pick the action with best short-horizon operational value.\n"
                "3) Self-check: ask if recommendation is too aggressive or too conservative.\n"
                "4) Revise once if needed, then finalize.\n"
                "Reasoning style requirements:\n"
                "- Use plain business language.\n"
                "- Focus on economics using: loss if not cleaned over lookahead_days, "
                "gain if cleaned over gain_horizon_days, and cleaning cost.\n"
                "- Provide chain-of-thought details within the reasoning section and avoid break-even framing unless explicitly asked.\n"
                "Output format requirement:\n"
                "Return ONLY strict JSON with keys: decision, reasoning."
            ),
            model=self.model,
            model_settings=ModelSettings(temperature=0.1),
        )

        prompt = (
            f"Current phase: {phase}.\n"
            f"Metrics JSON: {json.dumps(llm_metrics)}\n"
            "Business policy hints:\n"
            "- high ROI typically deploy\n"
            "- borderline ROI alert\n"
            "- low ROI wait\n"
        )
        if feedback:
            prompt += f"\nFeedback from previous attempt: {feedback}\n"

        result = Runner.run_streamed(decision_agent, prompt)
        response_text = ""
        async for event in result.stream_events():
            if isinstance(event, RawResponsesStreamEvent) and isinstance(
                event.data,
                ResponseTextDeltaEvent,
            ):
                delta = event.data.delta or ""
                response_text += delta
                if event_callback and delta:
                    await event_callback(
                        {
                            "type": "token",
                            "iteration": iteration,
                            "phase": phase,
                            "delta": delta,
                        }
                    )

        parsed_source = response_text.strip()
        if not parsed_source:
            parsed_source = str(result.final_output_as(str))
        parsed = self._parse_json_text(parsed_source)
        decision = parsed.get("decision")
        reasoning = parsed.get("reasoning")

        if decision not in {"deploy_crew", "wait_and_monitor", "alert_only"}:
            decision = "wait_and_monitor"
        if not isinstance(reasoning, str) or not reasoning.strip():
            reasoning = "Policy fallback reasoning due to invalid model output."

        return {"decision": decision, "reasoning": reasoning.strip()}

    @staticmethod
    def _build_manager_decision(
        candidate: dict[str, str],
        metrics: dict[str, float | None],
    ) -> ManagerDecision:
        return ManagerDecision(
            decision=candidate["decision"],
            reasoning=candidate["reasoning"],
            projected_loss_without_cleaning_usd=round(
                float(metrics["projected_loss_without_cleaning_usd"] or 0.0), 2
            ),
            projected_gain_usd=round(float(metrics["projected_gain_usd"] or 0.0), 2),
            clean_cost_usd=round(float(metrics["clean_cost_usd"] or 0.0), 2),
            roi_ratio=round(float(metrics["roi_ratio"] or 0.0), 3),
            break_even_days=(
                round(float(metrics["break_even_days"]), 2)
                if metrics["break_even_days"] is not None
                else None
            ),
        )

    @staticmethod
    def _compute_metrics(
        environment: EnvironmentReport,
        yield_report: YieldReport,
        cleaning_cost_usd: float,
        lookahead_days: int,
    ) -> dict[str, float | None]:
        sun_boost = DecisionManagerAgent._sun_multiplier(environment)
        # If there was recent rain, assume partial natural cleaning already occurred.
        recent_rain_penalty = 0.85 if environment.rain_in_prev_7_days else 1.0
        rain_penalty = 0.75 if environment.rain_in_next_7_days else 1.0

        projected_gain_usd = (
            yield_report.estimated_daily_loss_usd
            * GAIN_HORIZON_DAYS
            * sun_boost
            * rain_penalty
            * recent_rain_penalty
        )
        projected_loss_without_cleaning_usd = yield_report.estimated_daily_loss_usd * lookahead_days
        roi_ratio = (projected_gain_usd / cleaning_cost_usd) if cleaning_cost_usd > 0 else 0.0

        break_even_days = None
        if yield_report.estimated_daily_loss_usd > 0:
            break_even_days = cleaning_cost_usd / yield_report.estimated_daily_loss_usd

        return {
            "estimated_daily_loss_usd": float(yield_report.estimated_daily_loss_usd),
            "lookahead_days": float(lookahead_days),
            "gain_horizon_days": float(GAIN_HORIZON_DAYS),
            "sun_boost": float(sun_boost),
            "rain_penalty": float(rain_penalty),
            "recent_rain_penalty": float(recent_rain_penalty),
            "projected_loss_without_cleaning_usd": float(projected_loss_without_cleaning_usd),
            "projected_gain_usd": float(projected_gain_usd),
            "clean_cost_usd": float(cleaning_cost_usd),
            "roi_ratio": float(roi_ratio),
            "break_even_days": float(break_even_days) if break_even_days is not None else None,
            "avg_soiling_loss_pct": float(yield_report.avg_soiling_loss_pct),
        }

    @staticmethod
    def _deterministic_decision(
        environment: EnvironmentReport,
        metrics: dict[str, float | None],
    ) -> ManagerDecision:
        roi_ratio = float(metrics["roi_ratio"] or 0.0)
        soiling_loss = float(metrics["avg_soiling_loss_pct"] or 0.0)

        if soiling_loss < SOILING_ALERT_THRESHOLD_PCT:
            decision = "wait_and_monitor"
            reasoning = (
                f"Soiling loss ({soiling_loss:.1f}%) is below threshold "
                f"({SOILING_ALERT_THRESHOLD_PCT:.1f}%)."
            )
        elif environment.rain_in_next_7_days and roi_ratio < 1.2:
            decision = "wait_and_monitor"
            reasoning = "Rain is likely in the next 7 days and ROI is not strong enough yet."
        elif roi_ratio >= 1.15:
            decision = "deploy_crew"
            reasoning = "Projected near-term energy recovery exceeds cleaning costs."
        elif 0.95 <= roi_ratio < 1.15:
            decision = "alert_only"
            reasoning = "ROI is borderline; raise alert and re-evaluate after next data refresh."
        else:
            decision = "wait_and_monitor"
            reasoning = "Projected gain does not justify cleaning cost at this time."

        return ManagerDecision(
            decision=decision,
            reasoning=reasoning,
            projected_loss_without_cleaning_usd=round(
                float(metrics["projected_loss_without_cleaning_usd"] or 0.0), 2
            ),
            projected_gain_usd=round(float(metrics["projected_gain_usd"] or 0.0), 2),
            clean_cost_usd=round(float(metrics["clean_cost_usd"] or 0.0), 2),
            roi_ratio=round(roi_ratio, 3),
            break_even_days=(
                round(float(metrics["break_even_days"]), 2)
                if metrics["break_even_days"] is not None
                else None
            ),
        )

    @staticmethod
    def _validate_candidate(
        decision: str,
        environment: EnvironmentReport,
        metrics: dict[str, float | None],
    ) -> tuple[bool, str, str]:
        roi_ratio = float(metrics["roi_ratio"] or 0.0)
        soiling_loss = float(metrics["avg_soiling_loss_pct"] or 0.0)

        if soiling_loss < SOILING_ALERT_THRESHOLD_PCT:
            expected = "wait_and_monitor"
        elif environment.rain_in_next_7_days and roi_ratio < 1.2:
            expected = "wait_and_monitor"
        elif roi_ratio >= 1.15:
            expected = "deploy_crew"
        elif 0.95 <= roi_ratio < 1.15:
            expected = "alert_only"
        else:
            expected = "wait_and_monitor"

        if decision == expected:
            return True, "Decision aligns with deterministic policy.", expected

        return (
            False,
            f"Decision '{decision}' conflicts with policy for roi_ratio={roi_ratio:.3f}",
            expected,
        )

    @staticmethod
    def _sun_multiplier(environment: EnvironmentReport) -> float:
        # Sunshine and PM2.5 jointly adjust how much gain is recoverable.
        sun_ref_hours = max(environment.lookahead_days * 6.0, 1.0)
        sun_factor = environment.sun_hours_next_n_days / sun_ref_hours

        pm25 = environment.pm25 or 10.0
        if pm25 >= 45:
            pm_factor = 1.15
        elif pm25 >= 25:
            pm_factor = 1.08
        else:
            pm_factor = 0.98

        return max(0.7, min(1.35, sun_factor * pm_factor))

    @staticmethod
    def _parse_json_text(text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise ValueError("Agent output did not contain a JSON object")
        return json.loads(match.group(0))
