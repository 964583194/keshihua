# -*- coding: utf-8 -*-
"""A-share dashboard updater.
Keeps the previous valid dashboard data when upstream APIs fail.
Does not fabricate market values.
"""
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "dashboard.json")
NOW = datetime.now(ZoneInfo("Asia/Shanghai"))

def load_previous():
    try:
        with open(OUT, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

PREV = load_previous()

D = {
    "meta": {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "data_date": None,
        "overall_status": "部分数据接入中"
    },
    "overview": {
        "hs300": None, "chinext": None, "star50": None,
        "advancers": None, "decliners": None
    },
    "indices": [],
    "industry_flows": [],
    "concept_flows": [],
    "focus_sectors": [],
    "breadth": {
        "advancers": None, "decliners": None, "unchanged": None,
        "advance_decline_ratio": None
    },
    "valuation": {
        "hs300_pe": None, "hs300_pe_percentile": None,
        "equity_bond_spread": None, "cn10y_yield": None
    },
    "sources": []
}

def add_status(module, state, date=None, note=""):
    D["sources"].append({
        "module": module, "status": state, "date": date, "note": note
    })

def fnum(v):
    try:
        if pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None

def rnd(v):
    v = fnum(v)
    return round(v, 2) if v is not None else None

def retry_call(fn, attempts=3, delay=2):
    """Retry transient public API failures; raise last error if all attempts fail."""
    last_error = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay * (attempt + 1))
    raise last_error

# Index history through AkShare/Eastmoney public interface.
index_map = [
    ("沪深300", "sh000300", "hs300"),
    ("创业板指", "sz399006", "chinext"),
    ("科创50", "sh000688", "star50"),
    ("上证指数", "sh000001", None),
    ("深证成指", "sz399001", None),
]

try:
    import akshare as ak
    for name, symbol, key in index_map:
        try:
            df = retry_call(lambda: ak.stock_zh_index_daily_em(symbol=symbol))
            if df is None or df.empty:
                raise ValueError("接口返回空数据")
            df = df.copy()
            if "date" not in df.columns:
                raise ValueError("缺少 date 日期字段")
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            col = "close" if "close" in df.columns else None
            if not col:
                raise ValueError("缺少 close 收盘价字段")
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=[col])
            if df.empty:
                raise ValueError("没有有效收盘价")
            last = float(df.iloc[-1][col])
            ds = df.iloc[-1]["date"].strftime("%Y-%m-%d")

            def ret(n):
                if len(df) <= n:
                    return None
                prev = fnum(df.iloc[-(n + 1)][col])
                return round((last / prev - 1) * 100, 2) if prev not in (None, 0) else None

            D["indices"].append({
                "name": name, "latest": rnd(last), "change_pct": ret(1),
                "change_5d": ret(5), "change_20d": ret(20), "date": ds
            })
            if key:
                D["overview"][key] = rnd(last)
            D["meta"]["data_date"] = max(
                filter(None, [D["meta"]["data_date"], ds]), default=ds
            )
            add_status(name, "成功", ds, "AkShare公开指数日线；收益率由收盘价计算")
        except Exception as e:
            add_status(name, "失败", None, f"{type(e).__name__}: {str(e)[:160]}")
except Exception as e:
    add_status("指数行情", "失败", None, f"AkShare初始化失败：{type(e).__name__}: {str(e)[:160]}")

def sector_flow(sector_type):
    import akshare as ak
    df = retry_call(lambda: ak.stock_sector_fund_flow_rank(
        indicator="今日", sector_type=sector_type
    ))
    if df is None or df.empty:
        return []
    cols = list(df.columns)

    def find(*words):
        return next((c for c in cols if any(w in str(c) for w in words)), None)

    nc = find("名称", "板块")
    cc = find("涨跌幅")
    ic = find("主力净流入", "净流入")
    rc = find("主力净流入占比", "净流入占比")
    out = []
    for _, row in df.head(20).iterrows():
        name = row.get(nc) if nc else None
        inflow = fnum(row.get(ic)) if ic else None
        # Convert yuan to 亿元 only when the magnitude is consistent with yuan values.
        if inflow is not None and abs(inflow) >= 1e7:
            inflow = inflow / 1e8
        out.append({
            "name": str(name) if name is not None else "未知板块",
            "change_pct": rnd(row.get(cc)) if cc else None,
            "main_net_inflow": rnd(inflow),
            "inflow_ratio": rnd(row.get(rc)) if rc else None
        })
    out.sort(
        key=lambda x: x["main_net_inflow"] if x["main_net_inflow"] is not None else -1e30,
        reverse=True
    )
    return out

for label, typ, key in [
    ("行业板块资金", "行业资金流", "industry_flows"),
    ("概念板块资金", "概念资金流", "concept_flows")
]:
    try:
        D[key] = sector_flow(typ)
        add_status(
            label, "成功" if D[key] else "失败", D["meta"]["data_date"],
            "东方财富公开资金流向排名；资金流为供应商估算值"
        )
    except Exception as e:
        add_status(label, "失败", None, f"{type(e).__name__}: {str(e)[:160]}")

keywords = ["半导体", "CPO", "光模块", "AI应用", "电网设备",
            "黄金", "有色金属", "稀土", "储能", "电池"]
flows = D["industry_flows"] + D["concept_flows"]
for kw in keywords:
    match = next((x for x in flows if kw.lower() in x.get("name", "").lower()), None)
    D["focus_sectors"].append({
        "name": match["name"] if match else kw,
        "change_pct": match.get("change_pct") if match else None,
        "change_5d": None, "change_20d": None,
        "status": "仅当日数据；多日趋势待接入" if match else "本次资金排名未匹配到该板块"
    })

add_status("市场宽度", "待接入", None, "需要验证全市场涨跌家数的稳定来源")
add_status("估值与股债利差", "待接入", None, "历史分位/利差需稳定历史序列与口径核验后再接入")

# Merge policy: retain prior valid data for any module that failed this run.
# Successful modules replace their previous counterparts; failed/empty modules keep old data.
prev_meta = PREV.get("meta", {}) if isinstance(PREV.get("meta", {}), dict) else {}
prev_indices = PREV.get("indices", []) or []
if not D["indices"] and prev_indices:
    D["indices"] = prev_indices
    prev_overview = PREV.get("overview", {})
    if isinstance(prev_overview, dict):
        for k in ("hs300", "chinext", "star50"):
            if D["overview"].get(k) is None:
                D["overview"][k] = prev_overview.get(k)
    D["meta"]["data_date"] = prev_meta.get("data_date")
    add_status("历史数据保护", "已保留", D["meta"]["data_date"],
               "本次指数接口全部失败，沿用上次文件中的指数数据")

for key in ("industry_flows", "concept_flows"):
    if not D[key] and PREV.get(key):
        D[key] = PREV[key]
        add_status(key, "已保留", prev_meta.get("data_date"),
                   "本次接口失败或返回空数据，沿用上次文件中的数据")

# Preserve the last known data date when this run cannot determine a newer one.
if not D["meta"].get("data_date") and prev_meta.get("data_date"):
    D["meta"]["data_date"] = prev_meta.get("data_date")

# Preserve other fields until reliable data sources are implemented.
for key in ("breadth", "valuation"):
    old = PREV.get(key)
    if isinstance(old, dict):
        for field, value in old.items():
            if D[key].get(field) is None and value is not None:
                D[key][field] = value
for key in ("advancers", "decliners"):
    old = PREV.get("overview", {})
    if isinstance(old, dict) and D["overview"].get(key) is None:
        D["overview"][key] = old.get(key)

# Rebuild focus sectors from whichever current-or-retained flow data is available.
flows = (D.get("industry_flows") or []) + (D.get("concept_flows") or [])
D["focus_sectors"] = []
for kw in keywords:
    match = next((x for x in flows if kw.lower() in x.get("name", "").lower()), None)
    D["focus_sectors"].append({
        "name": match["name"] if match else kw,
        "change_pct": match.get("change_pct") if match else None,
        "change_5d": None, "change_20d": None,
        "status": "当日资金排名数据" if match else "暂无可用匹配数据"
    })

has_indices = bool(D["indices"])
has_flows = bool(D["industry_flows"] or D["concept_flows"])
if has_indices and has_flows:
    D["meta"]["overall_status"] = "行情可用；部分指标待接入"
elif has_indices:
    D["meta"]["overall_status"] = "指数行情可用；板块资金数据待排查"
elif has_flows:
    D["meta"]["overall_status"] = "板块资金数据可用；指数行情待排查"
else:
    D["meta"]["overall_status"] = "本次更新失败，已尽量保留上次有效数据"

# Critical safety: if this run and the previous file both have no useful data,
# write diagnostics; if previous data exists, merge above ensures it is not erased.
os.makedirs(os.path.dirname(OUT), exist_ok=True)
tmp = OUT + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(D, f, ensure_ascii=False, indent=2)
os.replace(tmp, OUT)

print("Wrote", OUT)
print("Data date:", D["meta"]["data_date"])
print("Indices:", len(D["indices"]),
      "Industry flows:", len(D["industry_flows"]),
      "Concept flows:", len(D["concept_flows"]))
print("Status:", D["meta"]["overall_status"])
