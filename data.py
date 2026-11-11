
"""台股資金雷達 PRO：TWSE 行情與法人資料"""

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
    error = None
    for attempt in range(2):
        try:
            r = S.get(url, params=params, timeout=18)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            error = e
            if attempt == 0:
                time.sleep(0.5)
    raise RuntimeError(f"API 讀取失敗：{error}")


def find_stock_table(j):
    if not isinstance(j, dict):
        return None, None

    for t in j.get("tables", []):
        if not isinstance(t, dict):
            continue
        f, rows = t.get("fields"), t.get("data")
        if (
            isinstance(f, list)
            and isinstance(rows, list)
            and rows
            and all(x in f for x in
                    ("證券代號", "成交金額", "收盤價"))
        ):
            return f, rows

    for k, f in j.items():
        if not k.startswith("fields"):
            continue
        if not isinstance(f, list):
            continue
        if all(x in f for x in
               ("證券代號", "成交金額", "收盤價")):
            rows = j.get("data" + k[6:])
            if isinstance(rows, list) and rows:
                return f, rows
    return None, None


def finalize(df):
    df["code"] = df["code"].astype(str).str.strip()
    df = df[df["code"].str.fullmatch(r"\d{4}")].copy()

    for c in ("volume", "turnover", "close", "change",
              "open", "high", "low"):
        if c in df.columns:
            df[c] = df[c].map(number)
        else:
            df[c] = float("nan")

    df["change"] = df["change"].fillna(0)
    df["prev_close"] = df["close"] - df["change"]
    df["pct"] = (
        df["change"]
        / df["prev_close"].where(df["prev_close"] > 0)
        * 100
    )
    df["market"] = "上市"

    if len(df) < 100:
        raise ValueError(
            f"有效上市股票資料不足：{len(df)} 筆"
        )
    return df


def parse_mi_index(j):
    fields, rows = find_stock_table(j)
    if fields is None:
        raise ValueError(
            f"找不到個股行情表格：{j.get('stat', '')}"
        )

    df = pd.DataFrame(rows, columns=fields)
    df = df.rename(columns={
        "證券代號": "code",
        "證券名稱": "name",
        "成交股數": "volume",
        "成交金額": "turnover",
        "收盤價": "close",
        "漲跌價差": "change",
        "開盤價": "open",
        "最高價": "high",
        "最低價": "low",
    })

    sign_col = next(
        (c for c in df.columns
         if "漲跌(" in c or "漲跌（" in c),
        None
    )

    if sign_col:
        def sign(v):
            raw = str(v)
            s = re.sub(r"<[^>]*>", "", raw)
            if "-" in s or "－" in s:
                return -1
            if "green" in raw.lower():
                return -1
            return 1

        df["change"] = (
            df["change"].map(number).abs()
            * df[sign_col].map(sign)
        )

    return finalize(df)


def parse_openapi(j, day):
    if not isinstance(j, list) or not j:
        raise ValueError("備援 API 沒有股票資料")

    dates = {
        str(x.get("Date", "")).strip()
        for x in j if isinstance(x, dict)
    }
    dates.discard("")

    expected = f"{day.year - 1911:03d}{day:%m%d}"

    if dates != {expected}:
        raise ValueError(
            f"備援資料日期 {sorted(dates)} "
            f"不符合查詢日 {expected}"
        )

    df = pd.DataFrame(j)
    df = df.rename(columns={
        "Code": "code",
        "Name": "name",
        "TradeVolume": "volume",
        "TradeValue": "turnover",
        "ClosingPrice": "close",
        "Change": "change",
        "OpeningPrice": "open",
        "HighestPrice": "high",
        "LowestPrice": "low",
    })
    return finalize(df)


@st.cache_data(ttl=900, show_spinner=False)
def listed_daily(day):
    params = {
        "response": "json",
        "date": day.strftime("%Y%m%d"),
        "type": "ALLBUT0999",
    }

    errors = []

    urls = [
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
        "https://www.twse.com.tw/exchangeReport/MI_INDEX",
    ]

    for url in urls:
        try:
            return parse_mi_index(get_json(url, params))
        except Exception as e:
            errors.append(f"MI_INDEX：{str(e)[:150]}")

    backup_urls = [
        "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL",
    ]

    for url in backup_urls:
        try:
            return parse_openapi(get_json(url), day)
        except Exception as e:
            errors.append(
                f"STOCK_DAY_ALL：{str(e)[:150]}"
            )

    raise RuntimeError(
        f"{day} 無法取得行情：" + "；".join(errors)
    )


@st.cache_data(ttl=900, show_spinner=False)
def institutional(day):
    params = {
        "response": "json",
        "date": day.strftime("%Y%m%d"),
        "selectType": "ALLBUT0999",
    }

    urls = [
        "https://www.twse.com.tw/rwd/zh/fund/T86",
        "https://www.twse.com.tw/fund/T86",
    ]

    error = None

    for url in urls:
        try:
            j = get_json(url, params)
            if not j.get("fields") or not j.get("data"):
                raise ValueError("法人資料未公布")

            df = pd.DataFrame(
                j["data"], columns=j["fields"]
            )

            code_col = next(
                (c for c in df.columns
                 if "證券代號" in c),
                None
            )
            if code_col is None:
                raise ValueError("缺少證券代號")

            df = df.rename(columns={code_col: "code"})
            df["code"] = df["code"].astype(str).str.strip()

            aliases = {
                "foreign": [
                    "外陸資買賣超股數(不含外資自營商)",
                    "外資及陸資買賣超股數(不含外資自營商)",
                ],
                "trust": ["投信買賣超股數"],
                "dealer": ["自營商買賣超股數"],
            }

            for target, names in aliases.items():
                found = next(
                    (c for name in names
                     for c in df.columns if name in c),
                    None
                )
                df[target] = (
                    df[found].map(number)
                    if found else float("nan")
                )

            return df[
                ["code", "foreign", "trust", "dealer"]
            ].drop_duplicates("code")

        except Exception as e:
            error = e

    raise RuntimeError(f"三大法人資料失敗：{error}")


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
                        f"tse_{c}.tw" for c in chunk
                    ),
                    "json": "1",
                    "delay": "0",
                }
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
