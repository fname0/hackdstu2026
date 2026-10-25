"""Find project-specific construction contracts in EIS with cached, conservative matching.

One request at a time; a customer match alone never confirms a construction stage.
Run locally (EIS may reject hosting IPs): python -m backend.etl.gov_procurement
"""
import argparse
import hashlib
import html as htmlmod
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/gov_invest/details"
SEED = ROOT / "data/seed/invest_gov"
SITE = "https://zakupki.gov.ru"
CTX = ssl.create_default_context()
CTX.load_verify_locations(ROOT / "backend/etl/certs/russian_trusted_root_ca.pem")
STOP = set("капитальный капитального капитальному капитальное капитальные капитальных ремонт ремонта ремонту ремонтом выборочный выборочного комплексный комплексного текущий строительство строительства строительству реконструкция реконструкции здание здания зданий зданию корпуса корпус литер литера расположенного расположенной расположенных расположенное адресу адрес области область ростовская ростовской ростовском ростовского российская федерация муниципального муниципальное муниципальной муниципальных района район город города улица улицы улицу проспект переулок помещение помещений территории территория выполнение работ работы работа устройство устройства обустройство обустройства благоустройство благоустройства оснащение оснащения установка установки монтаж монтажа спортивной спортивного спортивных спортивная площадки площадок площадка футбольного покрытия покрытий образовательного образовательной общеобразовательного общеобразовательной учреждение учреждения бюджетное бюджетного казенное казенного автономное автономного государственное государственного дополнительного образования специальной средняя средней основная основной общего дошкольного детский детского детские детских кровли кровель кровлю крыши фасада фасадов водоснабжения отопления системы систем обеспечения школ школы школу школа школьного школьной сооружений сооружения сооружение начальной начального сад детскому сада саду садов расположены здании органа имени именины лит гбпоу гапоу гкоу гбоу мбоу мбдоу маоу мкдоу мбу мау гбу гку фгбу фгбоу гау мку моу доо сош оош дош сш сшор дюсш детсад техникума колледжа гбоу гбпоу инв дом дск учреждений находящихся ростов дон дону донской после включая части объектов объекта объект утверждение кпу право санитарных затрат наличия установки применение применяется числе в том числе новый новых новая обновление технического технической технических средств занятия занятий закупка закупки собственность собственности".split())
FAMILIES = {
    "roof": r"кровл|крыш|чердак",
    "facade": r"фасад|отмостк",
    "windows": r"окон|окна|оконн|дверн",
    "heating": r"отоплен|теплоснабж|теплотрас|котельн",
    "security": r"видеонаблюден|контрол.{0,30}доступ|огражден",
    "site": r"площадк|беговы.{0,10}дорож|футбольн.{0,10}пол|стадион|благоустройств|тротуар",
    "gym": r"спортивн.{0,8}зал|спортзал",
}


def norm(s):
    return re.sub(r"[^а-яa-z0-9]+", " ", str(s or "").lower().replace("ё", "е")).strip()


def tokens(s):
    return {t for t in norm(s).split() if len(t) >= 4 and t not in STOP and not t.isdigit()}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def parse_list(page):
    doc = html.fromstring(page)
    result = []
    for b in doc.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," search-registry-entry-block ")]'):
        links = b.xpath('.//a[contains(@href,"reestrNumber=")]')
        if not links:
            continue
        number = re.search(r"reestrNumber=(\d+)", links[0].get("href", "")).group(1)
        customers = b.xpath('.//a[contains(@href,"organizationId=")]')
        subject_nodes = b.xpath('.//div[contains(@class,"lots-wrap-content__body__val") and preceding-sibling::div[contains(.,"Объекты закупки")]]')
        if not subject_nodes:
            subject_nodes = b.xpath('.//div[contains(@class,"lots-wrap-content__body__val") and preceding-sibling::div[contains(.,"Объект закупки")]]')
        subject = clean(subject_nodes[0].text_content()) if subject_nodes else ""
        if subject_nodes:
            tips = subject_nodes[0].xpath('.//@data-tooltip')
            if tips:
                subject = clean(html.fromstring(tips[0]).text_content())
        dates = {}
        for label in b.xpath('.//div[contains(@class,"data-block__title")]'):
            nxt = label.getnext()
            if nxt is not None:
                dates[clean(label.text_content())] = clean(nxt.text_content())
        status = b.xpath('.//div[contains(@class,"registry-entry__header-mid__title")]')
        prices = b.xpath('.//*[contains(@class,"price-block__value")]')
        price = re.sub(r"[^\d,.]", "", prices[0].text_content()) if prices else ""
        result.append({
            "number": number, "url": f"{SITE}/epz/contract/contractCard/common-info.html?reestrNumber={number}",
            "customer_inn": number[1:11] if len(number) == 19 else None,
            "customer_name": clean(customers[0].text_content()) if customers else None,
            "subject": subject, "status": clean(status[0].text_content()) if status else "",
            "signed": dates.get("Заключение контракта"), "finish": dates.get("Срок исполнения"),
            "updated": dates.get("Обновлен контракт в реестре контрактов"),
            "price_rub": float(price.replace(",", ".")) if re.fullmatch(r"\d+[,.]\d+", price) else None,
        })
    return result


def fetch(query, region="61", page=1, pause=1.7):
    ident = hashlib.sha256(f"{region}|{query}|{page}".encode()).hexdigest()[:20]
    path = RAW / "search" / f"{ident}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if path.with_suffix(".html").exists():
            cached["items"] = parse_list(path.with_suffix(".html").read_text(encoding="utf-8"))
        return cached
    q = {"fz44": "on", "contractStageList": "0,1,2,3", "customerPlace": f"{region}000000000",
         "customerPlaceCodes": f"{region}000000000", "morphology": "on", "searchString": query,
         "recordsPerPage": "_50", "pageNumber": page, "sortBy": "UPDATE_DATE", "sortDirection": "false"}
    url = f"{SITE}/epz/contract/search/results.html?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ru"})
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=35) as response:
            body = response.read().decode("utf-8", "replace")
        rows = parse_list(body)
        if not rows and 'Реестр контрактов' not in body:
            raise ValueError("EIS response is not a registry page")
        result = {"query": query, "url": url, "fetched_at": datetime.now(timezone.utc).isoformat(), "items": rows}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".html").write_text(body, encoding="utf-8")
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        time.sleep(pause)


def family(title):
    return {k for k, pattern in FAMILIES.items() if re.search(pattern, title.lower())}


def match(project, contract, frequencies):
    title, subject = project["title"], contract["subject"]
    if not contract.get("signed") or datetime.strptime(contract["signed"], "%d.%m.%Y").year < 2022:
        return None
    if not subject or not re.search(r"ремонт|строительств|реконструкц|устройство|обустройств|благоустройств|монтаж", subject, re.I):
        return None
    if not re.match(r'^[«"\s]*(?:выполнени[ея]\s+(?:работ|проектных|строительно)|капитальн|текущ|выборочн|комплексн|строительств|реконструкц|разработк|устройств|обустройств|благоустройств|реставрац|монтаж|работы)', subject, re.I):
        return None
    if "капитальн" in title.lower() and re.search(r"текущ.{0,12}ремонт", subject, re.I) and "капитальн" not in subject.lower():
        return None
    # Supplies, supervision and design do not establish execution of the building work.
    is_design = bool(re.search(r"разработк.{0,35}(документац|проект|псд)|проектн.{0,25}изыскательск", subject, re.I))
    if re.search(r"строительн.{0,12}контрол|авторск.{0,10}надзор|экспертиз|техническ.{0,12}надзор|поставка", subject, re.I):
        return None
    school = r"школ|\bсош\b|\bоош\b|гимнази|лице[йя]"
    nursery = r"детск.{0,8}сад|дошкольн|\bмбдоу\b"
    if re.search(school, title, re.I) and not re.search(school, subject, re.I):
        return None
    if re.search(nursery, title, re.I) and not re.search(nursery, subject, re.I):
        return None
    if re.search(r"автомобильн.{0,8}дорог|дорожн.{0,8}покрыт", subject, re.I) and not re.search(r"дорог|дорож", title, re.I):
        return None
    def house(s):
        s = re.sub(r"[‘'`]л\.", "ул.", s.lower())
        address = re.split(r"\bул\.\s*|\bул\s+|улиц[аыеу]\s|проспект\s|\bпр\.\s*|\bпер\.\s*", s)
        if len(address) < 2:
            return None
        numbers = re.findall(r"(?:\bд(?:ом)?[.,\s№]+|,\s*)(\d{1,4}(?:[/-]\d+)?\s*[а-яa-z]?)\b", address[-1])
        return re.sub(r"\s+", "", numbers[0]) if numbers else None
    if house(title) and house(subject) and house(title) != house(subject):
        return None
    floors_a = set(re.findall(r"(\d+)\s*этаж", title, re.I))
    floors_b = set(re.findall(r"(\d+)\s*этаж", subject, re.I))
    if floors_a and floors_b and not floors_a & floors_b:
        return None
    a, b = tokens(title), tokens(subject + " " + (contract["customer_name"] or ""))
    def stem(t):
        return t[:max(5, len(t)-3)] if len(t) > 6 else t
    matched = {x for x in a if any(stem(x) == stem(y) or x == y for y in b)}
    if len(matched) < 2:
        return None
    weights = {x: 1 + math.log(386 / (1 + frequencies[x])) for x in a}
    score = sum(weights[x] for x in matched) / max(1, sum(weights.values()))
    same_inn = bool(project.get("beneficiary_inn") and project["beneficiary_inn"] == contract["customer_inn"])
    pf, cf = family(title), family(subject)
    if not is_design and pf != cf:
        return None
    minimum = .67 if same_inn else .78
    if score < minimum:
        return None
    # Distinct school/kindergarten numbers must agree if present in both texts.
    nums_a = set(re.findall(r"№\s*(\d+)", title))
    nums_b = set(re.findall(r"№\s*(\d+)", subject + " " + (contract["customer_name"] or "")))
    if nums_a and nums_b and not nums_a & nums_b:
        return None
    return {**contract, "score": round(score, 4), "matched_tokens": sorted(matched), "is_design": is_design}


def query_for(project, frequencies):
    ts = tokens(project["title"])
    candidates = sorted(ts, key=lambda t: (frequencies[t], -len(t), t))
    # Prefer distinctive establishment names; rare street/settlement words work for unnamed sites.
    quoted = re.findall(r'["«]([^"»]+)["»]', project["title"])
    preferred = [t for s in quoted for t in norm(s).split() if len(t) >= 4 and t not in STOP]
    rare = preferred[:1] or candidates[:1]
    others = [x for x in candidates if x not in rare]
    if others:
        rare.append(others[0])
    verb = "ремонт" if "ремонт" in project["title"].lower() else "строительство" if "строительств" in project["title"].lower() else ""
    return " ".join([verb] + rare).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pause", type=float, default=1.7)
    parser.add_argument("--offline", action="store_true", help="Reparse and match cached searches without network requests")
    args = parser.parse_args()
    projects = json.loads((SEED / "projects_gov_61.json").read_text(encoding="utf-8"))
    frequencies = Counter(t for p in projects for t in tokens(p["title"]))
    results_path = SEED / ("procurement_reviewed_61.json" if args.offline else "procurement_61.json")
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    todo = sorted(projects, key=lambda p: (not p["is_active"], not bool(p["beneficiary_inn"]), p["work_type"] == "иные работы"))
    if args.limit:
        todo = todo[:args.limit]
    blocked = 0
    for index, p in enumerate(todo, 1):
        query = query_for(p, frequencies)
        try:
            if args.offline:
                ident = hashlib.sha256(f"61|{query}|1".encode()).hexdigest()[:20]
                if not (RAW / "search" / f"{ident}.json").exists():
                    continue
            response = fetch(query, pause=args.pause)
            candidates = [m for c in response["items"] if (m := match(p, c, frequencies))]
            generic = [c for c in response["items"] if c.get("signed") and int(c["signed"][-4:]) >= 2022
                       and re.search(r"выполнение работ по (?:капитальному ремонту|строительству|реконструкции) объекта капитального строительства", c["subject"], re.I)]
            candidates.sort(key=lambda c: (datetime.strptime(c["signed"], "%d.%m.%Y") if c.get("signed") else datetime.min, c["score"]), reverse=True)
            results[p["project_id"]] = {"query": query, "searched_at": response["fetched_at"], "candidates": candidates,
                                        "match": candidates[0] if candidates else None, "verified": False,
                                        "card_candidates": generic[:5]}
            blocked = 0
        except Exception as e:
            print(f"FAIL {index} {type(e).__name__}: {e}", flush=True)
            blocked += 1
            if blocked >= 3:
                print("STOP: three consecutive failures; cached results preserved", flush=True)
                break
            continue
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{index}/{len(todo)} matches={sum(bool(r.get('match')) for r in results.values())} query={query} rows={len(response['items'])} matched={len(candidates)}", flush=True)
    print(json.dumps({"searched": len(results), "matched": sum(bool(r.get("match")) for r in results.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
