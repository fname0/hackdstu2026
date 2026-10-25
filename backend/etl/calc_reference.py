"""ETL справочников калькулятора сделок (модуль 3) → data/seed/calc/reference.json + reference.meta.json

Источник — листы МОД3_Таб1…Таб4 из Хакатон_2026_фактура.xlsx (тематика: мониторинг и диспетчеризация зданий, IoT/АСУ):
  Таб1 — региональный коэффициент по федеральным округам;
  Таб2 — уровень проекта (базовый / продвинутый / экспертный);
  Таб3 — этапы работ в % от стоимости оборудования (ПИР, ПНР, шеф-монтаж);
  Таб4 — прайс компонентов: группа системы, ID, название, единица, базовая цена, коэффициент сложности.
Грязь: цена хранится строкой с пробелами («8 500»), проценты — строкой «10%». Листы ищем по колонкам, а не по имени.

Запуск: python -m backend.etl.calc_reference
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
XLSX = ROOT / "Хакатон_2026_фактура.xlsx"
OUT = ROOT / "data" / "seed" / "calc"

# Стабильные коды для API: подписи в xlsx длинные и могут поменяться
REGION_CODES = {"Центральный": "center", "Северо-Западный": "northwest", "Южный": "south",
                "Уральский": "ural_volga", "Дальневосточный": "far_east_siberia"}
LEVEL_CODES = {"Базовый": "basic", "Продвинутый": "advanced", "Экспертный": "expert"}
STAGE_CODES = {"Проектирование": "pir", "Пуско-наладка": "pnr", "Шеф-монтаж": "supervision"}
GROUP_CODES = {"el": "Электроснабжение", "ht": "Отопление", "ws": "Водоснабжение", "wo": "Водоотведение",
               "vn": "Вентиляция", "kd": "Кондиционирование", "gs": "Газоснабжение"}


def _num(v) -> float:
    """«8 500» / «10%» / 1.2 → число; неразрывные пробелы тоже убираем."""
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[\s %]", "", str(v)).replace(",", ".")
    return float(s)


def _code(label: str, codes: dict) -> str:
    for prefix, code in codes.items():
        if str(label).strip().startswith(prefix):
            return code
    raise ValueError(f"неизвестная строка справочника: {label!r}")


def _find(sheets: dict, *cols: str) -> tuple[str, pd.DataFrame]:
    for name, df in sheets.items():
        if all(any(c in str(h) for h in df.columns) for c in cols):
            return name, df
    raise ValueError(f"нет листа с колонками {cols}")


def build() -> dict:
    sheets = pd.read_excel(XLSX, sheet_name=None)
    s_reg, reg = _find(sheets, "Регион", "Коэффициент")
    s_lvl, lvl = _find(sheets, "Уровень проекта", "Коэффициент")
    s_stg, stg = _find(sheets, "Этап работ", "От стоимости")
    s_prc, prc = _find(sheets, "Компонент", "Базовая цена")

    regions = [{"code": _code(r.iloc[0], REGION_CODES), "label": str(r.iloc[0]).strip(), "value": _num(r.iloc[1]),
                "note": str(r.iloc[2]).strip()} for _, r in reg.iterrows()]
    levels = [{"code": _code(r.iloc[0], LEVEL_CODES), "label": str(r.iloc[0]).strip(), "value": _num(r.iloc[1]),
               "note": str(r.iloc[2]).strip()} for _, r in lvl.iterrows()]
    stages = [{"code": _code(r.iloc[0], STAGE_CODES), "label": str(r.iloc[0]).strip(), "value": _num(r.iloc[1]) / 100,
               "note": str(r.iloc[2]).strip()} for _, r in stg.iterrows()]
    items = []
    for _, r in prc.iterrows():
        item_id = str(r["ID"]).strip()
        items.append({"id": item_id, "group": str(r["Группа системы"]).strip(), "group_code": item_id.split("_")[0],
                      "name": str(r["Компонент (прибор/узел)"]).strip(), "unit": str(r["Ед. изм."]).strip(),
                      "price": _num(r["Базовая цена (руб.)"]), "complexity": _num(r["Коэф. сложности"])})

    # Проверки чистоты: всё, на что опирается формула, должно быть на месте
    assert len(regions) == 5 and len(levels) == 3 and len(stages) == 3, "справочники МОД3 изменились"
    assert len({i["id"] for i in items}) == len(items) == 20, "в прайсе дубли ID или не 20 позиций"
    assert all(i["group_code"] in GROUP_CODES and GROUP_CODES[i["group_code"]] == i["group"] for i in items), \
        "префикс ID не совпадает с группой системы"
    assert all(i["price"] > 0 and i["complexity"] >= 1 for i in items)

    meta = {"source": f"{XLSX.name}, листы {s_reg}, {s_lvl}, {s_stg}, {s_prc} (данные организаторов)",
            "built": date.today().isoformat(), "regions": len(regions), "levels": len(levels), "stages": len(stages),
            "items": len(items), "price_min": min(i["price"] for i in items), "price_max": max(i["price"] for i in items)}
    return {"regions": regions, "levels": levels, "stages": stages, "items": items, "meta": meta}


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ref = build()
    OUT.mkdir(parents=True, exist_ok=True)
    meta = ref.pop("meta")
    (OUT / "reference.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "reference.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
