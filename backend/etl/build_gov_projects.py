"""Prepare public investment objects for the common projects table, without guessing stages."""
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from backend.etl.gov_invest import key

ROOT = Path(__file__).resolve().parents[2]


def place_key(value):
    value = key(value).replace("р н", "район").replace("муниципальный район", "район").replace("городской округ", "")
    value = value.replace("ского района", "ский район").replace("ском районе", "ский район")
    return re.sub(r"^(?:город|г)\s+", "", value).strip()


def build(region="61"):
    raw = ROOT / "data/raw/gov_invest"
    seed = ROOT / "data/seed/invest_gov"
    records = json.loads((seed / f"education_{region}.json").read_text(encoding="utf-8"))
    extras = seed / f"additional_{region}.json"
    if extras.exists():
        records.extend(json.loads(extras.read_text(encoding="utf-8")))
    institutions = {r["inn"]: r for r in json.loads((raw / "institutions_db.json").read_text(encoding="utf-8"))}
    zones = json.loads((raw / "zones_db.json").read_text(encoding="utf-8"))
    grouped = defaultdict(list)
    for r in records:
        grouped[r["object_group_id"]].append(r)
    out = []
    for group, objects in grouped.items():
        # One object, multiple source lines: keep the conflicting amounts in provenance.
        r = max(objects, key=lambda x: (x["has_budget_current_or_future"], x["document_date"], x["source_row"]))
        inst = institutions.get(r.get("beneficiary_inn"))
        municipality = r["municipality"] or (inst or {}).get("municipality")
        text_key = place_key(r["title"])
        candidates = []
        for z in zones:
            zk = place_key(z["municipality"])
            mk = place_key(municipality or "")
            if zk and (zk == mk or f" {zk} " in f" {text_key} "):
                candidates.append(z)
        zone = candidates[0] if len(candidates) == 1 else None
        if not zone and inst:
            zone = next((z for z in zones if z["oktmo"] == inst.get("oktmo")), None)
        if zone:
            municipality = zone["municipality"]
        # Institution coordinates locate the beneficiary, not necessarily the work site.
        lat = (inst or {}).get("lat")
        lon = (inst or {}).get("lon")
        precision = "адрес учреждения, место работ уточняется" if lat is not None and lon is not None else "центр муниципалитета"
        if lat is None or lon is None:
            lat, lon = (zone or {}).get("lat"), (zone or {}).get("lon")
        active = any(o["has_budget_current_or_future"] or o.get("activity_unknown") for o in objects)
        amounts = {o["sum_mln"] for o in objects}
        total = next(iter(amounts)) if len(amounts) == 1 else None
        title = r["title"]
        t = title.lower()
        needs = []
        details = []
        # Roofs, facades and playgrounds alone are not evidence for an IT installation.
        whole_building = any(w in t for w in ["строительство", "реконструкция", "капитальный ремонт здания", "капитальный ремонт гб", "капитальный ремонт мбо"])
        limited = any(w in t for w in ["кровл", "крыши", "фасад", "отмостк", "спортивной площадк", "покрытия пола"])
        if whole_building and not limited:
            for n, label, offer in [("it", "ИТ-инфраструктура", "Обследование ЛВС и каналов связи при обновлении здания"),
                                     ("security", "Безопасность", "Проверить состав видеонаблюдения и контроля доступа в проекте")]:
                needs.append(n)
                details.append({"need": n, "label": label, "offer": offer, "quote": title})
        for n, pattern, label, offer in [
            ("security", r"видеонаблюден|контрол[ья].{0,35}доступ|охранн", "Безопасность", "Видеонаблюдение и контроль доступа по составу проекта"),
            ("it", r"локальн.{0,20}сет|структурирован.{0,20}кабель|интернет|слаботочн", "ИТ-инфраструктура", "ЛВС, каналы связи и слаботочные системы"),
            ("asutp", r"автоматизац|диспетчеризац|телеметр", "АСУ ТП и диспетчеризация", "Автоматизация и диспетчеризация инженерных систем"),
        ]:
            if re.search(pattern, t) and n not in needs:
                needs.append(n)
                details.append({"need": n, "label": label, "offer": offer, "quote": title})
        funded = any(o["has_budget_current_or_future"] for o in objects)
        score = 20 if funded and needs else 5 if funded else 0
        potential = round(total * .03, 6) if total is not None and needs else None
        category = r.get("program_label", "Развитие образования")
        sector_industry = r.get("industry_label", "Образование")
        out.append({
            "project_id": f"gov-{region}-{group}", "source": "Госпрограммы РО", "url": r["url"],
            "region": region, "title": title, "initiator": r.get("program_executor") or "Заказчик уточняется",
            "initiators": r.get("program_executor") or "Заказчик уточняется", "initiator_inn": None,
            "client_status": "не определён", "is_interregional": False, "is_key": False,
            "in_organizers_sample": False, "mo_raw": municipality, "municipality": municipality,
            "oktmo": (zone or {}).get("oktmo"), "curator": r.get("program_executor"),
            "stage": "стадия не подтверждена", "site_status": "актуальность уточняется" if r.get("activity_unknown") else "есть плановое финансирование" if active else "план прошлых лет",
            "start_year": None, "finish_year": r["finish_year"], "months_to_launch": None,
            "sales_window": "Срок из госпрограммы - план; стадию и закупки нужно уточнить",
            "sum_mln": total, "jobs": None, "industry": sector_industry,
            "industry_reason": f"Объект госпрограммы «{category}»", "needs": needs, "needs_detail": details,
            "it_share": .03 if needs else None, "rtk_potential_mln": potential,
            "rtk_potential_is_estimate": True, "hot_score": score,
            "hot_factors": {"плановое финансирование": score},
            "lat": float(lat) if lat is not None else None, "lon": float(lon) if lon is not None else None,
            "location_precision": precision if lat is not None else "место не определено",
            "address_from_text": (inst or {}).get("address"),
            "match_method": "инициатор не сопоставлен; получатель хранится отдельно",
            "sector": "government", "beneficiary_inn": r.get("beneficiary_inn"),
            "beneficiary_name": (inst or {}).get("name"), "program_executor": r.get("program_executor"),
            "work_type": r["work_type"], "document_date": r["document_date"], "is_active": active,
            "source_detail": {"program": category, "rows": [o["source_row"] for o in objects],
                "source_objects": objects, "sum_conflict": len(amounts) > 1,
                "coverage": r["coverage"], "stage_confirmed": False,
                "beneficiary_match_method": r.get("beneficiary_match_method"),
                "needs_basis": "гипотеза по виду работ; не подтвержденная закупка",
                "location_note": precision},
            "modify_date": r["document_date"], "create_date": None,
        })
    procurement = seed / f"procurement_reviewed_{region}.json"
    if procurement.exists():
        from backend.etl.gov_project_details import apply
        out = apply(out, json.loads(procurement.read_text(encoding="utf-8")))
    events_path = Path(__file__).with_name("gov_stage_events.json")
    if events_path.exists():
        events = json.loads(events_path.read_text(encoding="utf-8"))
        for p in out:
            event = events.get(p["project_id"])
            if not event:
                continue
            p.update(stage="работы завершены", is_active=False, hot_score=0, hot_factors={"контракт на исполнении": 0},
                     stage_basis=f"{event['publisher']}: корпус открыт после капитального ремонта {event['date']}; статус ЕИС может отставать от фактического события",
                     stage_checked_at=event["checked_on"], sales_window="Корпус открыт после ремонта - возможны эксплуатация и обслуживание, а не продажа на этапе стройки")
            p["source_detail"].update(stage_confirmed=True, stage_event=event, stage_basis_type="reported_opening")
    destination = seed / f"projects_gov_{region}.json"
    destination.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"projects": len(out), "active": sum(r["is_active"] for r in out),
                      "mapped": sum(r["lat"] is not None for r in out), "path": str(destination)}, ensure_ascii=False))
    return out


if __name__ == "__main__":
    build()
