"""Import Rwanda population density XYZ CSV into PostGIS.

Expected columns: X, Y, Z or lon, lat, density.
Run from project root after configuring DATABASE_URL.
"""
import os
import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/bizintel")
CSV_PATH = os.getenv("POP_DENSITY_CSV", "data/raw/rwa_pd_2020_1km_ASCII_XYZ.csv")


def main() -> None:
    engine = create_engine(DATABASE_URL)
    df = pd.read_csv(CSV_PATH)
    df.columns = [c.strip().lower() for c in df.columns]

    lon_col = "x" if "x" in df.columns else "lon"
    lat_col = "y" if "y" in df.columns else "lat"
    density_col = "z" if "z" in df.columns else "density"

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE geo.population_density_grid"))
        for chunk_start in range(0, len(df), 5000):
            chunk = df.iloc[chunk_start:chunk_start + 5000]
            rows = [
                {"density": float(r[density_col]), "lon": float(r[lon_col]), "lat": float(r[lat_col])}
                for _, r in chunk.iterrows()
            ]
            conn.execute(
                text(
                    """
                    INSERT INTO geo.population_density_grid (density, geom)
                    VALUES (:density, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                    """
                ),
                rows,
            )
    print(f"Imported {len(df):,} population density points")


if __name__ == "__main__":
    main()
