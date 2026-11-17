from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import streamlit as st
from ai_model import load_stock, make_features

MODELS = {
    "短線・5日": "short",
    "波段・20日": "swing",
    "長期・60日": "long",
}

@st.cache_resource
def get_model(name):
    path = Path("ai_models") / f"{name}.joblib"
    if not path.exists():
        raise FileNotFoundError(path)
    return joblib.load(path)

@st.cache_data(ttl=3600)
def stock_features(path, modified):
    data = make_features(load_stock(path))
    return data

def render_ai_screener(df, day):
    st.subheader("🤖 AI 智慧選股 PRO 4.0")
    st.warning(
        "實驗性機器學習模型，尚未證明優於基準。"
        "模型分數未經機率校準，不是買進建議。"
    )

    selected = st.selectbox(
        "選擇 AI 策略",
        list(MODELS),
        key="ml_strategy",
    )
    key = MODELS[selected]

    try:
        saved = get_model(key)
        model = saved["model"]
        features = saved["features"]
    except Exception as e:
        st.error(f"模型讀取失敗：{e}")
        return

    names = {}
    if {"code", "name"}.issubset(df.columns):
        names = dict(zip(
            df["code"].astype(str),
            df["name"].astype(str),
        ))

    results = []
    errors = []

    for path in sorted(Path("ai_data").glob("*.csv")):
        try:
            data = stock_features(
                str(path), path.stat().st_mtime
            )
            valid = data[features].replace(
                [np.inf, -np.inf], np.nan
            ).dropna()

            if valid.empty:
                continue

            latest = valid.tail(1)
            datestr = latest.index[-1].strftime("%Y-%m-%d")
            classes = list(model.classes_)

            if 1 not in classes:
                raise ValueError("模型沒有上漲類別 1")

            idx = classes.index(1)
            probability = float(
                model.predict_proba(latest)[0][idx]
            )

            code = path.stem
            results.append({
                "代號": code,
                "股票名稱": names.get(code, code),
                "資料日期": datestr,
                "模型分類1分數": round(
                    probability * 100, 2
                ),
                "模型分類": int(
                    model.predict(latest)[0]
                ),
                "歷史收盤價": round(
                    float(data["close"].loc[latest.index[-1]]), 2
                ),
            })
        except Exception as e:
            errors.append(f"{path.stem}: {e}")

    if not results:
        st.error("沒有可用的 AI 預測結果")
        if errors:
            st.caption("; ".join(errors[:3]))
        return

    result = pd.DataFrame(results)
    result = result.sort_values(
        "模型分類1分數", ascending=False
    )

    st.metric("已分析股票", len(result))
    st.caption(
        f"預測期間：{saved['horizon']} 個交易日"
        "｜分類1代表訓練標籤中的未來上漲"
    )

    latest_date = result["資料日期"].max()
    st.info(f"歷史行情最新日期：{latest_date}")

    older = result[
        result["資料日期"] != latest_date
    ]
    if not older.empty:
        st.warning(
            f"{len(older)} 檔股票資料日期不同，"
            "比較排名時需注意。"
        )

    st.dataframe(
        result,
        hide_index=True,
        use_container_width=True,
    )

    st.caption(
        "目前只分析 ai_data 中已有的股票。"
        "模型分類1分數不是經驗證的上漲機率。"
        "長期策略尚未加入完整基本面資訊。"
    )
    if errors:
        with st.expander("資料讀取問題"):
            st.write(errors)
