from pathlib import Path
import numpy as np
import pandas as pd

FEATURES = ["ret5", "ret20", "ma20_gap", "ma60_gap", "vol_ratio", "volatility20"]

def load_stock(path):
    df = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
    df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    required = {"close", "high", "low", "open", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"缺少欄位: {required - set(df.columns)}")
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")].copy()
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "volume"])
    df = df[(df["close"] > 0) & (df["volume"] >= 0)]
    return df

def make_features(df):
    d = df.copy()
    c = d["close"]
    v = d["volume"]
    d["ret5"] = c.pct_change(5)
    d["ret20"] = c.pct_change(20)
    d["ma20_gap"] = c / c.rolling(20).mean() - 1
    d["ma60_gap"] = c / c.rolling(60).mean() - 1
    d["vol_ratio"] = v / v.rolling(20).mean().replace(0, np.nan)
    d["volatility20"] = c.pct_change().rolling(20).std()
    return d.replace([np.inf, -np.inf], np.nan)

if __name__ == "__main__":
    files = sorted(Path("ai_data").glob("*.csv"))
    print("找到股票檔案：", len(files))
    for path in files:
        try:
            df = make_features(load_stock(path))
            valid = df.dropna(subset=FEATURES)
            print(f"{path.stem}: 原始 {len(df)} 筆，可用 {len(valid)} 筆")
        except Exception as e:
            print(f"{path.stem}: 讀取失敗：{e}")
