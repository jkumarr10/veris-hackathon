import logging

from app.clients.open_meteo import OpenMeteoClient
from app.models import EnvironmentReport

logger = logging.getLogger(__name__)


class EnvironmentalAgent:
    def __init__(self, client: OpenMeteoClient | None = None) -> None:
        self.client = client or OpenMeteoClient()

    async def run(self, latitude: float, longitude: float, lookahead_days: int) -> EnvironmentReport:
        report = await self.client.fetch_environment_report(latitude, longitude, lookahead_days)
        logger.info("EnvironmentalAgent output: %s", report.model_dump())
        return report
