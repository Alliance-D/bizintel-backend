"""Export the modelling dataset to CSV.

This is exactly what the model trains on: the leak-free fundamentals plus the
observed count it predicts (and the binary presence flag the hurdle's stage 1
uses). The hand-weighted composite scores (demand_score, accessibility_score,
...) and the retired opportunity_gap_score are deliberately left out - they are
display context, not model inputs, and including them is what made the old dump
misleading.

Usage:
    python scripts/export_training_dataset.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_and_score_opportunity_model import (  # noqa: E402
    CATEGORICAL_FEATURES, NUMERIC_FEATURES, TARGET, engine,
)

ID_COLS = ["grid_id", "business_category", "district", "sector", "cell"]
# business_category / district / sector are already identifiers above.
EXTRA_CATEGORICAL = [c for c in CATEGORICAL_FEATURES if c not in ("business_category", "district", "sector")]


def main() -> None:
    """Query the current feature table and write the features + target to CSV."""
    select_cols = (
        ID_COLS
        + ["ST_Y(centroid) AS latitude", "ST_X(centroid) AS longitude"]
        + NUMERIC_FEATURES + EXTRA_CATEGORICAL
    )
    query = f"""
        SELECT {", ".join(select_cols)},
               competitor_count_1000m AS {TARGET},
               (competitor_count_1000m > 0)::int AS presence_target
        FROM ml.grid_category_features
        ORDER BY business_category, grid_id
    """
    df = pd.read_sql_query(query, engine())

    out_dir = Path("data/exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = out_dir / f"training_dataset_{ts}.csv"
    df.to_csv(path, index=False)

    print(f"Wrote {len(df):,} rows x {df.shape[1]} columns -> {path}")
    print(f"Model features ({len(NUMERIC_FEATURES) + len(EXTRA_CATEGORICAL)}): "
          f"{NUMERIC_FEATURES + EXTRA_CATEGORICAL}")
    print(f"Target: {TARGET}  (plus presence_target = {TARGET} > 0)")


if __name__ == "__main__":
    main()
