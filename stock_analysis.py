
"""台股資金雷達 PRO 2.0：個股 K 線分析"""

import datetime as dt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from data import get_json, number


@st.cache_data(ttl=3600, show_spinner=False)
def stock_history(code):
    """取得上市股票近 8 個月歷史行情"""
    today = dt.datetime.now(
        dt.timezone(dt.timedelta(hours=8))
    ).date()

    frames = []
    errors = []

    for i in range(8):
        idx = today.year * 12 + today.month - 1 - i
        year, m0 = divmod(idx, 12)
        month = m0 + 1

        try:
            j = get_json(
                "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
                {
                    "response": "json",
                    "date": f"{year}{month:02d}01",
                    "stockNo": str(code),
                }
            )

            fields = j.get("fields", [])
            rows = j.get("data", [])

            if not rows:
                continue

            df = pd.DataFrame(rows, columns=fields)

            df = df.rename(columns={
                "日期": "date",
                "成交股數": "volume",
                "開盤價": "open",
                "最高價": "high",
                "最低價": "low",
                "收盤價": "close",
            })

            required = [
                "date", "open", "high",
                "low", "close", "volume"
            ]

            if not set(required).issubset(df.columns):
                continue

            def parse_date(value):
                y, m, d = str(value).split("/")
                return dt.date(
                    int(y) + 1911, int(m), int(d)
                )

            df["date"] = df["date"].map(parse_date)

            for col in required[1:]:
                df[col] = df[col].map(number)

            frames.append(df[required])

        except Exception as e:
            errors.append(str(e)[:120])

    if not frames:
        detail = errors[0] if errors else "無可用行情"
        raise RuntimeError(
            "歷史行情讀取失敗：" + detail
        )

    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates("date")
    result = result.dropna(
        subset=["open", "high", "low", "close"]
    )
    result = result[result["date"] <= today]
    result = result.sort_values("date")

    return result.reset_index(drop=True)


def add_indicators(df):
    """計算均線、RSI、MACD"""
    df = df.copy()

    for n in (5, 10, 20, 60):
        df[f"MA{n}"] = df["close"].rolling(
            window=n, min_periods=n
        ).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["RSI"] = 100 - 100 / (1 + rs)

    df.loc[
        (avg_loss == 0) & (avg_gain > 0), "RSI"
    ] = 100

    df.loc[
        (avg_loss == 0) & (avg_gain == 0), "RSI"
    ] = 50

    ema12 = df["close"].ewm(
        span=12, adjust=False
    ).mean()

    ema26 = df["close"].ewm(
        span=26, adjust=False
    ).mean()

    df["MACD"] = ema12 - ema26

    df["Signal"] = df["MACD"].ewm(
        span=9, adjust=False
    ).mean()

    df["Histogram"] = df["MACD"] - df["Signal"]

    return df


def render_stock_analysis(code="2330"):
    """顯示個股技術分析介面"""
    st.subheader(f"📈 {code} 個股技術分析")

    try:
        with st.spinner("取得歷史行情中..."):
            df = add_indicators(stock_history(code))
    except Exception as e:
        st.warning(str(e))
        return

    if df.empty:
        st.info("找不到有效歷史行情")
        return

    last = df.iloc[-1]

    st.caption(
        f"資料交易日：{last['date']}｜"
        "臺灣證券交易所｜非即時行情"
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "收盤價", f"{last['close']:.2f}"
    )

    c2.metric(
        "MA20",
        f"{last['MA20']:.2f}"
        if pd.notna(last["MA20"])
        else "資料不足"
    )

    c3.metric(
        "RSI(14)",
        f"{last['RSI']:.1f}"
        if pd.notna(last["RSI"])
        else "資料不足"
    )

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.48, 0.17, 0.18, 0.17]
    )

    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="日 K 線",
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a"
        ),
        row=1, col=1
    )

    colors = {
        "MA5": "#f9a825",
        "MA10": "#42a5f5",
        "MA20": "#ab47bc",
        "MA60": "#ff7043",
    }

    for ma, color in colors.items():
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df[ma],
                mode="lines",
                name=ma,
                line=dict(color=color, width=1.5)
            ),
            row=1, col=1
        )

    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["volume"] / 1000,
            name="成交量（張）",
            marker_color="#78909c"
        ),
        row=2, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["RSI"],
            name="RSI(14)",
            line=dict(color="#ffb300")
        ),
        row=3, col=1
    )

    for level in (30, 70):
        fig.add_hline(
            y=level,
            row=3, col=1,
            line_dash="dot",
            line_color="gray"
        )

    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["Histogram"],
            name="MACD 柱狀",
            marker_color="#90a4ae"
        ),
        row=4, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["MACD"],
            name="MACD",
            line=dict(color="#42a5f5")
        ),
        row=4, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["Signal"],
            name="訊號線",
            line=dict(color="#ff7043")
        ),
        row=4, col=1
    )

    fig.update_layout(
        height=850,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        margin=dict(l=5, r=5, t=25, b=15),
        legend=dict(
            orientation="h",
            y=1.04,
            x=0
        )
    )

    fig.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])]
    )

    st.plotly_chart(
        fig, use_container_width=True
    )

    st.caption(
        "均線、RSI、MACD 均由歷史行情計算。"
        "技術指標僅供研究，不保證未來漲跌。"
    )

    with st.expander("查看歷史行情與指標"):
        st.dataframe(
            df.sort_values(
                "date", ascending=False
            ),
            hide_index=True,
            use_container_width=True
        )


if __name__ == "__main__":
    st.set_page_config(
        page_title="台股資金雷達 PRO 2.0",
        page_icon="📈",
        layout="wide"
    )

    st.title("📡 台股資金雷達 PRO 2.0")

    code = st.text_input(
        "股票代號",
        value="2330",
        max_chars=4
    ).strip()

    if len(code) == 4 and code.isdigit():
        render_stock_analysis(code)
    else:
        st.info("請輸入四位數上市股票代號")

