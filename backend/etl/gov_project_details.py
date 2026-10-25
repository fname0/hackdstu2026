"""Merge verified EIS contracts into the government seed, preserving plan vs contract facts."""
from datetime import date, datetime, timedelta


def iso(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def apply(projects, searches):
    for p in projects:
        entry = searches.get(p["project_id"], {})
        c = entry.get("match")
        if not c or not entry.get("verified"):
            continue
        p.update(customer_name=c["customer_name"], customer_inn=c["customer_inn"],
                 contract_number=c["number"], contract_status=c["status"],
                 contract_signed=iso(c.get("signed")), contract_finish=iso(c.get("finish_card") or c.get("finish")),
                 contract_amount_rub=c.get("price_rub"), contractor_name=c.get("contractor_name"),
                 contractor_inn=c.get("contractor_inn"), stage_evidence_url=c["url"],
                 contract_work_address=c.get("work_address"),
                 stage_checked_at=entry["searched_at"][:10])
        source = p["source_detail"]
        source["procurement"] = c
        source["procurement_candidates"] = entry.get("candidates", [])[:5]
        source["stage_basis_type"] = "contract_registry"
        updated = c.get("updated") or "дата изменения не указана"
        changed = iso(c.get("updated")) or iso(c.get("signed"))
        fresh = bool(changed and date.fromisoformat(changed) >= date.today() - timedelta(days=365))
        conflicting_plan = source.get("sum_conflict") or bool(p.get("finish_year") and p["finish_year"] > date.today().year)
        if c["status"] == "Исполнение завершено" and not c.get("is_design") and not conflicting_plan:
            p.update(stage="работы завершены", is_active=False, hot_score=0,
                     hot_factors={"контракт на исполнении": 0},
                     sales_window="По ЕИС исполнение подходящего контракта завершено - проверьте наличие нового этапа")
            basis = "ЕИС: исполнение контракта на работы завершено; это не подтверждение ввода здания в эксплуатацию"
        elif c["status"] == "Исполнение" and not c.get("is_design") and fresh:
            p.update(stage="реализация", is_active=True,
                     hot_score=20 if p["needs"] else 5,
                     hot_factors={"контракт на исполнении": 20 if p["needs"] else 5})
            basis = "ЕИС: контракт на работы находится на исполнении; фактическая готовность объекта не опубликована"
        elif c.get("is_design") and c["status"] in {"Исполнение", "Исполнение завершено"} and fresh:
            p.update(stage="подготовка", is_active=True)
            basis = "Найден контракт на проектирование; переход к строительству пока не подтвержден"
        elif c["status"] == "Исполнение прекращено":
            basis = "Найден контракт с прекращенным исполнением; остановка всего проекта из этого не следует"
        elif c["status"] == "Исполнение завершено" and conflicting_plan:
            basis = "Контракт завершён, но в госпрограмме есть будущий срок или разные сметы; завершение всего проекта не подтверждено"
        elif not fresh:
            basis = "Заказчик известен из ЕИС, но запись не обновлялась больше года; текущая стадия требует уточнения"
        else:
            basis = "Заказчик подтвержден подходящим контрактом ЕИС; стадию проекта установить не удалось"
        p["stage_basis"] = basis + "; запись ЕИС обновлена " + updated
        source["stage_confirmed"] = p["stage"] != "стадия не подтверждена"
        source["stage_note"] = "Стадия по статусу контракта, не по обследованию площадки; срок контракта отделен от планового ввода"
        if p["stage"] == "реализация":
            p["sales_window"] = "По ЕИС контракт на работы на исполнении - состав ИТ и слаботочных систем уточните у заказчика"
        p["modify_date"] = entry["searched_at"]
    return projects
