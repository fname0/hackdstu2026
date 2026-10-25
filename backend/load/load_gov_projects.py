"""Idempotent additive import of public investment projects; existing projects are preserved."""
import json
import os
from pathlib import Path

from sqlalchemy import text
from backend.load.load_radar import engine

ROOT = Path(__file__).resolve().parents[2]
EXTRA_COLUMNS = {
    "sector": "text NOT NULL DEFAULT 'private'", "beneficiary_inn": "text", "beneficiary_name": "text",
    "program_executor": "text", "work_type": "text", "document_date": "date", "source_detail": "jsonb",
    "customer_name": "text", "customer_inn": "text", "contract_number": "text", "contract_status": "text",
    "contract_signed": "date", "contract_finish": "date", "contract_amount_rub": "double precision",
    "contractor_name": "text", "contractor_inn": "text", "stage_basis": "text", "stage_evidence_url": "text",
    "stage_checked_at": "date",
    "contract_work_address": "text",
}


def load(con, region="61"):
    for column, kind in EXTRA_COLUMNS.items():
        con.execute(text(f"ALTER TABLE projects ADD COLUMN IF NOT EXISTS {column} {kind}"))
    has_institutions = con.execute(text("SELECT to_regclass('institutions') IS NOT NULL")).scalar()
    institutional_match = "EXISTS (SELECT 1 FROM institutions i WHERE i.inn = p.initiator_inn)" if has_institutions else "false"
    con.execute(text(f"""UPDATE projects p SET sector = 'government' WHERE p.sector <> 'government' AND
        ({institutional_match}
         OR p.initiator ~* '\\m(ГБУ|ГБОУ|ГБПОУ|ГКОУ|МБОУ|МБДОУ|ФГБУ|ФГБОУ|ФГАОУ|МКУ|ГКУ|МАУ|МБУ|ГАУ|ГАПОУ|ФКУ|МУП|ГУП|ФГУП)\\M'
         OR p.initiator ~* '^(администрация|министерство)\\s')"""))
    source = ROOT / f"data/seed/invest_gov/projects_gov_{region}.json"
    if not source.exists():
        return {"added": 0, "note": "government seed not found"}
    objects = json.loads(source.read_text(encoding="utf-8"))
    if not objects or len({r["project_id"] for r in objects}) != len(objects):
        raise ValueError("Empty or duplicate government project IDs")
    columns = set(con.execute(text("SELECT * FROM projects LIMIT 0")).keys()) - {"geom"}
    con.execute(text("DELETE FROM projects WHERE project_id LIKE :prefix"), {"prefix": f"gov-{region}-%"})
    for original in objects:
        r = {k: v for k, v in original.items() if k in columns}
        for col in ["needs_detail", "hot_factors", "source_detail"]:
            r[col] = json.dumps(r[col], ensure_ascii=False)
        keys = list(r)
        values = [f"CAST(:{k} AS jsonb)" if k in {"needs_detail", "hot_factors", "source_detail"}
                  else f"CAST(:{k} AS date)" if k in {"document_date", "contract_signed", "contract_finish", "stage_checked_at"} else f":{k}" for k in keys]
        con.execute(text(f"INSERT INTO projects ({','.join(keys)}) VALUES ({','.join(values)})"), r)
    con.execute(text("UPDATE projects SET geom = ST_SetSRID(ST_MakePoint(lon, lat),4326) WHERE project_id LIKE :prefix AND lat IS NOT NULL AND lon IS NOT NULL"), {"prefix": f"gov-{region}-%"})
    con.execute(text("CREATE INDEX IF NOT EXISTS projects_sector_idx ON projects (sector)"))
    con.execute(text("DELETE FROM meta WHERE name = 'invest_gov'"))
    con.execute(text("INSERT INTO meta(name,data) VALUES ('invest_gov',:data)"), {"data": json.dumps({
        "projects": len(objects), "active": sum(r["is_active"] for r in objects),
        "sources": sorted({r["url"] for r in objects}), "partial_coverage": True}, ensure_ascii=False)})
    return {"added": len(objects), "active": sum(r["is_active"] for r in objects)}


def main():
    with engine().begin() as con:
        print(json.dumps(load(con, os.environ.get("REGION", "61")), ensure_ascii=False))


if __name__ == "__main__":
    main()
