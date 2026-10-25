"""Шаги 6–8: показатели муниципалитетов, «белые пятна», скоринг компаний.

Вход:  data/seed/radar/companies_<регион>.parquet, clients_<регион>.parquet
Выход: data/seed/radar/zones_<регион>.parquet   — 55 муниципалитетов с метриками и потенциалом
       data/seed/radar/scored_<регион>.parquet  — все субъекты с отраслью, рекомендацией и баллом лида
       data/seed/radar/scoring_<регион>.meta.json

Все баллы — оценка. Для каждого балла хранится вклад каждого фактора, чтобы интерфейс мог объяснить «почему».

Запуск: python -m backend.etl.scoring --region 61
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from backend.etl.products import classify

ROOT = Path(__file__).resolve().parents[2]
RADAR = ROOT / "data" / "seed" / "radar"

# Веса потенциала зоны (сумма 100).
# Три слагаемых: суммарный доход, рост доходов год к году, недоохват РТК.
# Это веса по умолчанию; на сайте пользователь двигает их сам (frontend/src/radar/potential.ts считает так же).
ZONE_WEIGHTS = {"income": 40, "growth": 30, "gap": 30}
LOW_COVERAGE = 0.75  # «низкий охват»: доля РТК в районе ≤ 75% от средней по региону
GROWTH_CLIP = (-100, 300)  # рост доходов юрлица, % — обрезаем выбросы на маленькой базе


def pct_rank(s: pd.Series) -> pd.Series:
    """Перцентиль 0…1 внутри региона (устойчив к выбросам и разным единицам)."""
    return s.rank(pct=True, method="average").fillna(0)


def zones(c: pd.DataFrame, region_share: float) -> pd.DataFrame:
    ul = c.kind == "ЮЛ"
    c = c.assign(
        is_ul=ul, is_ip=c.kind == "ИП", is_kfh=c.kind == "ИП (КФХ)",
        active_ul=ul & (c.income_2025 > 0),
        growth_clip=c.income_growth_pct.clip(*GROWTH_CLIP),
        # для роста района берём только юрлиц с доходом за оба года — иначе «рост» дают новые компании
        income_cur=c.income_2025.where(c.income_2024 > 0),
        income_prev=c.income_2024.where((c.income_2024 > 0) & c.income_2025.notna()),
    )
    g = c[c.oktmo.notna()].groupby(["oktmo", "municipality"])
    z = g.agg(
        companies=("inn", "size"), ul=("is_ul", "sum"), ip=("is_ip", "sum"), kfh=("is_kfh", "sum"),
        active_ul=("active_ul", "sum"),
        rtk_clients=("is_rtk_client", "sum"),
        ul_income_sum=("income_2025", "sum"), ul_income_median=("income_2025", "median"),
        ul_growth_median=("growth_clip", "median"),
        new_month=("new_in_release", "sum"),
        avg_relevance=("relevance", "mean"),
        income_cur=("income_cur", "sum"), income_prev=("income_prev", "sum"),
    ).reset_index()
    z["income_growth_abs"] = z.income_cur - z.income_prev
    z["income_growth_pct"] = (z.income_growth_abs / z.income_prev * 100).where(z.income_prev > 0).round(1)
    z["rtk_share_pct"] = (z.rtk_clients / z.companies * 100).round(3)
    # Сколько клиентов было бы при среднем по региону охвате, и сколько не хватает
    z["expected_clients"] = (z.companies * region_share).round(1)
    z["client_gap"] = (z.expected_clients - z.rtk_clients).round(1)
    return z


def zone_potential(z: pd.DataFrame, left_by_zone: pd.Series, rtk_left_by_zone: pd.Series) -> pd.DataFrame:
    z = z.copy()
    z["left_month"] = z.oktmo.map(left_by_zone).fillna(0).astype(int)
    z["rtk_left_month"] = z.oktmo.map(rtk_left_by_zone).fillna(0).astype(int)
    z["market_dynamics_pct"] = ((z.new_month - z.left_month) / z.companies * 100).round(2)

    # Недоохват: насколько охват РТК в районе ниже среднего по региону.
    # coverage_vs_region = 1 — как в среднем; 0 — клиентов нет. Вклад = 1 − coverage_vs_region (не меньше 0).
    region_share_pct = z.rtk_clients.sum() / z.companies.sum() * 100
    z["coverage_vs_region"] = (z.rtk_share_pct / region_share_pct).round(2)
    gap = (1 - z.coverage_vs_region).clip(lower=0, upper=1)

    factors = {
        "income": pct_rank(z.ul_income_sum),                    # суммарный доход юрлиц района, место среди районов
        "growth": pct_rank(z.income_growth_pct),                # изменение суммарного дохода 2025 к 2024, %
        "gap": gap,                                             # недоохват: 1 − охват района / средний охват
    }
    total = 0
    for k, f in factors.items():
        z[f"f_{k}"] = (f * ZONE_WEIGHTS[k]).round(1)
        total = total + z[f"f_{k}"]
    z["potential"] = total.round(1)
    z["potential_rank"] = z.potential.rank(ascending=False, method="min").astype(int)
    # «Белое пятно»: низкий охват (≤ 75% от среднего или ноль клиентов) + потенциал в верхней трети региона
    z["low_coverage"] = (z.coverage_vs_region <= LOW_COVERAGE) | (z.rtk_clients == 0)
    z["white_spot"] = z.low_coverage & (z.potential >= z.potential.quantile(2 / 3))
    z["white_spot_reason"] = np.where(
        z.white_spot,
        "клиентов РТК " + z.rtk_clients.astype(str) + " при ожидаемых " + z.expected_clients.astype(str)
        + " (охват " + (z.coverage_vs_region * 100).round().astype(int).astype(str) + "% от среднего по области)",
        None)
    return z.sort_values("potential", ascending=False)


def company_scores(c: pd.DataFrame, zone_pot: pd.Series) -> pd.DataFrame:
    """Балл лида 0…100. Юрлица и ИП — разные формулы: у ИП нет доходов и численности в открытых данных."""
    c = c.copy()
    years = (pd.Timestamp(date.today()) - pd.to_datetime(c.msp_since, format="%d.%m.%Y", errors="coerce")).dt.days / 365.25
    c["msp_years"] = years.round(1)
    zp = c.oktmo.map(zone_pot).fillna(0) / 100  # 0…1

    ul = c.kind == "ЮЛ"
    income = c.income_2025.where(c.income_2025 > 0)
    s_scale = pct_rank(np.log1p(income.where(ul))).where(ul & income.notna(), 0)
    s_staff = pct_rank(c.staff_2025.where(ul)).where(ul & c.staff_2025.notna(), 0)
    s_growth = ((c.income_growth_pct.clip(-50, 100) + 50) / 150).where(ul & c.income_growth_pct.notna(), 0.33)

    # Юрлица: масштаб 35 + численность 15 + рост 15 + отрасль 25 + зона 10
    ul_parts = {"scale": s_scale * 35, "staff": s_staff * 15, "growth": s_growth * 15,
                "industry": c.relevance * 25, "zone": zp * 10}
    # ИП и КФХ: отрасль 45 + стаж 20 + лицензии 10 + КФХ 5 + новый 5 + зона 15
    s_age = (c.msp_years.clip(0, 8) / 8).fillna(0)
    ip_parts = {"industry": c.relevance * 45, "age": s_age * 20, "licenses": (c.licenses > 0) * 10.0,
                "kfh": (c.kind == "ИП (КФХ)") * 5.0, "new": c.is_new * 5.0, "zone": zp * 15}

    for k in set(ul_parts) | set(ip_parts):
        c[f"s_{k}"] = np.where(ul, ul_parts.get(k, 0), ip_parts.get(k, 0)).round(1)
    c["lead_score"] = c[[x for x in c.columns if x.startswith("s_")]].sum(axis=1).round(1)

    # Флаги качества — не исключаем, а помечаем
    c["flag_zero_income"] = ul & (c.income_2025 == 0)
    c["flag_check_category"] = ul & (c.category == "микро") & (c.income_2025 > 800e6)
    c.loc[c.flag_zero_income, "lead_score"] = (c.loc[c.flag_zero_income, "lead_score"] * 0.5).round(1)
    c["lead_rank_in_kind"] = c[~c.is_rtk_client].groupby("kind").lead_score.rank(ascending=False, method="min")
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="61")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    c = pd.read_parquet(RADAR / f"companies_{a.region}.parquet")
    clients = pd.read_parquet(RADAR / f"clients_{a.region}.parquet")

    # Отрасль и продукты: основной ОКВЭД, иначе первый дополнительный
    okved = c.okved_main.fillna(c.okved_extra.str.split(";").str[0])
    cls = okved.map(classify)
    c["industry"] = cls.str[0]
    c["relevance"] = cls.str[1]
    c["products"] = cls.str[2].str.join("; ")
    c["products_reason"] = cls.str[3]

    region_share = c.is_rtk_client.sum() / len(c)
    z = zones(c, region_share)

    # Выбывшие за месяц по зонам: рынок (по прошлому выпуску) и клиенты РТК
    from backend.etl.municipality import assign, load_reference
    ref = load_reference(a.region)
    prev = pd.read_parquet(sorted((ROOT / "data" / "seed" / "fns").glob(f"msp_{a.region}_*.parquet"))[-2],
                           columns=["inn", "district", "city", "settlement"])
    left = prev[~prev.inn.isin(set(c.inn))]
    left_oktmo = pd.Series([assign(d, ci, s, ref)[0] for d, ci, s in zip(left.district, left.city, left.settlement)])
    left_by_zone = left_oktmo.value_counts()
    rtk_left = clients[clients.msp_status.str.startswith("выбыл")]
    rtk_left_by_zone = rtk_left.oktmo.value_counts()

    z = zone_potential(z, left_by_zone, rtk_left_by_zone)
    scored = company_scores(c, z.set_index("oktmo").potential)

    # DaData (если уже собрана): статус ЕГРЮЛ, КПП, филиалы, сигналы «*», координаты
    dd_path = ROOT / "data" / "seed" / "dadata" / f"enriched_{a.region}.parquet"
    dd_meta = None
    if dd_path.exists():
        dd = pd.read_parquet(dd_path)
        cols = [x for x in ["inn", "dd_name", "dd_status", "dd_liquidation_date", "kpp", "branch_count",
                            "branches_in_region", "branches", "legal_address", "reloc_signals", "geo_lat", "geo_lon",
                            "qc_geo", "geo_precision", "oktmo_dd", "house_fias_id"] if x in dd.columns]
        dd = dd[cols]
        scored = scored.merge(dd, on="inn", how="left")
        has_geo = scored.geo_lat.notna() if "geo_lat" in scored else pd.Series(False, index=scored.index)
        scored.loc[has_geo, "location_precision"] = scored.loc[has_geo, "geo_precision"]
        # В одном здании уже есть клиент РТК → вероятная техническая возможность подключения (оценка)
        if "house_fias_id" in scored:
            rtk_houses = set(scored.loc[scored.is_rtk_client & scored.house_fias_id.notna(), "house_fias_id"])
            scored["rtk_in_same_building"] = scored.house_fias_id.isin(rtk_houses) & ~scored.is_rtk_client
            mass = scored.house_fias_id.value_counts()
            scored["mass_address"] = scored.house_fias_id.map(mass).fillna(0) >= 50
        # повторный запуск: убираем колонки DaData прошлого прогона, чтобы не задвоить
        clients = clients.drop(columns=[x for x in cols if x != "inn"] + ["churn_type", "churn_risk"], errors="ignore")
        clients = clients.merge(dd, on="inn", how="left")
        clients["churn_type"] = np.select(
            [clients.msp_status.str.startswith("выбыл") & clients.dd_status.isin(["ликвидирована", "банкротство"]),
             clients.msp_status.str.startswith("выбыл") & (clients.dd_status == "ликвидируется"),
             clients.msp_status.str.startswith("выбыл") & (clients.dd_status == "действует")],
            ["закрылся", "закрывается", "действует, вышел из реестра МСП"], default=None)
        # Ранний сигнал: в реестре МСП ещё есть, а в ЕГРЮЛ уже ликвидация/банкротство (реестр отстаёт от ЕГРЮЛ)
        clients["churn_risk"] = np.where(
            (clients.msp_status == "в реестре МСП")
            & clients.dd_status.isin(["ликвидирована", "ликвидируется", "банкротство", "реорганизация"]),
            "риск: в ЕГРЮЛ — " + clients.dd_status.fillna(""), None)
        clients.to_parquet(RADAR / f"clients_{a.region}.parquet", index=False)
        clients.to_csv(RADAR / f"clients_{a.region}.csv", index=False, encoding="utf-8-sig")
        dd_meta = {"enriched": len(dd), "geocoded": int(has_geo.sum()),
                   "clients_churn_type": clients.churn_type.value_counts().to_dict(),
                   "clients_churn_risk": int(clients.churn_risk.notna().sum()),
                   "with_reloc_signals": int(scored.reloc_signals.notna().sum()) if "reloc_signals" in scored else 0}

    z.to_parquet(RADAR / f"zones_{a.region}.parquet", index=False)
    z.to_csv(RADAR / f"zones_{a.region}.csv", index=False, encoding="utf-8-sig")
    scored.to_parquet(RADAR / f"scored_{a.region}.parquet", index=False)

    top = z.head(10)[["municipality", "potential", "rtk_clients", "companies", "rtk_share_pct", "client_gap", "white_spot"]]
    meta = {
        "region": a.region,
        "region_rtk_share_pct": round(region_share * 100, 3),
        "zone_weights": ZONE_WEIGHTS,
        "white_spots": z[z.white_spot].municipality.tolist(),
        "top10_potential": top.to_dict(orient="records"),
        "industry_counts": c.industry.value_counts().to_dict(),
        "leads_scored": int((~scored.is_rtk_client).sum()),
        "flag_zero_income": int(scored.flag_zero_income.sum()),
        "flag_check_category": int(scored.flag_check_category.sum()),
        "dadata": dd_meta,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "note": "Баллы — оценка команды; веса и формулы в backend/etl/scoring.py, справочник продуктов — products.py",
    }
    (RADAR / f"scoring_{a.region}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str),
                                                         encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
