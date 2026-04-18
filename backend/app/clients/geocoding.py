import httpx
import logging

from app.models import GeocodeResult

logging.basicConfig(level=logging.INFO)

class GeocodingClient:
    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

    async def geocode_address(self, address: str) -> GeocodeResult:
        async with httpx.AsyncClient(timeout=20.0) as client:
            open_meteo = await self._try_open_meteo(client, address)
            if open_meteo is not None:
                return open_meteo

            nominatim = await self._try_nominatim(client, address)
            if nominatim is not None:
                return nominatim

        raise ValueError(
            "No geocoding match found. Try a simpler address like 'Santa Margarita, CA' or "
            "'California Valley Solar Ranch, California'."
        )

    async def _try_open_meteo(self, client: httpx.AsyncClient, address: str) -> GeocodeResult | None:
        for query in self._candidate_queries(address):
            params = {
                "name": query,
                "count": 1,
                "language": "en",
                "format": "json",
            }
            resp = await client.get(self.GEOCODING_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
            results = payload.get("results") or []
            if not results:
                continue
            top = results[0]
            return GeocodeResult(
                address_input=address,
                name=top.get("name", query),
                latitude=float(top["latitude"]),
                longitude=float(top["longitude"]),
                country=top.get("country"),
                admin1=top.get("admin1"),
                timezone=top.get("timezone"),
            )
        return None

    async def _try_nominatim(self, client: httpx.AsyncClient, address: str) -> GeocodeResult | None:
        headers = {"User-Agent": "solar-soiling-optimizer/0.1 (hackathon-demo)"}
        for query in self._candidate_queries(address):
            params = {
                "q": query,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1,
            }
            resp = await client.get(self.NOMINATIM_URL, params=params, headers=headers)
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                continue
            top = rows[0]
            addr = top.get("address", {})
            return GeocodeResult(
                address_input=address,
                name=top.get("display_name", query),
                latitude=float(top["lat"]),
                longitude=float(top["lon"]),
                country=addr.get("country"),
                admin1=addr.get("state"),
                timezone=None,
            )
        return None

    @staticmethod
    def _candidate_queries(address: str) -> list[str]:
        parts = [p.strip() for p in address.split(",") if p.strip()]
        candidates: list[str] = [address.strip()]

        if len(parts) > 1:
            candidates.append(", ".join(parts[1:]))

        if len(parts) >= 3:
            candidates.append(", ".join(parts[-3:]))
            candidates.append(", ".join(parts[-2:]))

        # Add a city/state fallback when a named site is not recognized by provider.
        deduped: list[str] = []
        for c in candidates:
            if c and c not in deduped:
                deduped.append(c)
        return deduped

if __name__ == "__main__":
    import asyncio
    
    client = GeocodingClient()
    result = asyncio.run(client.geocode_address("California Valley Solar Ranch, 13155 Boulder Creek Rd, Santa Margarita, CA 93453"))
    
    print(result)