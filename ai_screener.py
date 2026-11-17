
import numpy as np
import pandas as pd
import streamlit as st


def render_ai_screener(df, day):
    st.subheader("🤖 AI 智慧選股 PRO")
    st.caption(
        f"資料日期：{day}｜規則式選股，非即時預測"
    )

    strategy = st.radio(
        "選股策略",
        ["短線", "波段", "長期"],
        horizontal=True,
        key="ai_strategy",
    )

    data = df.copy()

    if data.empty:
        st.warning("目前沒有股票資料")
        return

    def score(row):
        points = 0

        pct = row.get("pct", np.nan)
        ratio = row.get("turnover_ratio", np.nan)
        inst = row.get("inst_net_lots", np.nan)

        if pd.notna(pct):
            if strategy == "短線":
                points += 35 if 1 <= pct <= 5 else 0
            elif strategy == "波段":
                points += 30 if 0 < pct <= 4 else 0
            else:
                points += 20 if pct > 0 else 0

        if pd.notna(ratio):
            if strategy == "短線":
                points += 35 if ratio >= 1.5 else 0
            elif strategy == "波段":
                points += 35 if ratio >= 1.2 else 0
            else:
                points += 20 if ratio >= 1 else 0

        if pd.notna(inst):
            if strategy == "短線":
                points += 30 if inst > 0 else 0
            elif strategy == "波段":
                points += 35 if inst > 0 else 0
            else:
                points += 20 if inst > 0 else 0

        return points

    data["AI評分"] = data.apply(score, axis=1)

    data["訊號"] = np.select(
        [
            data["AI評分"] >= 80,
            data["AI評分"] >= 50,
        ],
        [
            "🟢 優先觀察",
            "🟡 持續追蹤",
        ],
        default="⚪ 暫不符合",
    )

    min_score = st.slider(
        "最低評分",
        0, 100, 50, 5,
        key="ai_min_score",
    )

    result = data[
        data["AI評分"] >= min_score
    ].sort_values("AI評分", ascending=False)

    st.metric("符合條件股票數", len(result))

    columns = [
        "code", "name", "close",
        "pct", "turnover_ratio",
        "inst_net_lots", "AI評分", "訊號",
    ]

    st.dataframe(
        result[columns].rename(columns={
            "code": "股票代號",
            "name": "股票名稱",
            "close": "收盤價",
            "pct": "漲跌幅%",
            "turnover_ratio": "量能倍數",
            "inst_net_lots": "法人買賣超(張)",
        }),
        hide_index=True,
        use_container_width=True,
    )

    st.caption(
        "分數僅依目前可用資料計算。"
        "缺少歷史量能或法人資料會影響評分。"
        "長期策略尚未納入財報、估值及多年趨勢，"
        "不可當作完整長期投資評估。"
        "訊號不代表建議買入或保證獲利。"
    )
