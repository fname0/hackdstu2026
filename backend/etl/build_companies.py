"""Сборка итоговых таблиц радара из результатов шагов 1–3.

Вход:
    data/seed/fns/msp_<регион>_<дата>.parquet   — два выпуска реестра МСП (текущий и прошлый месяц)
    data/seed/fns/finance_<регион>.parquet       — доходы, численность, спецрежимы
    Хакатон_2026_фактура.xlsx, лист МОД1_Таб1     — клиенты РТК
    data/seed/geo/<регион>_municipalities.geojson — справочник ОКТМО

Выход (data/seed/radar/):
    companies_<регион>.parquet — все субъекты МСП региона на текущий выпуск, с ОКТМО, финансами и признаком «клиент РТК»
    clients_<регион>.parquet   — все клиенты РТК из исходной таблицы со статусом в реестре

Запуск из корня репо:
    python -m backend.etl.build_companies --region 61
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd

from backend.etl.municipality import assign, load_reference

ROOT = Path(__file__).resolve().parents[2]
FNS = ROOT / "data" / "seed" / "fns"
OUT = ROOT / "data" / "seed" / "radar"
XLSX = ROOT / "Хакатон_2026_фактура.xlsx"


def read_clients() -> pd.DataFrame:
    """МОД1_Таб1: клиенты РТК. Берём ИНН и исходные поля как есть, только для сверки."""
    ws = openpyxl.load_workbook(XLSX, read_only=True, data_only=True).worksheets[0]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[0]:
            continue
        rows.append({"inn": str(r[5]).strip(), "client_name_xlsx": r[1], "client_okved_xlsx": r[6]})
    return pd.DataFrame(rows).drop_duplicates("inn")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="61")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    releases = sorted(FNS.glob(f"msp_{a.region}_*.parquet"))
    if len(releases) < 2:
        sys.exit("нужны два выпуска реестра МСП (текущий и прошлый месяц)")
    prev_path, cur_path = releases[-2], releases[-1]
    cur_date, prev_date = cur_path.stem.split("_")[-1], prev_path.stem.split("_")[-1]
    cur, prev = pd.read_parquet(cur_path), pd.read_parquet(prev_path)
    fin = pd.read_parquet(FNS / f"finance_{a.region}.parquet")
    clients = read_clients()
    ref = load_reference(a.region)

    # Муниципалитет по ОКТМО
    loc = [assign(d, c, s, ref) for d, c, s in zip(cur.district, cur.city, cur.settlement)]
    cur["oktmo"] = [x[0] for x in loc]
    cur["municipality"] = [x[1] for x in loc]
    cur["oktmo_method"] = [x[2] for x in loc]
    cur["place"] = cur.settlement.where(cur.settlement != "", cur.city)
    cur["location_precision"] = "населённый пункт"  # точнее станет после геокодинга ЮЛ (DaData)

    # Клиенты РТК и динамика рынка
    client_inns = set(clients.inn)
    prev_inns = set(prev.inn)
    cur["is_rtk_client"] = cur.inn.isin(client_inns)
    cur["new_in_release"] = ~cur.inn.isin(prev_inns)
    # ИНН выдан в другом регионе — сигнал для задачи «*» (у ИП часто означает лишь место получения ИНН)
    cur["inn_region"] = cur.inn.str[:2]
    cur["inn_other_region"] = cur.inn_region != a.region

    companies = cur.merge(fin, on="inn", how="left")
    companies["source"] = f"ФНС: реестр МСП на {cur_date}; доходы/численность/спецрежимы — открытые данные ФНС"

    # Статус каждого клиента РТК
    cur_inns = set(cur.inn)
    def status(inn):
        if inn in cur_inns:
            return "в реестре МСП"
        if inn in prev_inns:
            return f"выбыл из реестра МСП между {prev_date} и {cur_date}"
        return f"нет в реестре МСП на {prev_date} и {cur_date}"
    clients["msp_status"] = clients.inn.map(status)
    # Для выбывших берём их последнюю запись из прошлого выпуска
    last = pd.concat([cur.drop(columns=["oktmo", "municipality", "oktmo_method", "place", "location_precision",
                                        "is_rtk_client", "new_in_release", "inn_region", "inn_other_region"]),
                      prev[~prev.inn.isin(cur_inns)]]).drop_duplicates("inn")
    clients = clients.merge(last, on="inn", how="left")
    loc = [assign(d, c, s, ref) if isinstance(d, str) else (None, None, "не привязан")
           for d, c, s in zip(clients.district, clients.city, clients.settlement)]
    clients["oktmo"] = [x[0] for x in loc]
    clients["municipality"] = [x[1] for x in loc]
    clients = clients.merge(fin, on="inn", how="left")

    OUT.mkdir(parents=True, exist_ok=True)
    companies.to_parquet(OUT / f"companies_{a.region}.parquet", index=False)
    clients.to_parquet(OUT / f"clients_{a.region}.parquet", index=False)
    clients.to_csv(OUT / f"clients_{a.region}.csv", index=False, encoding="utf-8-sig")

    inc_cols = sorted(c for c in companies.columns if c.startswith("income_2"))
    meta = {
        "region": a.region,
        "msp_release": cur_date,
        "msp_prev_release": prev_date,
        "companies": len(companies),
        "companies_by_kind": companies.kind.value_counts().to_dict(),
        "bound_to_oktmo": int(companies.oktmo.notna().sum()),
        "rtk_clients_in_release": int(companies.is_rtk_client.sum()),
        "new_in_release": int(companies.new_in_release.sum()),
        "left_since_prev": len(prev_inns - cur_inns),
        "with_income": int(companies[inc_cols[-1]].notna().sum()) if inc_cols else 0,
        "clients_total": len(clients),
        "clients_by_status": clients.msp_status.value_counts().to_dict(),
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    (OUT / f"radar_{a.region}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
