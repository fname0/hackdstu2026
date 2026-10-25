"""Загрузка инвестпроектов (модуль 2) из data/seed/invest в PostgreSQL/PostGIS.

Склейка двух источников в одну таблицу `projects` (пересоздаётся целиком — загрузка идемпотентна):
  - основной — реестр invest-don.ru (projects_don_<регион>.parquet, ~1500 проектов);
  - проекты из xlsx организаторов (projects_<регион>.parquet, 63): совпавшие с реестром по названию внутри того же
    муниципалитета (похожесть ≥ 0.8) только помечают запись реестра флагом in_organizers_sample и номером строки xlsx,
    несовпавшие добавляются отдельными записями с source = «xlsx организаторов».
Метаданные (источники, даты выгрузки) — в таблицу meta (строки invest_*).

Запуск: docker compose run --rm api python -m backend.load.load_invest   (нужны права на запись; rt_reader не подойдёт)
Перед этим: python -m backend.etl.invest_don && python -m backend.etl.invest --source invest-don && python -m backend.etl.invest
"""
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from backend.load.load_radar import engine

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed" / "invest"
REGION = os.environ.get("REGION", "61")
MIN_TITLE_MATCH = 0.8

COLUMNS = [
    "project_id", "source", "in_organizers_sample", "organizers_no", "site_status", "url", "create_date", "modify_date",
    "region", "mo_raw", "oktmo", "municipality", "curator", "is_key",
    "initiator", "initiators", "initiator_inn", "initiator_matched_name", "match_score", "match_method",
    "client_status", "is_interregional", "initiator_projects",
    "title", "address_from_text", "lat", "lon", "location_precision",
    "start_year", "finish_year", "duration_years", "stage", "months_to_launch", "sales_window",
    "sum_mln", "jobs", "industry", "industry_reason", "needs", "needs_detail",
    "it_share", "rtk_potential_mln", "rtk_potential_is_estimate", "hot_score", "hot_factors",
]


def _title_key(s: str) -> str:
    return re.sub(r"\W+", " ", str(s or "")).lower().strip()


def merge_sources() -> pd.DataFrame:
    don = pd.read_parquet(SEED / f"projects_don_{REGION}.parquet")
    xl = pd.read_parquet(SEED / f"projects_{REGION}.parquet")
    don["in_organizers_sample"], don["organizers_no"] = False, None
    keys = don.title.map(_title_key)

    extra = []
    for r in xl.to_dict("records"):
        k = _title_key(r["title"])
        cand = don.index[don.mo_raw == r["mo_raw"]]
        best, score = None, 0.0
        for i in cand:
            s = difflib.SequenceMatcher(None, k, keys[i]).ratio()
            if s > score:
                best, score = i, s
        if best is not None and score >= MIN_TITLE_MATCH:
            don.loc[best, "in_organizers_sample"] = True
            don.loc[best, "organizers_no"] = str(r["src_no"])
        else:
            r.update(in_organizers_sample=True, organizers_no=str(r["src_no"]))
            extra.append(r)
    out = pd.concat([don, pd.DataFrame(extra)], ignore_index=True)
    out["organizers_no"] = out.organizers_no.astype("string")
    # Массивы и JSON — строками: pandas их в postgres-типы не переводит, приводим SQL-ом после загрузки
    out["needs"] = out.needs.map(lambda v: ",".join(v) if v is not None and len(v) else "")
    out["initiators"] = out.initiators.map(lambda v: " ; ".join(v) if v is not None and len(v) else "")
    for c in COLUMNS:
        if c not in out:
            out[c] = None
    # После склейки с пропусками целые стали float (2027.0) — возвращаем целый тип с NULL
    for c in ["start_year", "finish_year", "duration_years", "months_to_launch", "jobs", "initiator_projects"]:
        out[c] = pd.to_numeric(out[c]).round().astype("Int64")
    return out[COLUMNS]


def load_projects(con) -> dict:
    p = merge_sources()
    p.to_sql("projects", con, if_exists="replace", index=False, chunksize=500, method="multi")
    con.execute(text("ALTER TABLE projects ADD PRIMARY KEY (project_id)"))
    con.execute(text("""ALTER TABLE projects
        ALTER COLUMN needs TYPE text[] USING CASE WHEN needs = '' THEN '{}'::text[] ELSE string_to_array(needs, ',') END,
        ALTER COLUMN needs_detail TYPE jsonb USING needs_detail::jsonb,
        ALTER COLUMN hot_factors TYPE jsonb USING hot_factors::jsonb,
        ADD COLUMN geom geometry(Point, 4326),
        ADD COLUMN is_active boolean"""))
    con.execute(text("UPDATE projects SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326) WHERE lat IS NOT NULL AND lon IS NOT NULL"))
    # «Активный» — тот, где ещё можно продать стройку: не введён и не приостановлен
    con.execute(text("UPDATE projects SET is_active = stage NOT IN ('введён', 'приостановлен')"))
    for idx in ["stage", "industry", "oktmo", "initiator_inn", "is_active", "hot_score DESC", "finish_year"]:
        con.execute(text(f"CREATE INDEX projects_{idx.split()[0]}_idx ON projects ({idx})"))
    con.execute(text("CREATE INDEX projects_needs_idx ON projects USING gin (needs)"))
    con.execute(text("CREATE INDEX projects_geom_idx ON projects USING gist (geom)"))
    con.execute(text("CREATE INDEX projects_title_trgm_idx ON projects USING gin (lower(title || ' ' || initiator) gin_trgm_ops)"))
    return {"projects": len(p), "from_invest_don": int((p.source == "invest-don.ru").sum()),
            "organizers_sample": int(p.in_organizers_sample.sum()),
            "organizers_matched_to_registry": int(((p.source == "invest-don.ru") & p.in_organizers_sample).sum())}


def load_meta(con) -> int:
    con.execute(text("CREATE TABLE IF NOT EXISTS meta (name text, data text)"))
    con.execute(text("DELETE FROM meta WHERE name LIKE 'invest%' OR name LIKE 'projects%'"))
    n = 0
    for f in sorted(SEED.glob("*.meta.json")):
        con.execute(text("INSERT INTO meta (name, data) VALUES (:n, :d)"),
                    {"n": f.stem.replace(".meta", ""), "d": f.read_text(encoding="utf-8")})
        n += 1
    return n


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    t0 = time.time()
    with engine().begin() as con:
        con.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        con.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        print(json.dumps(load_projects(con), ensure_ascii=False))
        print("meta", load_meta(con))
        from backend.load.load_gov_projects import load as load_gov_projects
        print("government", load_gov_projects(con, REGION))
    print(f"готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
