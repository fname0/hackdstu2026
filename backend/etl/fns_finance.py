'Шаги 2–3 ETL: доходы, численность и спецрежимы ФНС по ИНН субъектов региона.'
import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "fns"
OUT_DIR = ROOT / "data" / "seed" / "fns"

_INNS: set[str] = set()

def _init(inns):
    global _INNS
    _INNS = inns

def _year(state_date):

    return int(state_date[-4:]) if state_date else None

def _parse(args):
    kind, zip_path, name = args
    with zipfile.ZipFile(zip_path) as z:
        root = ET.fromstring(z.read(name))
    rows = []
    for doc in root.iter("Документ"):
        np_ = doc.find("СведНП")
        if np_ is None:
            continue
        inn = np_.get("ИННЮЛ") or np_.get("ИННФЛ")
        if inn not in _INNS:
            continue
        row = {"inn": inn, "state_date": doc.get("ДатаСост")}
        if kind == "revexp":
            x = doc.find("СведДохРасх")
            row["income"] = float(x.get("СумДоход") or 0) if x is not None else None
            row["expense"] = float(x.get("СумРасход") or 0) if x is not None else None
        elif kind == "sshr":
            x = doc.find("СведССЧР")
            row["staff"] = int(x.get("КолРаб")) if x is not None and (x.get("КолРаб") or "").isdigit() else None
        elif kind == "snr":
            x = doc.find("СведСНР")
            if x is not None:
                row.update({k: x.get(k) == "1" for k in ("ПризнЕСХН", "ПризнУСН", "ПризнАУСН", "ПризнСРП")})
        rows.append(row)
    return rows

def _read(kind, zip_path, inns, workers):
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".xml")]
    t0, rows = time.time(), []
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(inns,)) as ex:
        for i, r in enumerate(ex.map(_parse, [(kind, str(zip_path), n) for n in names], chunksize=16), 1):
            rows.extend(r)
            if i % 500 == 0 or i == len(names):
                print(f"  {zip_path.name}: {i}/{len(names)} файлов · найдено {len(rows):,} · {time.time() - t0:.0f} с",
                      file=sys.stderr, flush=True)
    return pd.DataFrame(rows)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--msp", type=Path, required=True, help="таблица шага 1 (msp_<регион>_<дата>.parquet)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    msp = pd.read_parquet(a.msp, columns=["inn", "kind", "region_code"])
    region = msp["region_code"].iloc[0]
    inns = set(msp["inn"])
    t0 = time.time()

    years = {}
    for zp in sorted(RAW.glob("revexp_*.zip")):
        df = _read("revexp", zp, inns, a.workers)
        y = _year(df["state_date"].iloc[0]) if len(df) else None
        years[y] = df.drop_duplicates("inn").set_index("inn")[["income", "expense"]]
    ys = sorted(y for y in years if y)
    fin = pd.DataFrame(index=sorted(inns))
    fin.index.name = "inn"
    for y in ys:
        fin[f"income_{y}"] = years[y]["income"]
        fin[f"expense_{y}"] = years[y]["expense"]
    if len(ys) >= 2:
        cur, prev = ys[-1], ys[-2]
        base = fin[f"income_{prev}"]

        fin["income_growth_pct"] = ((fin[f"income_{cur}"] - base) / base * 100).where(base > 0).round(1)

    sshr_zip = next(RAW.glob("sshr_*.zip"))
    sshr = _read("sshr", sshr_zip, inns, a.workers).drop_duplicates("inn").set_index("inn")
    staff_year = _year(sshr["state_date"].iloc[0]) if len(sshr) else None
    fin[f"staff_{staff_year}"] = sshr["staff"]

    snr_zip = next(RAW.glob("snr_*.zip"))
    snr = _read("snr", snr_zip, inns, a.workers).drop_duplicates("inn").set_index("inn")
    regime_cols = {"ПризнУСН": "УСН", "ПризнЕСХН": "ЕСХН", "ПризнАУСН": "АУСН", "ПризнСРП": "СРП"}

    def regime(r):
        if r.name not in snr.index:
            return None
        s = snr.loc[r.name]
        names = [v for k, v in regime_cols.items() if bool(s.get(k))]
        return "+".join(names) if names else "нет спецрежима"

    fin["tax_regime"] = fin.apply(regime, axis=1)
    fin = fin.reset_index()

    stem = f"finance_{region}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fin.to_parquet(OUT_DIR / f"{stem}.parquet", index=False)
    fin.to_csv(OUT_DIR / f"{stem}.csv", index=False, encoding="utf-8-sig")

    kinds = msp.set_index("inn")["kind"]
    has_income = fin[f"income_{ys[-1]}"].notna() if ys else pd.Series(False, index=fin.index)
    meta = {
        "source": "ФНС России, открытые данные: revexp (доходы/расходы), sshr2019 (численность), snr (спецрежимы)",
        "archives": sorted(p.name for p in RAW.glob("*.zip") if not p.name.startswith("rsmp")),
        "msp_table": a.msp.name,
        "region": region,
        "subjects": len(fin),
        "income_years": ys,
        "with_income_last_year": int(has_income.sum()),
        "with_income_by_kind": fin[has_income].inn.map(kinds).value_counts().to_dict(),
        "with_growth": int(fin["income_growth_pct"].notna().sum()) if "income_growth_pct" in fin else 0,
        "with_staff": int(fin[f"staff_{staff_year}"].notna().sum()),
        "in_snr": int(fin["tax_regime"].notna().sum()),
        "in_snr_by_kind": fin[fin["tax_regime"].notna()].inn.map(kinds).value_counts().to_dict(),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0),
    }
    (OUT_DIR / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
