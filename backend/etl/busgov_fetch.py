"""Выгрузка «Общей информации об учреждениях» с bus.gov.ru (ГИС ГМУ, приказ Минфина № 86н) → data/raw/busgov/pages/

Набор открытых данных 7710568760-Generalinformation отдаётся постранично, всего ~181 тыс. записей по России.
Что выяснили 25.10.2026:
  - фильтра по региону у API нет (region, subject, okato, oktmo игнорируются), есть только точный поиск по inn;
  - страницы нумеруются с 1; при одном и том же size порядок записей стабилен, при другом size — другой,
    поэтому размер страницы фиксируем и пишем в fetch.meta.json, продолжать выгрузку можно только с ним же;
  - портал медленный: ~3–4 записи в секунду на поток, поэтому качаем в несколько потоков;
  - сертификат сайта выпущен «Russian Trusted Sub CA» (Минцифры), которого нет в стандартном наборе Python:
    цепочку добавляем из certs/russian_trusted_root_ca.pem, проверку не отключаем.
С адресов хостинга портал не отвечает; с обычного домашнего интернета — отвечает.

Каждая страница — отдельный файл; повторный запуск докачивает недостающие. Разбор, фильтр по региону и загрузка
в базу — отдельным шагом (backend/etl/busgov.py).

Запуск из корня репозитория:
    python -m backend.etl.busgov_fetch --probe                 # проверить доступ и выйти
    python -m backend.etl.busgov_fetch --workers 4             # выгрузить всё (часы; можно прерывать и продолжать)
    python -m backend.etl.busgov_fetch --inn 6143037909        # одно учреждение по ИНН
"""
import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "busgov" / "pages"
META = OUT.parent / "fetch.meta.json"
URL = "https://bus.gov.ru/public-rest/api/7710568760-Generalinformation"
UA = "Mozilla/5.0 (rt-hackathon open data loader)"
# Корневой сертификат Минцифры: gu-st.ru (Госуслуги), SHA-256 D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:
# 35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31; промежуточные «Russian Trusted Sub CA» (gu-st.ru и
# nuc-cdp.digital.gov.ru/cdp/subca_ssl_rsa2024.crt — им подписан bus.gov.ru) проверяются по нему
CTX = ssl.create_default_context()
CTX.load_verify_locations(Path(__file__).with_name("certs") / "russian_trusted_root_ca.pem")


def get(query: str, tries: int = 6) -> dict:
    req = urllib.request.Request(f"{URL}?{query}", headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=300, context=CTX) as r:
                return json.loads(r.read())["pagedContent"]
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            if attempt == tries - 1:
                raise
            time.sleep(10 * (attempt + 1))
            print(f"  {query}: {e}; повтор", file=sys.stderr, flush=True)


def fetch_page(page: int, size: int) -> int:
    path = OUT / f"page_{page:05d}.json"
    rows = get(f"page={page}&size={size}")["content"]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # файл появляется целиком — прерванный запуск не оставит битых страниц
    return len(rows)


def fetch_by_inn(csv_path: Path, workers: int):
    """Открытый набор bus.gov.ru — лента изменений (~18% учреждений), поэтому нужных учреждений добираем точечно по ИНН.
    Ответ кладём как страницу: busgov.py читает и pages/, и by_inn/ одинаково. Пустой ответ тоже сохраняем — не повторяем."""
    import csv
    with csv_path.open(encoding="utf-8-sig") as f:
        sample = f.readline()
        f.seek(0)
        rows = list(csv.DictReader(f, delimiter=";" if ";" in sample else ","))
    inns = sorted({(r.get("customer_inn") or r.get("inn") or "").strip() for r in rows} - {""})
    out = OUT.parent / "by_inn"
    out.mkdir(parents=True, exist_ok=True)
    todo = [i for i in inns if not (out / f"{i}.json").exists()]
    print(f"ИНН в файле: {len(inns)}; осталось запросить: {len(todo)}", flush=True)

    def one(inn):
        rows = get(f"page=1&size=50&inn={inn}")["content"]
        (out / f"{inn}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return len(rows)

    done = found = 0
    with ThreadPoolExecutor(workers) as ex:
        for f in as_completed([ex.submit(one, i) for i in todo]):
            try:
                found += f.result() > 0
            except Exception as e:
                print(f"  {e}", file=sys.stderr, flush=True)
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(todo)} · найдено в ГИС ГМУ {found}", flush=True)
    print(f"готово: запрошено {done}, найдено {found}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=300, help="записей на страницу (не менять посреди выгрузки)")
    ap.add_argument("--workers", type=int, default=4, help="параллельных запросов; портал государственный — не больше 4–6")
    ap.add_argument("--probe", action="store_true", help="запросить одну маленькую страницу и выйти")
    ap.add_argument("--inn", help="выгрузить одно учреждение по ИНН и показать его")
    ap.add_argument("--inns-csv", help="добрать учреждения по списку ИНН из CSV (колонка customer_inn или inn) → data/raw/busgov/by_inn/")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    if a.inns_csv:
        fetch_by_inn(Path(a.inns_csv), a.workers)
        return
    if a.inn:
        print(json.dumps(get(f"page=1&size=10&inn={a.inn}")["content"], ensure_ascii=False, indent=1)[:4000])
        return
    if a.probe:
        pc = get("page=1&size=10")
        print(f"доступ есть: отдано {len(pc['content'])} записей, всего {pc['total']}")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    if META.exists():
        meta = json.loads(META.read_text(encoding="utf-8"))
        if meta["size"] != a.size:
            sys.exit(f"выгрузка начата с --size {meta['size']}: продолжайте с ним же (порядок записей зависит от size)")
    total = get("page=1&size=1")["total"]
    pages = -(-total // a.size)
    META.write_text(json.dumps({"url": URL, "size": a.size, "total": total, "pages": pages,
                                "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False, indent=2), encoding="utf-8")

    todo = [p for p in range(1, pages + 1) if not (OUT / f"page_{p:05d}.json").exists()]
    print(f"всего {total:,} записей = {pages} страниц по {a.size}; осталось {len(todo)}; потоков {a.workers}", flush=True)
    t0, done, failed = time.time(), 0, []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(fetch_page, p, a.size): p for p in todo}
        for f in as_completed(futs):
            try:
                f.result()
                done += 1
            except Exception as e:  # страница не скачалась после всех повторов — докачается при следующем запуске
                failed.append(futs[f])
                print(f"  страница {futs[f]}: {e}", file=sys.stderr, flush=True)
            if done and done % 20 == 0:
                el = time.time() - t0
                print(f"  {done}/{len(todo)} · {el / 60:.0f} мин · осталось ~{el / done * (len(todo) - done) / 60:.0f} мин", flush=True)
    have = len(list(OUT.glob("page_*.json")))
    print(f"готово: {have}/{pages} страниц" + (f"; не скачались {len(failed)} — запустите ещё раз" if failed else ""))


if __name__ == "__main__":
    main()
