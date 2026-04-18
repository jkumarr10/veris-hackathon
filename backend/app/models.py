from typing import Literal

from pydantic import BaseModel, Field


class EnvironmentReport(BaseModel):
    latitude: float
    longitude: float
    pm25: float | None
    pm10: float | None
    humidity_pct: float | None
    wind_speed_kmh: float | None
    wind_direction_deg: float | None
    rain_in_next_7_days: bool
    rainy_days_next_7_days: int
    total_precipitation_next_7_days_mm: float
    rain_in_prev_7_days: bool
    rainy_days_prev_7_days: int
    total_precipitation_prev_7_days_mm: float
    sun_hours_next_n_days: float
    avg_shortwave_radiation_wm2_next_n_days: float
    lookahead_days: int


class YieldReport(BaseModel):
    panel_count: int
    avg_soiling_loss_pct: float
    worst_zone: str | None
    zone_loss_pct: dict[str, float]
    estimated_daily_loss_usd: float
    estimated_daily_lost_kwh: float
    estimated_plant_capacity_mw: float | None = None


class ManagerDecision(BaseModel):
    decision: Literal["deploy_crew", "wait_and_monitor", "alert_only"]
    reasoning: str
    gain_horizon_days: int
    projected_loss_without_cleaning_usd: float
    projected_gain_usd: float
    clean_cost_usd: float
    roi_ratio: float
    break_even_days: float | None


class RunDecisionRequest(BaseModel):
    latitude: float
    longitude: float
    panel_csv_path: str | None = None
    cleaning_cost_usd: float | None = None
    lookahead_days: int | None = Field(default=None, ge=1, le=7)
    energy_price_per_kwh: float | None = Field(default=None, gt=0)
    use_llm_manager: bool = True


class RunDecisionResponse(BaseModel):
    environment: EnvironmentReport
    yield_report: YieldReport
    manager_decision: ManagerDecision
    data_sources: list[str] = []
    assumptions: list[str] = []


class GeocodeRequest(BaseModel):
    address: str = Field(min_length=3)


class GeocodeResult(BaseModel):
    address_input: str
    name: str
    latitude: float
    longitude: float
    country: str | None = None
    admin1: str | None = None
    timezone: str | None = None


class RunDecisionByAddressRequest(BaseModel):
    address: str = Field(min_length=3)
    panel_csv_path: str | None = None
    cleaning_cost_usd: float | None = None
    lookahead_days: int | None = Field(default=None, ge=1, le=7)
    energy_price_per_kwh: float | None = Field(default=None, gt=0)
    use_llm_manager: bool = True


class RunDecisionByAddressResponse(BaseModel):
    input_address: str
    resolved_location: GeocodeResult
    environment: EnvironmentReport
    yield_report: YieldReport
    manager_decision: ManagerDecision
    data_sources: list[str] = []
    assumptions: list[str] = []
