import argparse
import csv
import io
import json
import sys
import urllib.parse
import urllib.request

CASES = [
    ("район Багаевский, все компании", {"client": "all", "oktmo": "60605000"}),
    ("розница, доход от 10 млн, только потенциальные", {"client": "other", "industry": "Розница", "income_min": "10",
                                                      "include_no_income": "false"}),
    ("поиск по ИНН", {"client": "all", "q": "6103006206"}),
]

def get(base, path, params):
    with urllib.request.urlopen(f"{base}{path}?{urllib.parse.urlencode(params)}", timeout=60) as r:
        return r.read()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    failed = 0

    def check(ok, msg):
        nonlocal failed
        print(("  ✅ " if ok else "  ❌ ") + msg)
        failed += not ok

    for title, params in CASES:
        print(f"\n▶ {title}")
        listing = json.loads(get(a.base, "/api/radar/companies", {**params, "limit": 500}))
        raw = get(a.base, "/api/radar/export.csv", params)
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
        header, body = rows[0], rows[1:]
        check(raw.startswith(b"\xef\xbb\xbf"), "CSV с BOM (Excel откроет кириллицу)")
        check(len(body) == listing["total"], f"строк в CSV {len(body)} = компаний в списке {listing['total']}")
        inns = [r[0] for r in body]
        check(inns[: len(listing["items"])] == [x["inn"] for x in listing["items"]], "тот же порядок, что в списке (по потенциалу)")
        check(all(len(i) in (10, 12) and i.isdigit() for i in inns), "ИНН целые: 10/12 цифр, ведущие нули сохранены")
        num_cols = [header.index(c) for c in ("Доход 2025, ₽", "Рост дохода, %", "Потенциал (оценка)")]
        check(all("." not in r[c] for r in body for c in num_cols), "числа без точки (целые без «.0», дробные через запятую)")
        if params.get("industry"):
            check(all(r[header.index("Отрасль")] == params["industry"] for r in body), "все строки — выбранной отрасли")
        if params.get("income_min"):
            col = header.index("Доход 2025, ₽")
            check(all(r[col] and float(r[col].replace(",", ".")) >= float(params["income_min"]) * 1e6 for r in body),
                  "у всех доход не ниже фильтра")
        if params.get("client") == "other":
            check(all(r[header.index("Клиент РТК")] == "Нет" for r in body), "нет клиентов РТК в выгрузке «потенциальные»")

        amo = json.loads(get(a.base, "/api/radar/export/crm", {**params, "format": "amocrm"}))
        check(len(amo["companies"]) == len(body) == len(amo["notes"]), "amoCRM: компаний и примечаний столько же, сколько строк CSV")
        check(all(c["name"] and "_note" not in c for c in amo["companies"]), "amoCRM: у каждой компании есть name, нет нестандартных ключей")
        check(all(f["field_code"] == "ADDRESS" for c in amo["companies"] for f in c.get("custom_fields_values", [])),
              "amoCRM: только стандартное поле ADDRESS")
        bx = json.loads(get(a.base, "/api/radar/export/crm", {**params, "format": "bitrix24"}))
        check(len(bx) == len(body), "Bitrix24: вызовов crm.company.add столько же, сколько строк CSV")
        check(all(x["fields"]["COMPANY_TYPE"] in {"CUSTOMER", "OTHER"} for x in bx), "Bitrix24: тип компании — код справочника")
        check(all(x["fields"]["INDUSTRY"] in {"IT", "MANUFACTURING", "FINANCE", "GOVERNMENT", "DELIVERY", "ENTERTAINMENT",
                                             "CONSULTING", "OTHER"} for x in bx), "Bitrix24: сфера — код справочника")
        check([x["fields"]["ORIGIN_ID"] for x in bx] == inns, "Bitrix24: ORIGIN_ID = ИНН, порядок как в CSV")

    print(f"\n{'Все проверки пройдены' if not failed else f'Ошибок: {failed}'}")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
