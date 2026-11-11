from pathlib import Path
import datetime as dt
import pandas as pd

BASE = Path(__file__).resolve().parent / "snapshots"

def read_snapshot():
    path = BASE / "latest.csv"
    if not path.exists():
        return None

    df = pd.read_csv(path, dtype={"code": str})
    required = {
        "day", "code", "name", "turnover",
        "close", "volume", "pct"
    }
    if not required.issubset(df.columns) or len(df) < 100:
        raise ValueError("儲存的行情資料不完整")

    days = df["day"].dropna().unique()
    if len(days) != 1:
        raise ValueError("行情資料日期不一致")

    day = dt.date.fromisoformat(str(days[0]))
    today = dt.datetime.now(
        dt.timezone(dt.timedelta(hours=8))
    ).date()

    if day > today:
        raise ValueError("行情日期異常")

    return day, df.drop(columns=["day"])

def read_history():
    path = BASE / "history.csv"
    if path.exists():
        return pd.read_csv(path, dtype={"code": str})
    return pd.DataFrame()
