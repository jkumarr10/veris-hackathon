import logging
from pathlib import Path

import pandas as pd

from app.models import YieldReport

logger = logging.getLogger(__name__)


class YieldAnalyzerAgent:
    def run(
        self,
        panel_csv_path: str,
        energy_price_per_kwh: float,
    ) -> YieldReport:
        df = pd.read_csv(panel_csv_path)
        if {"panel_id", "zone", "expected_kwh", "actual_kwh"}.issubset(df.columns):
            report = self._run_panel_schema(df, energy_price_per_kwh)
            logger.info("YieldAnalyzerAgent output: %s", report.model_dump())
            return report

        kaggle_required = {"DATE_TIME", "PLANT_ID", "SOURCE_KEY", "AC_POWER"}
        if kaggle_required.issubset(df.columns):
            report = self._run_kaggle_generation_schema(df, panel_csv_path, energy_price_per_kwh)
            logger.info("YieldAnalyzerAgent output: %s", report.model_dump())
            return report

        raise ValueError(
            "Unsupported yield CSV schema. Expected either panel schema "
            "(`panel_id,zone,expected_kwh,actual_kwh`) or Kaggle generation schema "
            "(`DATE_TIME,PLANT_ID,SOURCE_KEY,AC_POWER,...`)."
        )

    def _run_panel_schema(self, df: pd.DataFrame, energy_price_per_kwh: float) -> YieldReport:
        work = df.copy()
        work["expected_kwh"] = pd.to_numeric(work["expected_kwh"], errors="coerce")
        work["actual_kwh"] = pd.to_numeric(work["actual_kwh"], errors="coerce")
        work = work.dropna(subset=["expected_kwh", "actual_kwh", "zone"])
        if work.empty:
            raise ValueError("Panel CSV has no valid rows after cleaning")

        work["lost_kwh"] = (work["expected_kwh"] - work["actual_kwh"]).clip(lower=0)
        total_expected = float(work["expected_kwh"].sum())
        total_lost = float(work["lost_kwh"].sum())

        by_zone = (
            work.groupby("zone", dropna=False)[["expected_kwh", "lost_kwh"]]
            .sum()
            .assign(loss_pct=lambda g: (g["lost_kwh"] / g["expected_kwh"]).fillna(0) * 100.0)
        )
        zone_loss_pct = {str(zone): round(float(pct), 2) for zone, pct in by_zone["loss_pct"].items()}

        worst_zone = None
        if zone_loss_pct:
            worst_zone = max(zone_loss_pct, key=zone_loss_pct.get)

        estimated_daily_loss_usd = total_lost * energy_price_per_kwh
        avg_soiling_loss_pct = (total_lost / total_expected * 100.0) if total_expected > 0 else 0.0

        return YieldReport(
            panel_count=int(work["panel_id"].nunique()),
            avg_soiling_loss_pct=round(avg_soiling_loss_pct, 2),
            worst_zone=worst_zone,
            zone_loss_pct=zone_loss_pct,
            estimated_daily_loss_usd=round(float(estimated_daily_loss_usd), 2),
            estimated_daily_lost_kwh=round(float(total_lost), 2),
            estimated_plant_capacity_mw=None,
        )

    def _run_kaggle_generation_schema(
        self,
        gen_df: pd.DataFrame,
        generation_csv_path: str,
        energy_price_per_kwh: float,
    ) -> YieldReport:
        weather_path = self._infer_weather_path(generation_csv_path)
        weather_df = pd.read_csv(weather_path)
        if not {"DATE_TIME", "PLANT_ID", "IRRADIATION"}.issubset(weather_df.columns):
            raise ValueError("Kaggle weather file missing required columns: DATE_TIME, PLANT_ID, IRRADIATION")

        gen = gen_df.copy()
        weather = weather_df.copy()
        gen["DATE_TIME"] = gen["DATE_TIME"].map(self._parse_kaggle_datetime)
        weather["DATE_TIME"] = weather["DATE_TIME"].map(self._parse_kaggle_datetime)
        gen = gen.dropna(subset=["DATE_TIME", "PLANT_ID", "SOURCE_KEY", "AC_POWER"])
        weather = weather.dropna(subset=["DATE_TIME", "PLANT_ID", "IRRADIATION"])
        if gen.empty or weather.empty:
            raise ValueError("Kaggle generation/weather data has no usable rows after datetime parsing.")

        weather = weather[["DATE_TIME", "PLANT_ID", "IRRADIATION"]]
        weather = weather.groupby(["DATE_TIME", "PLANT_ID"], as_index=False)["IRRADIATION"].mean()

        merged = gen.merge(weather, on=["DATE_TIME", "PLANT_ID"], how="left")
        merged["AC_POWER"] = pd.to_numeric(merged["AC_POWER"], errors="coerce")
        merged["IRRADIATION"] = pd.to_numeric(merged["IRRADIATION"], errors="coerce")
        merged = merged.dropna(subset=["AC_POWER", "IRRADIATION"])
        if merged.empty:
            raise ValueError("No overlapping generation and weather timestamps found.")

        merged = merged.sort_values(["SOURCE_KEY", "DATE_TIME"])
        dt_hours = (
            merged.groupby("SOURCE_KEY")["DATE_TIME"]
            .diff()
            .dt.total_seconds()
            .div(3600)
            .fillna(0.25)
            .clip(lower=0.05, upper=1.0)
        )
        merged["interval_hours"] = dt_hours

        # Derive expected power from irradiation profile per inverter using observed max AC.
        max_irr = float(max(merged["IRRADIATION"].max(), 1e-6))
        peak_ac_by_source = merged.groupby("SOURCE_KEY")["AC_POWER"].transform("max").clip(lower=0)
        performance_ratio = 0.9
        merged["expected_power_kw"] = (peak_ac_by_source * (merged["IRRADIATION"] / max_irr) * performance_ratio).clip(
            lower=0
        )
        merged["actual_kwh"] = (merged["AC_POWER"] * merged["interval_hours"]).clip(lower=0)
        merged["expected_kwh"] = (merged["expected_power_kw"] * merged["interval_hours"]).clip(lower=0)
        merged["lost_kwh"] = (merged["expected_kwh"] - merged["actual_kwh"]).clip(lower=0)

        # Deterministic zone mapping for demo grouping.
        zones = ["Block A", "Block B", "Block C", "Block D"]
        merged["zone"] = merged["SOURCE_KEY"].map(lambda s: zones[sum(ord(c) for c in str(s)) % len(zones)])

        total_expected = float(merged["expected_kwh"].sum())
        total_lost = float(merged["lost_kwh"].sum())
        avg_soiling_loss_pct = (total_lost / total_expected * 100.0) if total_expected > 0 else 0.0

        by_zone = (
            merged.groupby("zone", dropna=False)[["expected_kwh", "lost_kwh"]]
            .sum()
            .assign(loss_pct=lambda g: (g["lost_kwh"] / g["expected_kwh"]).fillna(0) * 100.0)
        )
        zone_loss_pct = {str(zone): round(float(pct), 2) for zone, pct in by_zone["loss_pct"].items()}
        worst_zone = max(zone_loss_pct, key=zone_loss_pct.get) if zone_loss_pct else None

        estimated_daily_loss_usd = total_lost * energy_price_per_kwh
        peak_ac_per_source_kw = merged.groupby("SOURCE_KEY")["AC_POWER"].max().clip(lower=0)
        estimated_plant_capacity_mw = float(peak_ac_per_source_kw.sum() / 1000.0)

        return YieldReport(
            panel_count=int(merged["SOURCE_KEY"].nunique()),
            avg_soiling_loss_pct=round(avg_soiling_loss_pct, 2),
            worst_zone=worst_zone,
            zone_loss_pct=zone_loss_pct,
            estimated_daily_loss_usd=round(float(estimated_daily_loss_usd), 2),
            estimated_daily_lost_kwh=round(float(total_lost), 2),
            estimated_plant_capacity_mw=round(estimated_plant_capacity_mw, 3),
        )

    @staticmethod
    def _infer_weather_path(generation_csv_path: str) -> str:
        p = Path(generation_csv_path)
        name = p.name
        if "Generation_Data" in name:
            candidate = p.with_name(name.replace("Generation_Data", "Weather_Sensor_Data"))
            if candidate.exists():
                return str(candidate)
        raise ValueError(
            "Could not infer paired weather CSV for Kaggle generation file. "
            "Expected sibling file named like `Plant_X_Weather_Sensor_Data.csv`."
        )

    @staticmethod
    def _parse_kaggle_datetime(value: object) -> pd.Timestamp | None:
        if value is None:
            return pd.NaT
        text = str(value).strip()
        if not text:
            return pd.NaT
        # Plant 1 uses DD-MM-YYYY HH:MM; plant 2/weather often uses ISO-like YYYY-MM-DD HH:MM:SS.
        if "-" in text and ":" in text:
            first = text.split("-", 1)[0]
            if len(first) == 4:
                return pd.to_datetime(text, format="%Y-%m-%d %H:%M:%S", errors="coerce")
            return pd.to_datetime(text, format="%d-%m-%Y %H:%M", errors="coerce")
        return pd.to_datetime(text, errors="coerce")
