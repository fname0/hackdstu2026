"""Контракты госсектора на связь → data/seed/gov/contracts_<регион>.* (для слоя «Госсектор» радара)

Вход: data/raw/zakupki/contracts_<регион>.csv (backend/etl/zakupki_contracts.py: реестр контрактов ЕИС, 44-ФЗ,
поиск по фразам предмета, поставщики — из карточек; на 25.10.2026 карточки открылись у 1141 из 1763 контрактов,
остальные ЕИС закрыл антиботом — у них поставщик неизвестен, это видно в данных).

Шаги:
  1) убираем не телеком: почтовая и курьерская связь, спецсвязь, фельдъегерская служба (фраза «услуги связи»
     ловит и их) — по ИНН поставщика и словам в предмете; и контракты, где слова фразы стоят врозь («перевозка
     в связи с ремонтом»): в предмете должно быть про связь, интернет, телефонию, каналы или видеонаблюдение;
  2) вид услуги по предмету: интернет, телефония, каналы и передача данных, видеонаблюдение, мобильная связь;
  3) поставщик-оператор: Ростелеком, МТС, МегаФон, Билайн, Т2 или «другой»;
  4) действует ли контракт на дату расчёта и «окно продаж» — контракт не с Ростелекомом кончается в ближайшие
     6 месяцев: к новой закупке учреждения нужно успеть с предложением.

Запуск: python -m backend.etl.contracts --region 61 [--today 2026-10-25]
"""
import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "zakupki"
OUT = ROOT / "data" / "seed" / "gov"

RTK_INN = "7707049388"
OPERATORS = {RTK_INN: "Ростелеком", "7740000076": "МТС", "7812014560": "МегаФон", "7713076301": "Билайн",
             "7743895280": "Т2", "7707083893": "Сбербанк"}
# Не телеком: почта, спецсвязь, фельдъегеря, курьеры
NOT_TELECOM_INN = {"7724490000", "9102012001", "7717043113", "6164048210"}
NOT_TELECOM = re.compile(r"почтов|фельдъегер|специальной связи|спецсвяз|курьер|экспресс-доставк|пересылк", re.I)
# Поиск ЕИС находит слова фразы в любом месте предмета («услуг по перевозке … в связи с закрытием»):
# оставляем только предмет, где действительно связь, — или контракт с известным оператором связи
TELECOM = re.compile(r"связ|интернет|телефон|телематич|передач\w* данных|канал\w* связ|видеонаблюд|радиотелефон|телеком|"
                     r"ip-?тв|цифров\w* телевид|vpn|wi-?fi", re.I)

SERVICES = [  # (вид, слова в предмете); первый подходящий
    ("Видеонаблюдение", r"видеонаблюд"),
    ("Мобильная связь", r"подвижной радиотелефонной|сотов|мобильн"),
    ("Каналы и передача данных", r"передач\w* данных|канал\w* связи|vpn|защищ\w* сет"),
    ("Интернет", r"интернет|телематическ"),
    ("Телефония", r"телефон|местной|междугородн|внутризонов"),
]


def service(subject: str) -> str:
    s = subject or ""
    for name, rx in SERVICES:
        if re.search(rx, s, re.I):
            return name
    return "Связь (прочее)"


def parse_date(s):
    try:
        return datetime.strptime(str(s).strip(), "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="61")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--window-months", type=int, default=6)
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    today = date.fromisoformat(a.today)

    d = pd.read_csv(RAW / f"contracts_{a.region}.csv", sep=";", dtype=str)
    total = len(d)
    d["price"] = pd.to_numeric(d.price, errors="coerce")
    subj = d.subject_card.fillna(d.subject).fillna("")
    clean_subj = subj.str.replace(r"в связи с", " ", case=False, regex=True)
    off_topic = ~clean_subj.str.contains(TELECOM) & ~d.supplier_inn.isin(OPERATORS.keys())
    not_tel = (d.supplier_inn.isin(NOT_TELECOM_INN) | subj.str.contains(NOT_TELECOM)
               | d.supplier.fillna("").str.contains(NOT_TELECOM) | off_topic)
    d = d[~not_tel].copy()
    d["subject"] = subj[~not_tel]
    d["service"] = d.subject.map(service)
    d["supplier_known"] = d.supplier_inn.notna()
    d["operator"] = d.supplier_inn.map(OPERATORS).where(d.supplier_known, None)
    d.loc[d.supplier_known & d.operator.isna(), "operator"] = "другой"
    d["is_rtk"] = d.supplier_inn.eq(RTK_INN)
    d["finish_date"] = [parse_date(x) or parse_date(y) for x, y in zip(d.finish_card, d.finish)]
    d["signed_date"] = d.signed.map(parse_date)
    d["is_active"] = d.finish_date.map(lambda x: x is not None and x >= today)
    months = d.finish_date.map(lambda x: None if x is None else (x.year - today.year) * 12 + x.month - today.month)
    d["months_left"] = months
    # окно продаж: контракт известного поставщика (не РТК) кончается в ближайшие N месяцев
    d["sales_window"] = d.supplier_known & ~d.is_rtk & d.is_active & months.le(a.window_months)
    d["source"] = "ЕИС zakupki.gov.ru, реестр контрактов 44-ФЗ"
    keep = ["reestr_number", "customer_inn", "customer", "subject", "service", "price", "signed_date", "finish_date",
            "is_active", "months_left", "supplier", "supplier_inn", "supplier_kpp", "operator", "is_rtk",
            "supplier_known", "sales_window", "source"]
    d = d[keep].sort_values("finish_date")

    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"contracts_{a.region}"
    d.to_parquet(OUT / f"{stem}.parquet", index=False)
    d.to_csv(OUT / f"{stem}.csv", index=False, encoding="utf-8-sig")
    k = d[d.supplier_known]
    meta = {
        "source": "ЕИС zakupki.gov.ru, реестр контрактов 44-ФЗ, заключены с 01.01.2024", "region": a.region, "today": a.today,
        "contracts_raw": total, "not_telecom_removed": int(not_tel.sum()), "off_topic_removed": int(off_topic.sum()), "contracts": len(d),
        "with_supplier": len(k), "customers": int(d.customer_inn.nunique()),
        "rtk_share_by_count_pct": round(k.is_rtk.mean() * 100, 1) if len(k) else None,
        "rtk_share_by_sum_pct": round(k[k.is_rtk].price.sum() / k.price.sum() * 100, 1) if len(k) else None,
        "by_operator": k.operator.value_counts().to_dict(), "by_service": d.service.value_counts().to_dict(),
        "active": int(d.is_active.sum()), "sales_window": int(d.sales_window.sum()),
        "sales_window_sum_rub": round(float(d[d.sales_window].price.sum())),
        "note": "поставщик известен только у контрактов, чьи карточки удалось открыть (остальные ЕИС закрыл антиботом)",
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    (OUT / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
