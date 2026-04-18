import argparse
import random
from pathlib import Path

import pandas as pd


def generate(output: str, panels: int, seed: int) -> None:
    random.seed(seed)
    zones = ["Block A", "Block B", "Block C", "Block D"]
    rows = []

    for i in range(1, panels + 1):
        zone = zones[(i - 1) % len(zones)]
        expected_kwh = round(random.uniform(28.0, 44.0), 2)

        zone_soiling_bias = {
            "Block A": random.uniform(0.82, 0.99),
            "Block B": random.uniform(0.78, 0.97),
            "Block C": random.uniform(0.70, 0.93),
            "Block D": random.uniform(0.80, 0.98),
        }[zone]
        actual_kwh = round(expected_kwh * zone_soiling_bias, 2)

        rows.append(
            {
                "panel_id": f"P-{i:03d}",
                "zone": zone,
                "expected_kwh": expected_kwh,
                "actual_kwh": actual_kwh,
            }
        )

    df = pd.DataFrame(rows)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} panel rows to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/panels.csv")
    parser.add_argument("--panels", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.output, args.panels, args.seed)
