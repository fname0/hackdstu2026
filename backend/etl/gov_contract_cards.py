"""Verify selected contract cards and enrich suppliers, without guessing customer roles."""
import argparse
import json
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from lxml import html

from backend.etl.gov_procurement import RAW, SEED, CTX, SITE, fetch as fetch_search, norm, match, tokens
from backend.etl.zakupki_contracts import parse_card


def parse_full(body):
    record = parse_card(body)
    record["work_address"] = None
    doc = html.fromstring(body)
    for heading in doc.xpath('//h2'):
        if "месте поставки" in heading.text_content():
            values = heading.getparent().xpath('.//span[contains(@class,"section__info")]')
            if values:
                record["work_address"] = " ".join(values[0].text_content().split())
        if "Информация о заказчике" not in heading.text_content():
            continue
        block = heading.getparent()
        for section in block.xpath('.//section'):
            labels = section.xpath('./span[contains(@class,"section__title")]')
            values = section.xpath('./span[contains(@class,"section__info")]')
            if not labels or not values:
                continue
            label = " ".join(labels[0].text_content().split())
            value = " ".join(values[0].text_content().split())
            if label == "ИНН":
                record["customer_inn"] = value
            elif label == "Полное наименование заказчика":
                record["customer_name"] = value
    return record


def fetch(number, pause):
    path = RAW / "cards" / f"{number}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if (not cached.get("customer_inn") or "work_address" not in cached) and path.with_suffix(".html").exists():
            cached.update(parse_full(path.with_suffix(".html").read_text(encoding="utf-8")))
            path.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
        return cached
    url = f"{SITE}/epz/contract/contractCard/common-info.html?reestrNumber={number}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, context=CTX, timeout=35) as response:
            body = response.read().decode("utf-8", "replace")
        if number not in body or "Карточка контракта" not in body or "Информация о заказчике" not in body:
            raise ValueError("Unexpected EIS card")
        record = {**parse_full(body), "number": number, "url": url,
                  "fetched_at": datetime.now(timezone.utc).isoformat()}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".html").write_text(body, encoding="utf-8")
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return record
    finally:
        time.sleep(pause)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pause", type=float, default=1.7)
    parser.add_argument("--offline", action="store_true", help="Use cached cards and reviewed full-text registry rows only")
    args = parser.parse_args()
    path = SEED / "procurement_reviewed_61.json"
    results = json.loads(path.read_text(encoding="utf-8"))
    projects = {p["project_id"]: p for p in json.loads((SEED / "projects_gov_61.json").read_text(encoding="utf-8"))}
    frequencies = Counter(t for p in projects.values() for t in tokens(p["title"]))
    # Some list entries hide the real object behind a generic procurement name.
    # Read the full card and then apply the same address/work matching rules.
    for pid, r in results.items():
        for c in r.get("card_candidates", []):
            if args.offline and not (RAW / "cards" / f"{c['number']}.json").exists():
                continue
            try:
                card = fetch(c["number"], args.pause)
                full = {**c, "subject": card.get("subject_card") or c["subject"]}
                candidate = match(projects[pid], full, frequencies)
                if candidate:
                    r["candidates"].append(candidate)
            except Exception as e:
                print("GENERIC CARD", c["number"], type(e).__name__, flush=True)
        r["candidates"].sort(key=lambda c: (datetime.strptime(c["signed"], "%d.%m.%Y"), c["score"]), reverse=True)
        r["match"] = r["candidates"][0] if r["candidates"] else None
    # These contracts were discovered separately; their full card subject must equal
    # the programme object, not just contain a similar customer name.
    exact_cards = {"gov-61-50fa420c55a5afee": "3610200922923000002",
                   "gov-61-d088833caa2f8d5d": "2614800446324000006"}
    for pid, number in exact_cards.items():
        if pid not in projects:
            continue
        card = fetch(number, args.pause)
        if norm(card.get("subject_card")) != norm(projects[pid]["title"]):
            raise ValueError(f"Exact contract subject changed: {number}")
        search = fetch_search(number, pause=args.pause)
        c = next((x for x in search["items"] if x["number"] == number), None)
        if not c:
            continue
        c.update(subject=card["subject_card"], score=1.0, is_design=False, match_method="точное название объекта в полной карточке ЕИС")
        results[pid] = {"query": number, "searched_at": search["fetched_at"], "candidates": [c], "match": c, "verified": False}
    selected = [(pid, r) for pid, r in results.items() if r.get("match")]
    failures = 0
    for index, (pid, r) in enumerate(selected, 1):
        c = r["match"]
        try:
            if args.offline and not (RAW / "cards" / f"{c['number']}.json").exists():
                # A full-text registry row is itself an official source for customer,
                # subject, status, dates and price. It does not disclose the supplier.
                p = projects[pid]
                same_inn = bool(p.get("beneficiary_inn") and p["beneficiary_inn"] == c["customer_inn"])
                r["verified"] = c.get("score", 0) >= .9 or same_inn
                r["verification_level"] = "registry_full_text"
                r["supplier_unavailable_reason"] = "ЕИС вернула 403 на дальнейшие запросы полных карточек"
                path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                continue
            card = fetch(c["number"], args.pause)
            if card.get("customer_inn") != c["customer_inn"]:
                raise ValueError("Customer INN differs between list and full card")
            suppliers = card.get("suppliers") or []
            main_supplier = next((s for s in suppliers if s.get("inn")), suppliers[0] if suppliers else {})
            c.update(contractor_name=main_supplier.get("name"), contractor_inn=main_supplier.get("inn"),
                     finish_card=card.get("finish_card"), subject_short=card.get("subject_card"),
                     customer_name=card.get("customer_name") or c["customer_name"], suppliers=suppliers,
                     work_address=card.get("work_address"))
            r["verified"] = True
            r["verification_level"] = "full_contract_card"
            r["card_checked_at"] = card["fetched_at"]
            failures = 0
        except Exception as e:
            r["verified"] = False
            r["card_error"] = f"{type(e).__name__}: {e}"
            failures += 1
            print("FAIL", c["number"], r["card_error"], flush=True)
        path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{index}/{len(selected)} verified={sum(bool(x.get('verified')) for x in results.values())}", flush=True)
        if failures >= 3:
            print("STOP: three card failures, results preserved", flush=True)
            break


if __name__ == "__main__":
    main()
