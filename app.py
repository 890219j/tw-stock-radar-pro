
"""台股資金雷達 PRO 2.0：完整整合版"""

import datetime as dt
import os
import tempfile
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from data import (
    listed_daily,
    institutional,
    mis_quotes,
    recent_trading_days,
)
from snapshot_store import read_snapshot, read_history
from stock_analysis import render_stock_analysis


st.set_page_config(
    page_title="台股資金雷達 PRO 2.0",
    page_icon="📡",
    layout="wide",
)

DB = Path(
    os.environ.get(
        "RADAR_DB_PATH",
        str(
            Path(tempfile.gettempdir())
            / "stock_radar_pro.db"
        ),
    )
)


def connect():
    c = sqlite3.connect(DB, timeout=10)
    c.execute(
        "CREATE TABLE IF NOT EXISTS daily "
        "(day TEXT, code TEXT, turnover REAL, "
        "close REAL, volume REAL, "
        "PRIMARY KEY(day,code))"
    )
    return c


def save_history(day, df):
    with connect() as c:
        c.executemany(
            "INSERT OR REPLACE INTO daily "
            "VALUES (?,?,?,?,?)",
            [
                (
                    day.isoformat(),
                    str(r.code),
                    float(r.turnover),
                    float(r.close)
                    if pd.notna(r.close)
                    else None,
                    float(r.volume),
                )
                for r in df.itertuples()
            ],
        )


def historical():
    with connect() as c:
        return pd.read_sql_query(
            "SELECT * FROM daily", c
        )


@st.cache_data(ttl=600, show_spinner=False)
def load_latest():
    saved = read_snapshot()

    if saved is not None:
        return saved

    errors = []

    for day in recent_trading_days(9):
        try:
            d = listed_daily(day)

            if len(d) > 100:
                return day, d

        except Exception as e:
            errors.append(f"{day}: {e}")

    raise RuntimeError(
        "近 9 日無法取得上市資料。"
        "請稍後重試。最近錯誤："
        + "; ".join(errors[:2])
    )


st.title("📡 台股資金雷達 PRO 2.0")

st.caption(
    "上市股票｜交易所公開資料｜法人淨買賣超｜"
    "資金熱力圖｜盤中報價｜異常量能｜"
    "個股 K 線｜MA｜RSI｜MACD"
)


# ===== 側邊控制中心 =====

with st.sidebar:
    st.header("控制中心")

    if st.button(
        "🔄 重新取得資料",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.rerun()

    enable_live = st.toggle(
        "查詢盤中報價",
        value=False,
        help="MIS 可能延遲或沒有成交價",
    )

    live_count = st.slider(
        "盤中報價查詢檔數",
        10, 100, 40, 10,
        disabled=not enable_live,
    )

    threshold = st.slider(
        "異常成交金額倍數門檻",
        1.2, 5.0, 1.8, 0.1,
    )

    st.caption(
        "日行情以已儲存快照優先。"
        "重新整理不代表交易所已發布新資料。"
    )


# ===== 讀取股票行情 =====

try:
    day, df = load_latest()
except Exception as e:
    st.error(str(e))
    st.stop()

df = df.copy()
df["code"] = df["code"].astype(str).str.strip()


# ===== 三大法人 =====

try:
    cols = {"foreign", "trust", "dealer"}

    if cols.issubset(df.columns):
        inst_ok = bool(
            df[
                ["foreign", "trust", "dealer"]
            ].notna().all(axis=1).any()
        )
    else:
        inst = institutional(day)
        df = df.merge(
            inst,
            on="code",
            how="left",
        )
        inst_ok = bool(
            df[
                ["foreign", "trust", "dealer"]
            ].notna().all(axis=1).any()
        )

except Exception as e:
    inst_ok = False
    st.warning(
        f"法人資料暫時不可用：{e}"
    )
    for c in ["foreign", "trust", "dealer"]:
        df[c] = np.nan

for c in ["foreign", "trust", "dealer"]:
    if c not in df.columns:
        df[c] = np.nan

df["inst_net"] = df[
    ["foreign", "trust", "dealer"]
].sum(axis=1, min_count=3)

df["turnover_100m"] = df["turnover"] / 1e8

for c in [
    "foreign",
    "trust",
    "dealer",
    "inst_net",
]:
    df[c + "_lots"] = df[c] / 1000


# ===== 歷史資料 =====

try:
    save_history(day, df)
except Exception as e:
    st.warning(f"本機歷史儲存失敗：{e}")

hist = read_history()

if hist.empty:
    hist = historical()

previous = hist[
    hist["day"] < day.isoformat()
]

if len(previous):
    base = (
        previous
        .sort_values("day")
        .groupby("code")
        .tail(5)
        .groupby("code")["turnover"]
        .agg(["mean", "count"])
        .reset_index()
    )

    base.columns = [
        "code",
        "turnover_avg",
        "history_days",
    ]

    df = df.merge(
        base,
        on="code",
        how="left",
    )

    df["turnover_ratio"] = (
        df["turnover"]
        / df["turnover_avg"].replace(0, np.nan)
    )

else:
    df["turnover_ratio"] = np.nan
    df["history_days"] = 0


st.info(
    f"資料交易日：{day.isoformat()}｜"
    "成交額與法人為日資料，非即時｜"
    f"歷史資料：{hist.day.nunique()} 個交易日"
)

if hist.day.nunique() < 4:
    st.caption(
        "⚠️ 異常量能至少需要 3 個"
        "過去交易日作為比較基準。"
    )


# ===== 個股搜尋 =====

search = st.text_input(
    "🔎 股票代號或名稱",
    placeholder="例如 2330、台積電",
)

if search:
    filtered = df[
        df["code"].str.contains(
            search, regex=False
        )
        |
        df["name"].astype(str).str.contains(
            search, regex=False
        )
    ]
else:
    filtered = df


# ===== 市場總覽 =====

m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "上市股票成交總額",
    f"{df.turnover.sum() / 1e8:,.0f} 億",
)

m2.metric(
    "法人合計淨買賣超",
    (
        f"{df.inst_net.sum() / 1000:+,.0f} 張"
        if inst_ok
        else "資料未公布"
    ),
)

m3.metric(
    "上漲 / 下跌",
    f"{int((df.pct > 0).sum())} / "
    f"{int((df.pct < 0).sum())}",
)

m4.metric(
    "當日股票數",
    f"{len(df):,}",
)


# ===== 七大分析頁籤 =====

tabs = st.tabs([
    "🔥 資金排行",
    "🏦 法人追蹤",
    "🗺️ 資金熱力圖",
    "⚡ 盤中報價",
    "🚨 警報與觀察名單",
    "📚 歷史資料",
    "📈 個股 K 線分析",
])


# ===== 1. 資金排行 =====

with tabs[0]:
    st.subheader("🔥 成交金額排行榜")

    top = filtered.sort_values(
        "turnover",
        ascending=False,
    ).head(30)

    if not top.empty:
        fig = px.bar(
            top.head(20).sort_values(
                "turnover_100m"
            ),
            x="turnover_100m",
            y="name",
            orientation="h",
            hover_data=["code", "pct"],
            labels={
                "turnover_100m": "成交金額（億元）",
                "name": "股票",
            },
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
        )

        st.dataframe(
            top[
                [
                    "code",
                    "name",
                    "close",
                    "pct",
                    "turnover_100m",
                    "volume",
                    "turnover_ratio",
                ]
            ].rename(columns={
                "code": "代號",
                "name": "名稱",
                "close": "收盤",
                "pct": "漲跌幅%",
                "turnover_100m": "成交額(億)",
                "volume": "成交股數",
                "turnover_ratio": "成交額/歷史均值",
            }),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("沒有符合條件的股票")


# ===== 2. 法人追蹤 =====

with tabs[1]:
    st.subheader("🏦 三大法人追蹤")

    if inst_ok:
        choices = {
            "inst_net_lots": "三大法人合計",
            "foreign_lots": "外資",
            "trust_lots": "投信",
            "dealer_lots": "自營商",
        }

        kind = st.selectbox(
            "排序依據",
            list(choices.keys()),
            format_func=lambda x: choices[x],
        )

        cols = [
            "code",
            "name",
            "foreign_lots",
            "trust_lots",
            "dealer_lots",
            "inst_net_lots",
        ]

        buy, sell = st.columns(2)

        with buy:
            st.subheader("買超前 20")
            st.dataframe(
                filtered.nlargest(
                    20, kind
                )[cols],
                hide_index=True,
                use_container_width=True,
            )

        with sell:
            st.subheader("賣超前 20")
            st.dataframe(
                filtered.nsmallest(
                    20, kind
                )[cols],
                hide_index=True,
                use_container_width=True,
            )

        st.caption(
            "法人單位為張，1 張 = 1,000 股。"
            "買賣超張數不能直接視為現金流入。"
        )

    else:
        st.warning(
            "目前沒有完整的三大法人資料"
        )


# ===== 3. 資金熱力圖 =====

with tabs[2]:
    st.subheader("🗺️ 資金熱力圖")

    st.caption(
        "方塊大小代表成交金額，"
        "顏色代表漲跌幅，不是淨資金流入。"
    )

    heat = (
        filtered.nlargest(80, "turnover")
        .dropna(subset=["pct", "turnover"])
    )

    if not heat.empty:
        fig = px.treemap(
            heat,
            path=[
                px.Constant("台股上市"),
                "name",
            ],
            values="turnover",
            color="pct",
            color_continuous_scale="RdYlGn",
            color_continuous_midpoint=0,
            hover_data=[
                "code",
                "turnover_100m",
            ],
        )

        fig.update_layout(
            height=650,
            margin=dict(
                t=10, l=10, r=10, b=10
            ),
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
        )

    st.subheader("自訂產業分類")

    st.caption(
        "可上傳包含 code,sector 欄位的 CSV。"
    )

    up = st.file_uploader(
        "上傳產業分類 CSV",
        type="csv",
    )

    if up:
        try:
            sectors = pd.read_csv(
                up, dtype={"code": str}
            )

            if not {
                "code", "sector"
            }.issubset(sectors.columns):
                raise ValueError(
                    "CSV 需要 code,sector 欄位"
                )

            merged = df.merge(
                sectors[
                    ["code", "sector"]
                ].drop_duplicates("code"),
                on="code",
                how="left",
            )

            sec = (
                merged.dropna(subset=["sector"])
                .groupby("sector", as_index=False)
                .agg(
                    turnover=("turnover", "sum"),
                    count=("code", "count"),
                )
            )

            sec["億元"] = (
                sec["turnover"] / 1e8
            )

            st.plotly_chart(
                px.bar(
                    sec.sort_values(
                        "億元",
                        ascending=False,
                    ),
                    x="sector",
                    y="億元",
                    hover_data=["count"],
                ),
                use_container_width=True,
            )

        except Exception as e:
            st.error(
                f"分類檔無法讀取：{e}"
            )


# ===== 4. 盤中報價 =====

with tabs[3]:
    st.subheader("⚡ 盤中報價")

    st.warning(
        "MIS 非交易所授權行情串流，"
        "可能延遲、空值或受到存取限制。"
    )

    if enable_live:
        codes = (
            filtered.nlargest(
                live_count, "turnover"
            )["code"].tolist()
        )

        try:
            q = mis_quotes(tuple(codes))

            if len(q):
                out = q.merge(
                    df[
                        ["code", "name", "close"]
                    ],
                    on="code",
                    how="left",
                )

                st.dataframe(
                    out.rename(columns={
                        "code": "代號",
                        "name": "名稱",
                        "last": "最近成交價",
                        "bid": "最佳買價",
                        "ask": "最佳賣價",
                        "quote_time": "報價時間",
                        "quote_date": "報價日期",
                        "close": "日資料收盤價",
                    }),
                    hide_index=True,
                    use_container_width=True,
                )

                st.caption(
                    "報價時間以來源回傳為準。"
                    "日資料收盤價不是即時成交價。"
                )

            else:
                st.info(
                    "目前沒有可用報價"
                )

        except Exception as e:
            st.error(
                f"盤中報價查詢失敗：{e}"
            )

    else:
        st.info(
            "請在左側控制中心開啟盤中報價"
        )


# ===== 5. 警報與觀察名單 =====

with tabs[4]:
    st.subheader("🚨 異常量能警報")

    valid = df[
        (df["history_days"] >= 3)
        & (df["turnover_ratio"] >= threshold)
        & (df["pct"] > 0)
    ]

    if inst_ok:
        valid = valid[
            valid["inst_net"] > 0
        ]

    st.dataframe(
        valid.sort_values(
            "turnover_ratio",
            ascending=False,
        )[
            [
                "code",
                "name",
                "pct",
                "turnover_100m",
                "turnover_ratio",
                "inst_net_lots",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )

    st.caption(
        "警報僅為頁面內的篩選結果，"
        "並非背景推播通知。"
    )

    st.subheader("自訂觀察名單")

    watch = st.text_input(
        "股票代號，以逗號分隔",
        "2330,2317,2454",
    )

    codes = [
        x.strip()
        for x in watch.split(",")
        if x.strip()
    ]

    st.dataframe(
        df[
            df["code"].isin(codes)
        ][
            [
                "code",
                "name",
                "close",
                "pct",
                "turnover_100m",
                "inst_net_lots",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )


# ===== 6. 歷史資料 =====

with tabs[5]:
    st.subheader("📚 歷史資料")

    st.dataframe(
        hist.sort_values(
            ["day", "turnover"],
            ascending=[False, False],
        ).head(500),
        hide_index=True,
        use_container_width=True,
    )

    st.download_button(
        "下載已累積歷史 CSV",
        hist.to_csv(
            index=False
        ).encode("utf-8-sig"),
        "radar_history.csv",
        "text/csv",
    )

    st.download_button(
        "下載當日完整 CSV",
        df.to_csv(
            index=False
        ).encode("utf-8-sig"),
        f"radar_{day}.csv",
        "text/csv",
    )


# ===== 7. 新增：個股 K 線分析 =====

with tabs[6]:
    st.subheader("📈 個股 K 線與技術指標")

    st.caption(
        "台股上市個股｜日 K 線｜"
        "MA5/10/20/60｜RSI｜MACD"
    )

    technical_code = st.text_input(
        "輸入四位數上市股票代號",
        value="2330",
        max_chars=4,
        key="technical_stock_code",
    ).strip()

    if (
        len(technical_code) == 4
        and technical_code.isdigit()
    ):
        render_stock_analysis(
            technical_code
        )
    else:
        st.info(
            "請輸入有效的四位數上市股票代號"
        )


# ===== 風險提醒 =====

st.divider()

st.caption(
    "本系統為研究與觀察工具，"
    "不構成投資建議。"
    "成交金額不是淨資金流入，"
    "法人淨買賣超為股數差額。"
    "技術指標不能保證未來股價走勢。"
)
