"""Extract public education investment objects from the downloaded regional act.

This is a staging dataset, not an automatic production import. The downloaded
publication is incomplete; unknown completion dates, customers and stages stay null.
Run: python -m backend.etl.gov_invest [--region 61] [--year 2026]
"""
import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "https://base.garant.ru/414806409/53f89421bbdaf741eb2d1ecc4ddb4c33/"


def clean(value):
    return re.sub(r"\s+", " ", value).strip()


def key(value):
    return re.sub(r"[^а-яa-z0-9]+", " ", value.lower().replace("ё", "е")).strip()


def amount(value):
    s = clean(value).replace(" ", "").replace(",", ".")
    return float(s) if re.fullmatch(r"\d+(?:\.\d+)?", s) else None


def work_type(title):
    t = title.lower()
    if "проектн" in t and ("разработ" in t or "документац" in t):
        return "проектирование"
    for token, label in [("строительств", "строительство"), ("реконструкц", "реконструкция"),
                         ("реставрац", "реставрация"), ("капитальн", "капитальный ремонт")]:
        if token in t:
            return label
    return "иные работы"


def extract(path, region, year):
    doc = html.fromstring(path.read_bytes())
    section, municipality = None, None
    records = []
    for table in doc.xpath("//table"):
        rows = table.xpath("./tr|./tbody/tr")
        if not rows:
            continue
        header = clean(rows[0].text_content())
        if "Наименование инвестиционного проекта" in header:
            section = "regional" if "Ответственный исполнитель" in header else "municipal"
            municipality = None
        if section is None:
            continue
        for row in rows:
            cells = [clean(c.text_content()) for c in row.xpath("./td|./th")]
            if len(cells) == 1 and section == "municipal":
                m = re.fullmatch(r"\d+\.\d+\.\s*(.+)", cells[0])
                if m:
                    municipality = m.group(1)
            expected = 12 if section == "regional" else 10
            if len(cells) != expected or not re.fullmatch(r"\d+(?:\.\d+)+\.", cells[0]):
                continue
            offset = 2 if section == "regional" else 0
            if cells[3 + offset].lower() != "всего":
                continue
            title = cells[1]
            if title in {"Х", "X", "-", ""}:
                continue
            annual = {str(y): amount(v) for y, v in zip(range(2024, 2029), cells[5 + offset:])}
            finish = cells[4] if section == "regional" else None
            years = re.findall(r"\b20\d{2}\b", finish or "")
            identity = f"{region}|education|{section}|{key(title)}"
            records.append({
                "project_id": "gov-edu-" + hashlib.sha256((identity + "|" + cells[0]).encode()).hexdigest()[:16],
                "object_group_id": hashlib.sha256(identity.encode()).hexdigest()[:16],
                "source_title_conflict": False,
                "region": region, "source_row": cells[0], "ownership": section,
                "title": title, "municipality": municipality,
                "work_type": work_type(title), "program_executor": cells[2] if offset else None,
                "beneficiary_inn": None, "beneficiary_name": None,
                "beneficiary_match_method": None, "customer_inn": None,
                "initiator_inn": None, "stage": None,
                "expertise": cells[2 + offset], "finish_raw": finish,
                "finish_year": int(years[-1]) if years else None,
                "sum_mln": round(amount(cells[4 + offset]) / 1000, 7)
                if amount(cells[4 + offset]) is not None else None,
                "sum_kind": "сметная стоимость, не сумма контракта",
                "annual_budget_thousand_rub": annual,
                "has_budget_current_or_future": any(v is not None and v > 0 for y, v in annual.items() if int(y) >= year),
                "source": "Госпрограмма Ростовской области Развитие образования",
                "url": SOURCE, "document_date": "2026-08-25", "document_number": "680",
                "source_appendix": 2 if offset else 3,
                "coverage": "часть опубликованного документа; не полный реестр области",
                "existing_project_id": None, "possible_duplicate_id": None,
            })
    from collections import Counter
    groups = Counter(r["object_group_id"] for r in records)
    for r in records:
        r["source_title_conflict"] = groups[r["object_group_id"]] > 1
    ids = [r["project_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate project titles in source: review before export")
    if not records:
        raise ValueError("No investment rows found: source layout changed")
    return records


def enrich(records, raw):
    institutions = json.loads((raw / "institutions_db.json").read_text(encoding="utf-8")) if (raw / "institutions_db.json").exists() else []
    existing = json.loads((raw / "existing_projects_db.json").read_text(encoding="utf-8")) if (raw / "existing_projects_db.json").exists() else []
    from difflib import SequenceMatcher
    for r in records:
        title = key(r["title"])
        matches = {}
        for inst in institutions:
            for field in ["name", "name_short"]:
                name = key(inst.get(field) or "")
                # Whole normalized name with enough specificity, not fuzzy INN inference.
                if len(name) >= 18 and f" {name} " in f" {title} ":
                    matches[inst["inn"]] = inst
        if len(matches) == 1:
            inst = next(iter(matches.values()))
            r.update(beneficiary_inn=inst["inn"], beneficiary_name=inst["name"],
                     beneficiary_match_method="единственное полное/краткое название в тексте; bus.gov.ru")
        best, score = None, 0
        for p in existing:
            other = key(p["title"] or "")
            matcher = SequenceMatcher(None, title, other)
            if matcher.real_quick_ratio() < max(.8, score) or matcher.quick_ratio() < max(.8, score):
                continue
            s = matcher.ratio()
            if s > score:
                best, score = p, s
        if best and score == 1:
            r["existing_project_id"] = best["project_id"]
        elif best and score >= .8:
            r["possible_duplicate_id"] = best["project_id"]
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="61", choices=["61"])
    parser.add_argument("--year", default=2026, type=int)
    parser.add_argument("--download", action="store_true", help="Download the public source before parsing")
    args = parser.parse_args()
    raw = ROOT / "data/raw/gov_invest"
    source = raw / "education_2026-08-25.html"
    if args.download:
        import urllib.request
        raw.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            source.write_bytes(response.read())
    records = enrich(extract(source, args.region, args.year), raw)
    out = ROOT / "data/seed/invest_gov"
    out.mkdir(parents=True, exist_ok=True)
    stem = f"education_{args.region}"
    (out / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    shortlist = [r for r in records if r["has_budget_current_or_future"] and not r["existing_project_id"] and not r["source_title_conflict"]]
    for name, rows in [(stem, records), (stem + "_shortlist", shortlist)]:
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0]), delimiter=";")
            w.writeheader()
            for r in rows:
                w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v for k, v in r.items()})
    meta = {
        "source": SOURCE, "document_date": "2026-08-25",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "projects": len(records), "shortlist": len(shortlist),
        "matched_beneficiaries": sum(bool(r["beneficiary_inn"]) for r in records),
        "exact_existing": sum(bool(r["existing_project_id"]) for r in records),
        "possible_duplicates": sum(bool(r["possible_duplicate_id"]) for r in records),
        "regional": sum(r["ownership"] == "regional" for r in records),
        "municipal": sum(r["ownership"] == "municipal" for r in records),
        "unique_object_titles": len({r["object_group_id"] for r in records}),
        "conflicting_source_rows": sum(r["source_title_conflict"] for r in records),
        "limitations": [
            "Публикация обрывается в муниципальном перечне; покрытие неполное",
            "Это редакция от 25.08.2026, отсутствие последующих изменений не подтверждено",
            "ИНН учреждения-получателя не означает ИНН заказчика или инициатора",
            "Бюджетные ассигнования не доказывают фактическую стадию или незавершенность работ",
            "Капремонт, благоустройство и строительство выделены разными типами",
            "Нечеткие дубли требуют ручной проверки; суммы объектов не следует суммировать с итогами программы",
        ],
    }
    (out / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
