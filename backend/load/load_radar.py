"""Загрузка подготовленных данных радара (data/seed) в PostgreSQL/PostGIS.

Таблицы пересоздаются целиком — загрузка идемпотентна:
    zones      — муниципалитеты: границы (MultiPolygon) + метрики и потенциал (zones_<регион>.parquet)
    companies  — все субъекты МСП региона с баллами, финансами и данными DaData (scored_<регион>.parquet)
    clients    — клиенты РТК из исходной таблицы со статусом (clients_<регион>.parquet)
    meta       — источники и даты выпусков

Запуск: docker compose run --rm api python -m backend.load.load_radar
"""
import io
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed"
REGION = os.environ.get("REGION", "61")
GEOJSON = {"61": "rostov_municipalities.geojson"}

COMPANY_COLUMNS = [
    "inn", "ogrn", "kind", "category", "name", "name_short", "is_new", "is_social", "msp_since", "msp_years",
    "staff", "district", "city", "settlement", "place", "okved_main", "okved_main_name", "okved_extra", "licenses",
    "oktmo", "municipality", "oktmo_method", "location_precision",
    "is_rtk_client", "new_in_release", "inn_region", "inn_other_region",
    "income_2024", "expense_2024", "income_2025", "expense_2025", "income_growth_pct", "staff_2025", "tax_regime",
    "industry", "relevance", "products", "products_reason",
    "lead_score", "lead_rank_in_kind", "s_scale", "s_staff", "s_growth", "s_industry", "s_zone", "s_age",
    "s_licenses", "s_kfh", "s_new", "flag_zero_income", "flag_check_category",
    "dd_name", "dd_status", "dd_liquidation_date", "kpp", "branch_count", "branches_in_region", "branches",
    "legal_address", "reloc_signals", "geo_lat", "geo_lon", "qc_geo", "geo_precision", "house_fias_id",
    "rtk_in_same_building", "mass_address", "source",
]


def engine():
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://rt:rt_local_dev@localhost:5432/rt")
    return create_engine(url)


def load_zones(con):
    z = pd.read_parquet(SEED / "radar" / f"zones_{REGION}.parquet")
    geo = json.loads((SEED / "geo" / GEOJSON[REGION]).read_text(encoding="utf-8"))
    shapes = {f["properties"]["oktmo"]: f for f in geo["features"]}
    z.to_sql("zones", con, if_exists="replace", index=False)
    con.execute(text("ALTER TABLE zones ADD PRIMARY KEY (oktmo)"))
    con.execute(text("ALTER TABLE zones ADD COLUMN kind text, ADD COLUMN short text, ADD COLUMN geom geometry(MultiPolygon, 4326)"))
    for oktmo, f in shapes.items():
        con.execute(text("""UPDATE zones SET kind = :kind, short = :short,
                            geom = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)) WHERE oktmo = :o"""),
                    {"kind": f["properties"]["kind"], "short": f["properties"]["short"],
                     "g": json.dumps(f["geometry"]), "o": oktmo})
    con.execute(text("CREATE INDEX zones_geom_idx ON zones USING gist (geom)"))
    return len(z)


def load_companies(con):
    s = pd.read_parquet(SEED / "radar" / f"scored_{REGION}.parquet")
    cols = [c for c in COMPANY_COLUMNS if c in s.columns]
    s = s[cols].copy()
    # У 220 юрлиц в реестре МСП пустое краткое наименование — показываем полное
    s["name_short"] = s.name_short.where(s.name_short.fillna("").str.strip() != "", s.name)
    # Структуру таблицы создаёт pandas (по пустому кадру), сами 188 тыс. строк заливаются COPY — в разы быстрее INSERT
    s.head(0).to_sql("companies", con, if_exists="replace", index=False)
    buf = io.StringIO()
    s.to_csv(buf, index=False, header=False)
    buf.seek(0)
    raw = con.connection.driver_connection  # psycopg 3
    with raw.cursor() as cur, cur.copy(f"COPY companies ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv)") as cp:
        while chunk := buf.read(1 << 20):
            cp.write(chunk)
    con.execute(text("ALTER TABLE companies ADD PRIMARY KEY (inn)"))
    con.execute(text("ALTER TABLE companies ADD COLUMN geom geometry(Point, 4326)"))
    if "geo_lat" in cols:
        con.execute(text("UPDATE companies SET geom = ST_SetSRID(ST_MakePoint(geo_lon, geo_lat), 4326) "
                         "WHERE geo_lat IS NOT NULL AND geo_lon IS NOT NULL"))
    for idx in ["oktmo", "kind", "industry", "is_rtk_client", "lead_score DESC", "income_2025"]:
        name = idx.split()[0]
        con.execute(text(f"CREATE INDEX companies_{name}_idx ON companies ({idx})"))
    con.execute(text("CREATE INDEX companies_geom_idx ON companies USING gist (geom)"))
    con.execute(text("CREATE INDEX companies_name_trgm_idx ON companies USING gin (lower(name) gin_trgm_ops)"))
    return len(s), int(s["geo_lat"].notna().sum()) if "geo_lat" in cols else 0


def load_clients(con):
    c = pd.read_parquet(SEED / "radar" / f"clients_{REGION}.parquet")
    c.to_sql("clients", con, if_exists="replace", index=False)
    con.execute(text("ALTER TABLE clients ADD PRIMARY KEY (inn)"))
    return len(c)


def load_meta(con):
    rows = []
    for p in sorted(SEED.rglob("*.meta.json")):
        rows.append({"name": p.stem.replace(".meta", ""), "data": p.read_text(encoding="utf-8")})
    pd.DataFrame(rows).to_sql("meta", con, if_exists="replace", index=False)
    return len(rows)


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    t0 = time.time()
    eng = engine()
    with eng.begin() as con:
        con.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        con.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        print("zones", load_zones(con))
        print("companies, geocoded", load_companies(con))
        print("clients", load_clients(con))
        print("meta", load_meta(con))
    print(f"готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
