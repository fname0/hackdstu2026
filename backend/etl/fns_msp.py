"""Шаг 1 ETL: Единый реестр МСП (ФНС, набор 7707329152-rsmp) → субъекты одного региона.

Архив читается прямо из zip, без распаковки: внутри ~7,5 тыс. XML по ~3 МБ (≈22,7 ГБ на всю РФ).
Файлы обрабатываются параллельно; файл без нужного кода региона отбрасывается без разбора XML.

Запуск из корня репо:
    python -m backend.etl.fns_msp data/raw/fns/rsmp_2026-10.zip --region 61
    python -m backend.etl.fns_msp data/raw/fns/rsmp_2026-10.zip --region 61 --limit 50   # быстрая проверка

Результат: data/seed/fns/msp_<регион>_<ГГГГ-ММ-ДД>.parquet (+ .csv для просмотра, + .meta.json).
"""
import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "seed" / "fns"

KIND = {"1": "ЮЛ", "2": "ИП", "3": "ИП (КФХ)"}  # 3 — глава крестьянского (фермерского) хозяйства
CATEGORY = {"1": "микро", "2": "малое", "3": "среднее"}


def _place(el):
    """«Тип Наим» элемента адреса (Район, Город, НаселПункт) или пустая строка."""
    if el is None:
        return ""
    return " ".join(x for x in (el.get("Тип", "").strip(), el.get("Наим", "").strip()) if x)


def _parse_doc(doc):
    ul, ip = doc.find("ОргВклМСП"), doc.find("ИПВклМСП")
    if ul is not None:
        inn, ogrn = ul.get("ИННЮЛ"), ul.get("ОГРН")
        name, short = ul.get("НаимОрг", ""), ul.get("НаимОргСокр", "")
    elif ip is not None:
        inn, ogrn = ip.get("ИННФЛ"), ip.get("ОГРНИП")
        fio = ip.find("ФИОИП")
        parts = [fio.get(k, "") for k in ("Фамилия", "Имя", "Отчество")] if fio is not None else []
        name = "ИП " + " ".join(p for p in parts if p)
        short = name
    else:
        return None

    mn = doc.find("СведМН")
    okved = doc.find("СвОКВЭД")
    main = okved.find("СвОКВЭДОсн") if okved is not None else None
    extra = [e.get("КодОКВЭД") for e in okved.findall("СвОКВЭДДоп")] if okved is not None else []
    staff = doc.get("ССЧР")

    return {
        "inn": inn,
        "ogrn": ogrn,
        "kind": KIND.get(doc.get("ВидСубМСП"), doc.get("ВидСубМСП")),
        "category": CATEGORY.get(doc.get("КатСубМСП"), doc.get("КатСубМСП")),
        "name": name,
        "name_short": short,
        "is_new": doc.get("ПризНовМСП") == "1",
        "is_social": doc.get("СведСоцПред") == "1",
        "msp_since": doc.get("ДатаВклМСП"),
        "staff": int(staff) if staff and staff.isdigit() else None,
        "region_code": mn.get("КодРегион") if mn is not None else None,
        "district": _place(mn.find("Район")) if mn is not None else "",
        "city": _place(mn.find("Город")) if mn is not None else "",
        "settlement": _place(mn.find("НаселПункт")) if mn is not None else "",
        "okved_main": main.get("КодОКВЭД") if main is not None else None,
        "okved_main_name": main.get("НаимОКВЭД") if main is not None else None,
        "okved_extra": ";".join(c for c in extra if c),
        "licenses": len(doc.findall("СвЛиценз")),
        "has_products": doc.find("СвПрод") is not None,
    }


def _parse_file(args):
    """Разбирает один XML из архива. Возвращает (записи региона, всего документов в файле, дата состояния)."""
    zip_path, name, region = args
    with zipfile.ZipFile(zip_path) as z:
        raw = z.read(name)
    marker = f'КодРегион="{region}"'.encode("utf-8")
    root = ET.fromstring(raw)
    docs = root.findall("Документ")
    state_date = docs[0].get("ДатаСост") if docs else None
    if marker not in raw:  # в файле нет ни одного субъекта региона
        return [], len(docs), state_date
    rows = []
    for doc in docs:
        mn = doc.find("СведМН")
        if mn is None or mn.get("КодРегион") != region:
            continue
        row = _parse_doc(doc)
        if row:
            rows.append(row)
    return rows, len(docs), state_date


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip", type=Path)
    ap.add_argument("--region", default="61")
    ap.add_argument("--limit", type=int, default=0, help="обработать только N файлов (проверка)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    with zipfile.ZipFile(a.zip) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".xml")]
    if a.limit:
        names = names[: a.limit]

    t0 = time.time()
    rows, total_docs, state_dates = [], 0, set()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        tasks = [(str(a.zip), n, a.region) for n in names]
        for i, (r, n_docs, sd) in enumerate(ex.map(_parse_file, tasks, chunksize=8), 1):
            rows.extend(r)
            total_docs += n_docs
            if sd:
                state_dates.add(sd)
            if i % 500 == 0 or i == len(names):
                print(f"  {i}/{len(names)} файлов · документов {total_docs:,} · регион {a.region}: {len(rows):,} · {time.time() - t0:.0f} с",
                      file=sys.stderr, flush=True)

    df = pd.DataFrame(rows)
    dup = int(df.duplicated("inn").sum()) if len(df) else 0
    df = df.drop_duplicates("inn")

    state = sorted(state_dates)[-1] if state_dates else "unknown"
    iso = datetime.strptime(state, "%d.%m.%Y").date().isoformat() if state != "unknown" else state
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"msp_{a.region}_{iso}" + ("_sample" if a.limit else "")
    df.to_parquet(OUT_DIR / f"{stem}.parquet", index=False)
    df.to_csv(OUT_DIR / f"{stem}.csv", index=False, encoding="utf-8-sig")

    meta = {
        "source": "ФНС России, Единый реестр субъектов МСП (7707329152-rsmp), nalog.gov.ru/opendata",
        "archive": a.zip.name,
        "state_date": state,
        "region": a.region,
        "files_processed": len(names),
        "documents_total": total_docs,
        "rows": len(df),
        "duplicates_dropped": dup,
        "by_kind": df["kind"].value_counts().to_dict() if len(df) else {},
        "by_category": df["category"].value_counts().to_dict() if len(df) else {},
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0),
    }
    (OUT_DIR / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
