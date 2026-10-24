'Обогащение по ИНН через DaData (бесплатные методы подписки «Подсказки»).'
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RADAR = ROOT / "data" / "seed" / "radar"
CACHE = ROOT / "data" / "seed" / "dadata"
API = "https://suggestions.dadata.ru/suggestions/api/4_1/rs"
STATUS_RU = {"ACTIVE": "действует", "LIQUIDATING": "ликвидируется", "LIQUIDATED": "ликвидирована",
             "BANKRUPT": "банкротство", "REORGANIZING": "реорганизация"}

def load_key() -> str:
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
               if "=" in l and not l.startswith("#"))
    return env["DADATA_API_KEY"].strip()

class DaData:
    def __init__(self, key: str, budget: int, rps: float = 8.0):
        self.key, self.budget, self.spent, self.pause = key, budget, 0, 1.0 / rps

    def _post(self, method: str, payload: dict) -> dict:
        if self.spent >= self.budget:
            raise RuntimeError("budget")
        req = urllib.request.Request(f"{API}/{method}", data=json.dumps(payload).encode(), method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Token {self.key}"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    self.spent += 1
                    time.sleep(self.pause)
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                if e.code == 403:
                    raise RuntimeError("403: дневной лимит DaData исчерпан или ключ не принят") from e
                raise

    def cached(self, kind: str, key: str, method: str, payload: dict) -> dict:
        path = CACHE / kind / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        data = self._post(method, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"requested_at": datetime.now().isoformat(timespec="seconds"), "response": data},
                                   ensure_ascii=False), encoding="utf-8")
        return {"requested_at": "", "response": data}

def party(dd: DaData, inn: str):

    sug = dd.cached("party", inn, "findById/party", {"query": inn, "count": 20})["response"].get("suggestions", [])
    main = next((s for s in sug if s["data"].get("branch_type") != "BRANCH"), sug[0] if sug else None)
    branches = [s for s in sug if s["data"].get("branch_type") == "BRANCH"]
    return main, branches

QC_GEO = {0: "дом", 1: "ближайший дом", 2: "улица", 3: "населённый пункт", 4: "город", 5: "не определена"}
_HOUSE = re.compile(r"\b(?:д|дом|влд|зд)(?:\.|\s)\s*\d[\w/\-]*", re.I)

def clean_address(address: str) -> str:

    s = re.sub(r"^\s*\d{6},\s*", "", address)
    s = re.sub(r"(?i)\bг\.?\s?о\.?\s+(?:город\s+)?[^,]+,\s*", "", s)
    m = _HOUSE.search(s)
    return s[: m.end()] if m else s

def _suggest(dd: DaData, address: str):
    key = hashlib.md5(address.encode("utf-8")).hexdigest()
    sug = dd.cached("address", key, "suggest/address", {"query": address, "count": 1})["response"].get("suggestions", [])
    return sug[0]["data"] if sug else None

def _qc(g):
    return int(g["qc_geo"]) if g and g.get("qc_geo") not in (None, "") else 9

def geocode(dd: DaData, address: str):

    best = _suggest(dd, address)
    cleaned = clean_address(address)
    if _qc(best) > 1 and cleaned != address:
        alt = _suggest(dd, cleaned)
        if _qc(alt) < _qc(best):
            best = alt
    return best

def row_for(dd: DaData, inn: str, region: str) -> dict:
    main, branches = party(dd, inn)
    row = {"inn": inn, "dd_found": main is not None}
    if not main:
        return row
    d = main["data"]
    st = d.get("state") or {}
    addr = d.get("address") or {}
    adata = addr.get("data") or {}
    kpp = d.get("kpp") or ""
    row.update({
        "dd_type": "ЮЛ" if d.get("type") == "LEGAL" else "ИП",
        "dd_name": main.get("value"),
        "dd_status": STATUS_RU.get(st.get("status"), st.get("status")),
        "dd_liquidation_date": datetime.fromtimestamp(st["liquidation_date"] / 1000).date().isoformat()
        if st.get("liquidation_date") else None,
        "dd_okved": d.get("okved"),
        "kpp": kpp or None,
        "branch_count": d.get("branch_count") or 0,
        "branches_in_region": sum(1 for b in branches if ((b["data"].get("address") or {}).get("data") or {})
                                  .get("region_kladr_id", "").startswith(region)),
        "branches": json.dumps([{"kpp": b["data"].get("kpp"), "address": (b["data"].get("address") or {}).get("value")}
                                for b in branches], ensure_ascii=False) if branches else None,
        "legal_address": addr.get("value"),
        "legal_region": adata.get("region_with_type"),
        "legal_city": adata.get("city_with_type") or adata.get("settlement_with_type"),
    })

    inn_reg, kpp_reg = inn[:2], kpp[:2] if kpp else None
    signals = []
    if inn_reg != region:
        signals.append(f"ИНН выдан в регионе {inn_reg}")
    if kpp_reg and kpp_reg != inn_reg:
        signals.append(f"КПП: сейчас на учёте в регионе {kpp_reg} (переезд)")
    if row["branches_in_region"]:
        signals.append(f"филиалов в регионе: {row['branches_in_region']}")
    row["reloc_signals"] = "; ".join(signals) or None

    if row["dd_type"] == "ЮЛ" and addr.get("value"):
        g = geocode(dd, addr["value"])
        if g:
            row.update({"geo_lat": float(g["geo_lat"]) if g.get("geo_lat") else None,
                        "geo_lon": float(g["geo_lon"]) if g.get("geo_lon") else None,
                        "qc_geo": int(g["qc_geo"]) if g.get("qc_geo") not in (None, "") else None,
                        "geo_precision": QC_GEO.get(int(g["qc_geo"])) if g.get("qc_geo") not in (None, "") else None,
                        "oktmo_dd": (g.get("oktmo") or "")[:8] or None,
                        "house_fias_id": g.get("house_fias_id"),
                        "geo_source": "DaData suggest/address"})
    return row

def select_top_leads(region: str) -> dict[str, str]:

    s = pd.read_parquet(RADAR / f"scored_{region}.parquet",
                        columns=["inn", "kind", "is_rtk_client", "lead_score", "income_2025", "income_growth_pct",
                                 "oktmo", "flag_zero_income"])
    z = pd.read_parquet(RADAR / f"zones_{region}.parquet", columns=["oktmo", "white_spot"])
    done = {p.stem for p in (CACHE / "party").glob("*.json")}
    pool = s[(s.kind == "ЮЛ") & ~s.is_rtk_client & ~s.flag_zero_income & ~s.inn.isin(done)]

    picks: dict[str, str] = {}
    def take(df, n, why):
        for inn in df.inn.head(n):
            picks.setdefault(inn, why)

    take(pool.sort_values("lead_score", ascending=False), 1000, "топ по баллу")
    take(pool.sort_values("income_2025", ascending=False), 400, "топ по доходу")
    take(pool[pool.income_2025 >= 10e6].sort_values("income_growth_pct", ascending=False), 300, "топ по росту дохода")
    spots = set(z[z.white_spot].oktmo)
    for o, g in pool[pool.oktmo.isin(spots)].groupby("oktmo"):
        take(g.sort_values("lead_score", ascending=False), 40, "лучшие в белом пятне")
    for o, g in pool.groupby("oktmo"):
        take(g.sort_values("lead_score", ascending=False), 12, "лучшие в муниципалитете")
    return picks

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="61")
    ap.add_argument("--set", action="append", default=[], choices=["clients", "other_region_ul", "top_leads"])
    ap.add_argument("--inn", action="append", default=[])
    ap.add_argument("--budget", type=int, default=9500, help="максимум запросов за запуск")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    targets: dict[str, str] = {i: "вручную" for i in a.inn}
    if "clients" in a.set:
        for i in pd.read_parquet(RADAR / f"clients_{a.region}.parquet", columns=["inn"]).inn:
            targets.setdefault(i, "клиент РТК")
    if "other_region_ul" in a.set:
        c = pd.read_parquet(RADAR / f"companies_{a.region}.parquet", columns=["inn", "kind", "inn_other_region"])
        for i in c[(c.kind == "ЮЛ") & c.inn_other_region].inn:
            targets.setdefault(i, "ЮЛ с ИНН другого региона")
    if "top_leads" in a.set:
        for i, why in select_top_leads(a.region).items():
            targets.setdefault(i, why)

    dd = DaData(load_key(), a.budget)
    rows, stopped, t0 = [], None, time.time()
    for n, (inn, why) in enumerate(targets.items(), 1):
        try:
            r = row_for(dd, inn, a.region)
        except RuntimeError as e:
            stopped = str(e)
            break
        r["enrich_reason"] = why
        rows.append(r)
        if n % 100 == 0:
            print(f"  {n}/{len(targets)} · запросов в этом запуске {dd.spent} · {time.time() - t0:.0f} с", file=sys.stderr, flush=True)

    out = pd.DataFrame(rows)
    stem = f"enriched_{a.region}"
    if (CACHE / f"{stem}.parquet").exists() and not a.inn:
        old = pd.read_parquet(CACHE / f"{stem}.parquet")
        out = pd.concat([old[~old.inn.isin(out.inn)], out]) if len(out) else old
    if not a.inn:
        out.to_parquet(CACHE / f"{stem}.parquet", index=False)
        out.to_csv(CACHE / f"{stem}.csv", index=False, encoding="utf-8-sig")

    meta = {
        "source": "DaData findById/party (ЕГРЮЛ/ЕГРИП) + suggest/address (ФИАС, ОКТМО, координаты)",
        "targets": len(targets), "processed": len(rows), "requests_this_run": dd.spent,
        "stopped": stopped,
        "found": int(out.dd_found.sum()) if len(out) else 0,
        "by_status": out.dd_status.value_counts().to_dict() if "dd_status" in out else {},
        "geocoded": int(out.geo_lat.notna().sum()) if "geo_lat" in out else 0,
        "geo_exact_house": int((out.qc_geo == 0).sum()) if "qc_geo" in out else 0,
        "with_reloc_signals": int(out.reloc_signals.notna().sum()) if "reloc_signals" in out else 0,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not a.inn:
        (CACHE / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if a.inn:
        print(out.T.to_string())

if __name__ == "__main__":
    main()
