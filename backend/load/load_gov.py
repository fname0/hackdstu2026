"""Загрузка госсектора из data/seed/gov в PostGIS: institutions (учреждения с bus.gov.ru) и gov_contracts (контракты
на связь из ЕИС). Таблицы пересоздаются целиком.

Запуск: docker compose run --rm api python -m backend.load.load_gov
Перед этим: python -m backend.etl.busgov_fetch (выгрузка) → python -m backend.etl.busgov (разбор).
"""
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from backend.load.load_radar import engine

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed" / "gov"
REGION = os.environ.get("REGION", "61")


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    t0 = time.time()
    df = pd.read_parquet(SEED / f"institutions_{REGION}.parquet")
    with engine().begin() as con:
        con.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        df.to_sql("institutions", con, if_exists="replace", index=False, chunksize=1000, method="multi")
        con.execute(text("ALTER TABLE institutions ADD PRIMARY KEY (inn)"))
        con.execute(text("ALTER TABLE institutions ADD COLUMN geom geometry(Point, 4326)"))
        con.execute(text("UPDATE institutions SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326) "
                         "WHERE lat IS NOT NULL AND lon IS NOT NULL"))
        for col in ["segment", "oktmo", "level", "is_liquidating"]:
            con.execute(text(f"CREATE INDEX institutions_{col}_idx ON institutions ({col})"))
        con.execute(text("CREATE INDEX institutions_geom_idx ON institutions USING gist (geom)"))
        contracts = SEED / f"contracts_{REGION}.parquet"
        n_contracts = 0
        if contracts.exists():  # контракты на связь из ЕИС (backend/etl/contracts.py) — по ИНН заказчика
            c = pd.read_parquet(contracts)
            c.to_sql("gov_contracts", con, if_exists="replace", index=False, chunksize=1000, method="multi")
            con.execute(text("ALTER TABLE gov_contracts ADD PRIMARY KEY (reestr_number)"))
            for col in ["customer_inn", "supplier_inn", "finish_date"]:
                con.execute(text(f"CREATE INDEX gov_contracts_{col}_idx ON gov_contracts ({col})"))
            n_contracts = len(c)
        con.execute(text("CREATE TABLE IF NOT EXISTS meta (name text, data text)"))
        con.execute(text("DELETE FROM meta WHERE name LIKE 'institutions%' OR name LIKE 'contracts%'"))
        for stem in (f"institutions_{REGION}", f"contracts_{REGION}"):
            meta = SEED / f"{stem}.meta.json"
            if meta.exists():
                con.execute(text("INSERT INTO meta (name, data) VALUES (:n, :d)"), {"n": stem, "d": meta.read_text(encoding="utf-8")})
    print(json.dumps({"institutions": len(df), "with_coords": int(df.lat.notna().sum()), "contracts": n_contracts}, ensure_ascii=False))
    print(f"готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
