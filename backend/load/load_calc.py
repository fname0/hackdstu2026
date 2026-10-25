"""Загрузка справочников калькулятора сделок (модуль 3) из data/seed/calc в PostgreSQL.

Таблицы пересоздаются целиком (загрузка идемпотентна):
  calc_items        — прайс компонентов (МОД3_Таб4): id, группа, название, единица, цена, коэффициент сложности;
  calc_coefficients — коэффициенты: kind = region (Таб1) / level (Таб2) / stage (Таб3, доля от оборудования).
Метаданные — строка calc_reference в таблице meta.

Запуск: docker compose run --rm api python -m backend.load.load_calc   (нужны права на запись; rt_reader не подойдёт)
Перед этим: python -m backend.etl.calc_reference
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from backend.load.load_radar import engine

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed" / "calc"


def load(con) -> dict:
    ref = json.loads((SEED / "reference.json").read_text(encoding="utf-8"))
    pd.DataFrame(ref["items"]).to_sql("calc_items", con, if_exists="replace", index_label="sort")
    con.execute(text("ALTER TABLE calc_items ADD PRIMARY KEY (id)"))
    coefs = [{**c, "kind": kind, "sort": i} for kind in ("region", "level", "stage")
             for i, c in enumerate(ref[f"{kind}s"])]
    pd.DataFrame(coefs).to_sql("calc_coefficients", con, if_exists="replace", index=False)
    con.execute(text("ALTER TABLE calc_coefficients ADD PRIMARY KEY (kind, code)"))

    con.execute(text("CREATE TABLE IF NOT EXISTS meta (name text, data text)"))
    con.execute(text("DELETE FROM meta WHERE name = 'calc_reference'"))
    con.execute(text("INSERT INTO meta (name, data) VALUES ('calc_reference', :d)"),
                {"d": (SEED / "reference.meta.json").read_text(encoding="utf-8")})
    return {"calc_items": len(ref["items"]), "calc_coefficients": len(coefs)}


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    t0 = time.time()
    with engine().begin() as con:
        print(json.dumps(load(con), ensure_ascii=False))
    print(f"готово за {time.time() - t0:.1f} с")


if __name__ == "__main__":
    main()
