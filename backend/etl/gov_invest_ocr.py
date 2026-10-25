"""Normalize reviewed OCR staging rows from official scanned municipal programmes.

Run scripts/ocr_gov_tables.py on the official PDFs first. Amounts and dates are
deliberately left unknown: title OCR alone cannot confirm a budget or a stage.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from backend.etl.gov_invest import enrich, key, work_type
from backend.etl.build_gov_projects import place_key

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "education": ("6100202608260013", "680", "Развитие образования", "Образование"),
    "sports": ("6100202608260003", "671", "Развитие физической культуры и спорта", "Досуг и спорт"),
}


def main():
    raw = ROOT / "data/raw/gov_invest"
    seed = ROOT / "data/seed/invest_gov"
    zones = json.loads((raw / "zones_db.json").read_text(encoding="utf-8"))
    existing = json.loads((seed / "education_61.json").read_text(encoding="utf-8"))
    existing_rows = {r["source_row"] for r in existing if r["ownership"] == "municipal"}
    out, rejected = [], []
    for category, (number, act, program, industry) in SOURCES.items():
        path = raw / f"ocr_{category}/objects.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        municipality_by_prefix = defaultdict(Counter)
        for r in rows:
            title = place_key(r["title"])
            for z in zones:
                name = place_key(z["municipality"])
                if f" {name} " in f" {title} ":
                    municipality_by_prefix[".".join(r["source_row"].split(".")[:2])][z["municipality"]] += 1
        for r in rows:
            if category == "education" and r["source_row"] in existing_rows:
                continue
            title = r["title"].strip().rstrip(".")
            # Cut cells ending at the page edge and weak OCR stay out of production.
            if r["ocr_confidence"] < 88 or title.endswith(":") and not title.endswith("числе:"):
                rejected.append({**r, "reason": "слабое OCR или незавершенная ячейка"})
                continue
            title = re.sub(r",?\s*в том числе:?$", "", title, flags=re.I).strip()
            votes = municipality_by_prefix[".".join(r["source_row"].split(".")[:2])]
            municipality = votes.most_common(1)[0][0] if votes else None
            identity = f"61|{category}|municipal|{key(municipality or '')}|{key(title)}"
            out.append({
                "project_id": f"gov-ocr-{category}-{r['source_row']}",
                "object_group_id": hashlib.sha256(identity.encode()).hexdigest()[:16],
                "source_title_conflict": False, "region": "61", "source_row": r["source_row"],
                "ownership": "municipal", "title": title, "municipality": municipality,
                "work_type": work_type(title), "program_executor": None,
                "beneficiary_inn": None, "beneficiary_name": None, "beneficiary_match_method": None,
                "finish_year": None, "sum_mln": None,
                "annual_budget_thousand_rub": {str(y): None for y in range(2024, 2029)},
                "has_budget_current_or_future": False, "activity_unknown": True,
                "url": f"http://publication.pravo.gov.ru/file/pdf?eoNumber={number}#page={r['page']}",
                "document_date": "2026-08-25", "document_number": act,
                "source_appendix": 3 if category == "education" else 2,
                "coverage": "частичная выборка из полного официального PDF; название распознано OCR, суммы и стадии не подтверждены",
                "ocr_confidence": r["ocr_confidence"], "source_page": r["page"],
                "program_label": program, "industry_label": industry,
                "existing_project_id": None, "possible_duplicate_id": None,
            })
    enrich(out, raw)
    (seed / "additional_61.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (seed / "ocr_rejected_61.json").write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"accepted": len(out), "rejected": len(rejected),
                      "by_industry": dict(Counter(r["industry_label"] for r in out)),
                      "with_inn": sum(bool(r["beneficiary_inn"]) for r in out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
