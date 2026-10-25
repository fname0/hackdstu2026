"""Контракты на услуги связи заказчиков региона из ЕИС (zakupki.gov.ru, 44-ФЗ) → data/raw/zakupki/

Зачем: у кого учреждения покупают связь (Ростелеком или конкурент), на какую сумму и когда кончается контракт —
окно продаж для госсектора и доля РТК по районам. Склейка с госсектором — по ИНН заказчика.

Как устроено (проверено 25.10.2026):
  - реестр контрактов ЕИС ищет по региону заказчика (customerPlace=61000000000), фильтра ОКПД2 там нет —
    ищем по точным фразам в предмете (morphology=off), списки фраз объединяем и убираем повторы;
  - в списке есть номер, заказчик, цена, даты заключения и исполнения, предмет; поставщик — только в карточке;
  - ИНН заказчика зашит в реестровый номер 44-ФЗ: уровень бюджета (1) + ИНН (10) + год (2) + порядковый (6);
  - сайт подписан «Russian Trusted Sub CA» Минцифры — цепочка из certs/, проверка TLS не отключается;
  - с адресов хостинга и через VPN сайт может не отвечать — запускать с обычного домашнего интернета.

Шаги и кэш (повторный запуск продолжает, ничего не качает заново):
  1) список — data/raw/zakupki/list/<фраза>_p<страница>.json;
  2) карточки — data/raw/zakupki/cards/<номер>.json (только разобранные поля, без HTML);
  3) итог — data/raw/zakupki/contracts_<регион>.csv.

Запуск из корня репозитория:
    python -m backend.etl.zakupki_contracts                    # всё: список, карточки, итог
    python -m backend.etl.zakupki_contracts --since 01.01.2024 --pause 2   # если ЕИС отвечает 429 — увеличить паузу
    python -m backend.etl.zakupki_contracts --list-only        # только список (быстро), без карточек
"""
import argparse
import html as htmlmod
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "zakupki"
SITE = "https://zakupki.gov.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
CTX = ssl.create_default_context()
CTX.load_verify_locations(Path(__file__).with_name("certs") / "russian_trusted_root_ca.pem")
PLACE = {"61": "61000000000"}  # код субъекта в ЕИС (КЛАДР) — как в ссылке поиска с фильтром «Ростовская область»

# Точные фразы предмета контракта. Пересекаются — повторы убираются по номеру контракта
PHRASES = [
    "услуги связи", "услуг связи", "телефонной связи", "сети Интернет", "сеть Интернет", "передачи данных",
    "каналов связи", "канала связи", "видеонаблюдения", "телематических", "междугородной", "подвижной радиотелефонной",
]
PER_PAGE = 50
PAUSE = 1.5  # пауза после каждой карточки, с; при 3 потоках сайт уже отвечал 429
MAX_PAGES = 20  # ЕИС показывает не больше 1000 результатов на запрос — длинные запросы дробим по годам


def get(url: str, tries: int = 8) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            # 429 — ЕИС просит сбавить темп: ждём, сколько сказал сайт (Retry-After), иначе минуту и дольше
            if e.code != 429 and e.code < 500 or attempt == tries - 1:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 60 * (attempt + 1)
            print(f"  сайт просит паузу ({e.code}), жду {wait} с", file=sys.stderr, flush=True)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))
            print(f"  повтор ({e})", file=sys.stderr, flush=True)


def text(s: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def money(s: str) -> float | None:
    m = re.search(r"[\d\s ]+,\d{2}", s)
    return float(m.group(0).replace(" ", "").replace(" ", "").replace(",", ".")) if m else None


def parse_list(page: str) -> list[dict]:
    """Блоки результатов поиска реестра контрактов."""
    rows = []
    for blk in page.split('search-registry-entry-block')[1:]:
        num = re.search(r"reestrNumber=(\d+)", blk)
        if not num:
            continue
        cust = re.search(r'organizationId=(\d+)"[^>]*>(.*?)</a>', blk, re.S)
        subj = re.search(r'lots-wrap-content__body__val"\s*>(.*?)</div>', blk, re.S)
        price = re.search(r'price-block__value[^>]*>(.*?)</div>', blk, re.S)
        dates = dict((text(t), text(v)) for t, v in re.findall(r'data-block__title">(.*?)</div>\s*<div class="data-block__value">(.*?)</div>', blk, re.S))
        n = num.group(1)
        rows.append({
            "reestr_number": n, "customer_inn": n[1:11] if len(n) == 19 else None,
            "customer": text(cust.group(2)) if cust else None, "customer_eis_id": cust.group(1) if cust else None,
            "subject": text(subj.group(1)) if subj else None, "price": money(price.group(1)) if price else None,
            "signed": dates.get("Заключение контракта"), "finish": dates.get("Срок исполнения"),
        })
    return rows


def parse_card(page: str) -> dict:
    """Карточка контракта: поставщики (название, ИНН, КПП), окончание исполнения, предмет."""
    def field(label):
        m = re.search(re.escape(label) + r"</span>\s*<span[^>]*>(.*?)</span>", page, re.S)
        return text(m.group(1)) if m else None
    suppliers = []
    part = page.split("Информация о поставщиках", 1)
    if len(part) == 2:
        for td in re.findall(r'tableBlock__col_first text-break">(.*?)</td>', part[1].split("participantsUrlRefresh")[0], re.S):
            name = text(re.split(r"<br|<section", td, maxsplit=1)[0])
            inn = re.search(r"ИНН:</span>\s*<span>(\d+)</span>", td)
            kpp = re.search(r"КПП:</span>\s*<span>(\d+)</span>", td)
            suppliers.append({"name": name, "inn": inn.group(1) if inn else None, "kpp": kpp.group(1) if kpp else None})
    finish = re.search(r"Дата окончания исполнения контракта\s*</span>\s*<span[^>]*>\s*([\d.]+)", page)
    if not finish:
        m = re.search(r"Дата окончания исполнения контракта(.{0,300})", page, re.S)
        finish = re.search(r"(\d{2}\.\d{2}\.\d{4})", m.group(1)) if m else None
    return {"suppliers": suppliers, "finish_card": finish.group(1) if finish else None,
            "subject_card": field("Предмет контракта"),
            "ikz": (re.search(r"\(ИКЗ\)\s*</span>\s*<span[^>]*>\s*(\d+)", page) or [None, None])[1]}


def search_url(region: str, phrase: str, page: int, date_from: str, date_to: str) -> str:
    q = {"fz44": "on", "contractStageList": "0,1,2,3", "customerPlace": PLACE[region], "customerPlaceCodes": PLACE[region],
         "morphology": "off", "searchString": phrase, "recordsPerPage": f"_{PER_PAGE}", "pageNumber": page,
         "contractDateFrom": date_from, "contractDateTo": date_to, "sortBy": "UPDATE_DATE", "sortDirection": "false"}
    return f"{SITE}/epz/contract/search/results.html?{urllib.parse.urlencode(q)}"


def year_slices(since: str):
    """Запрос дробим по годам — ЕИС отдаёт не больше 1000 результатов на поиск."""
    start = datetime.strptime(since, "%d.%m.%Y")
    for y in range(start.year, datetime.now().year + 1):
        a = start if y == start.year else datetime(y, 1, 1)
        yield a.strftime("%d.%m.%Y"), datetime(y, 12, 31).strftime("%d.%m.%Y")


def collect_list(region: str, since: str) -> dict:
    found = {}
    for phrase in PHRASES:
        for d_from, d_to in year_slices(since):
            for page in range(1, MAX_PAGES + 1):
                cache = OUT / "list" / f"{region}_{re.sub(r'[^а-яa-z0-9]+', '_', phrase.lower())}_{d_from[-4:]}_p{page:02d}.json"
                if cache.exists():
                    rows = json.loads(cache.read_text(encoding="utf-8"))
                else:
                    rows = parse_list(get(search_url(region, phrase, page, d_from, d_to)))
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
                    time.sleep(0.5)
                for r in rows:
                    rec = found.setdefault(r["reestr_number"], {**r, "phrases": []})
                    if phrase not in rec["phrases"]:
                        rec["phrases"].append(phrase)
                if len(rows) < PER_PAGE:
                    break
            print(f"  «{phrase}» {d_from[-4:]}: всего уникальных {len(found)}", flush=True)
    return found


def fetch_card(number: str) -> dict:
    path = OUT / "cards" / f"{number}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = parse_card(get(f"{SITE}/epz/contract/contractCard/common-info.html?reestrNumber={number}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(PAUSE)  # ЕИС отвечает 429 на частые запросы — держим темп
    return data


def main():
    global PAUSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="61")
    ap.add_argument("--since", default="01.01.2024", help="дата заключения контракта, с")
    ap.add_argument("--workers", type=int, default=1, help="параллельных запросов карточек (на 3 потоках ЕИС отвечает 429)")
    ap.add_argument("--pause", type=float, default=PAUSE, help="пауза после карточки, с")
    ap.add_argument("--list-only", action="store_true")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    PAUSE = a.pause

    t0 = time.time()
    print("шаг 1: список контрактов по фразам", flush=True)
    found = collect_list(a.region, a.since)
    print(f"найдено контрактов: {len(found)} · {time.time() - t0:.0f} с", flush=True)
    if a.list_only:
        return

    print(f"шаг 2: карточки ({a.workers} поток, пауза {a.pause} с)", flush=True)
    todo = list(found)
    done = failed = 0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(fetch_card, n): n for n in todo}
        for f in as_completed(futs):
            try:
                found[futs[f]].update(f.result())
                done += 1
            except Exception as e:  # карточка не открылась после повторов — докачается при следующем запуске
                failed += 1
                print(f"  карточка {futs[f]}: {e}", file=sys.stderr, flush=True)
            if (done + failed) % 50 == 0:
                el = time.time() - t0
                print(f"  {done + failed}/{len(todo)} · {el / 60:.0f} мин", flush=True)

    rows = []
    for r in found.values():
        sup = (r.get("suppliers") or [{}])
        main_sup = next((s for s in sup if s.get("inn")), sup[0] if sup else {})
        rows.append({**{k: v for k, v in r.items() if k not in ("suppliers", "phrases")},
                     "phrases": "; ".join(r.get("phrases", [])),
                     "supplier": main_sup.get("name"), "supplier_inn": main_sup.get("inn"), "supplier_kpp": main_sup.get("kpp"),
                     "suppliers_all": "; ".join(f"{s.get('name')} ({s.get('inn')})" for s in sup if s.get("name"))})
    import csv
    path = OUT / f"contracts_{a.region}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["reestr_number"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    rt = sum(1 for r in rows if r["supplier_inn"] == "7707049388")
    print(f"готово: {len(rows)} контрактов, карточек не открылось {failed}" + (" — запустите ещё раз" if failed else "")
          + f"; Ростелеком поставщик в {rt}; файл {path} · {(time.time() - t0) / 60:.0f} мин")


if __name__ == "__main__":
    main()
