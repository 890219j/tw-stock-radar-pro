
"""台股資金雷達 PRO - TWSE 資料模組"""

import datetime as dt
import re
import time
import requests
import pandas as pd
import streamlit as st

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.twse.com.tw/",
})


def number(v):
    try:
        s = str(v).replace(",", "").replace("+", "")
        s = s.replace("%", "").strip()
        if s in ("", "--", "---", "X", "nan", "None"):
            return float("nan")
        return float(s)
    except (ValueError, TypeError):
        return float("nan")


def get_json(url, params=None):
    last_error = None
    for attempt in range(3):
        try:
            r = S.get(url, params=params, timeout=25)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last_error = e
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError(f"證交所連線失敗：{last_error}")


def find_stock_table(j):
    """相容 tables 與 fieldsN/dataN 格式"""
    tables = j.get("tables", [])
    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue
            fields = table.get("fields", [])
            rows = table.get("data", [])
            if (
                isinstance(fields, list)
                and isinstance(rows, list)
                and "證券代號" in fields
                and "成交金額" in fields
                and "收盤價" in fields
                and rows
            ):
                return fields, rows

    for k, fields in j.items():
        if not k.startswith("fields"):
            continue
        if not isinstance(fields, list):
            continue
        if (
            "證券代號" in fields
            and "成交金額" in fields
            and "收盤價" in fields
        ):
            rows = j.get("data" + k[6:], [])
            if isinstance(rows, list) and rows:
                return fields, rows
    return None, None


@st.cache_data(ttl=900, show_spinner=False)
def listed_daily(day):
    date_str = day.strftime("%Y%m%d")
    urls = [
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
        "https://www.twse.com.tw/exchangeReport/MI_INDEX",
    ]
    params = {
        "response": "json",
        "date": date_str,
        "type": "ALLBUT0999",
    }

    fields, rows = None, None
    errors = []

    for url in urls:
        try:
            j = get_json(url, params)
            fields, rows = find_stock_table(j)
            if fields is not None:
                break
            errors.append(str(j.get("stat", "找不到股票表格")))
        except Exception as e:
            errors.append(str(e))

    if fields is None:
        raise ValueError(
            f"{date_str} 無法取得上市行情："
            + "；".join(errors)
        )

    df = pd.DataFrame(rows, columns=fields)
    rename = {
        "證券代號": "code",
        "證券名稱": "name",
        "成交股數": "volume",
        "成交金額": "turnover",
        "收盤價": "close",
        "漲跌價差": "change",
        "開盤價": "open",
        "最高價": "high",
        "最低價": "low",
    }
    df = df.rename(columns=rename)
    df["code"] = df["code"].astype(str).str.strip()
    df = df[df["code"].str.fullmatch(r"\d{4}")].copy()

    for c in [
        "volume", "turnover", "close", "change",
        "open", "high", "low"
    ]:
        if c in df.columns:
            df[c] = df[c].map(number)
        else:
            df[c] = float("nan")

    sign_col = next(
        (c for c in df.columns if "漲跌(" in c),
        None
    )
    if sign_col:
        def sign_value(v):
            raw = str(v)
            plain = re.sub(r"<[^>]*>", "", raw).strip()
            if "-" in plain or "－" in plain:
                return -1
            if "+" in plain or "＋" in plain:
                return 1
            if "green" in raw.lower():
                return -1
            return 1

        df["change"] = (
            df["change"].abs()
            * df[sign_col].map(sign_value)
        )

    df["change"] = df["change"].fillna(0)
    df["prev_close"] = df["close"] - df["change"]
    df["pct"] = (
        df["change"]
        / df["prev_close"].where(df["prev_close"] > 0)
        * 100
    )
    df["market"] = "上市"

    if df.empty:
        raise ValueError(f"{date_str} 找不到上市股票")
    return df


@st.cache_data(ttl=900, show_spinner=False)
def institutional(day):
    date_str = day.strftime("%Y%m%d")
    urls = [
        "https://www.twse.com.tw/rwd/zh/fund/T86",
        "https://www.twse.com.tw/fund/T86",
    ]
    params = {
        "response": "json",
        "date": date_str,
        "selectType": "ALLBUT0999",
    }

    j = None
    for url in urls:
        try:
            candidate = get_json(url, params)
            if candidate.get("fields") and candidate.get("data"):
                j = candidate
                break
        except Exception:
            continue

    if j is None:
        raise ValueError(
            f"{date_str} 三大法人資料尚未公布或無法取得"
        )

    df = pd.DataFrame(j["data"], columns=j["fields"])
    code = next(
        (c for c in df.columns if "證券代號" in c),
        None
    )
    if code is None:
        raise ValueError("法人資料格式已更改")

    df = df.rename(columns={code: "code"})
    df["code"] = df["code"].astype(str).str.strip()

    aliases = {
        "foreign": [
            "外陸資買賣超股數(不含外資自營商)",
            "外資及陸資買賣超股數(不含外資自營商)",
        ],
        "trust": ["投信買賣超股數"],
        "dealer": ["自營商買賣超股數"],
    }

    for target, patterns in aliases.items():
        found = next(
            (c for p in patterns for c in df.columns if p in c),
            None
        )
        df[target] = (
            df[found].map(number) if found else 0.0
        )

    return df[
        ["code", "foreign", "trust", "dealer"]
    ].drop_duplicates("code")


@st.cache_data(ttl=35, show_spinner=False)
def mis_quotes(codes):
    if not codes:
        return pd.DataFrame()

    result = []
    for start in range(0, len(codes), 40):
        chunk = codes[start:start + 40]
        try:
            j = get_json(
                "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
                {
                    "ex_ch": "|".join(
                        "tse_" + str(c) + ".tw" for c in chunk
                    ),
                    "json": "1",
                    "delay": "0",
                },
            )
            for x in j.get("msgArray", []):
                price = number(x.get("z"))
                if pd.isna(price):
                    price = number(x.get("y"))
                result.append({
                    "code": x.get("c"),
                    "last": price,
                    "bid": number(
                        (x.get("b") or "").split("_")[0]
                    ),
                    "ask": number(
                        (x.get("a") or "").split("_")[0]
                    ),
                    "quote_time": x.get("t", ""),
                    "quote_date": x.get("d", ""),
                })
        except Exception:
            continue

    return pd.DataFrame(result)


def recent_trading_days(n=7):
    today = dt.datetime.now(
        dt.timezone(dt.timedelta(hours=8))
    ).date()
    return [
        today - dt.timedelta(days=i)
        for i in range(n)
    ]
