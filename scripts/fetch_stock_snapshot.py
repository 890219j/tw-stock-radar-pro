from pathlib import Path
import datetime as dt
import json
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data import (
    listed_daily, institutional,
    get_json, parse_openapi
)

BASE = ROOT / "snapshots"
BASE.mkdir(parents=True, exist_ok=True)

now = dt.datetime.now(
    dt.timezone(dt.timedelta(hours=8))
)
today = now.date()
result = None
errors = []

try:
    raw = get_json(
        "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    )
    roc = str(raw[0]["Date"]).strip()
    day = dt.date(
        int(roc[:-4]) + 1911,
        int(roc[-4:-2]),
        int(roc[-2:])
    )

    if day > today or (today - day).days > 10:
        raise ValueError("備援資料日期異常")

    result = (day, parse_openapi(raw, day))
except Exception as e:
    errors.append(str(e))

for delta in range(8):
    day = today - dt.timedelta(days=delta)
    if result is not None and day <= result[0]:
        break
    try:
        df = listed_daily(day)
        if len(df) >= 100:
            result = (day, df)
            break
    except Exception as e:
        errors.append(str(e)[:120])

if result is None:
    raise SystemExit(
        "行情更新失敗，保留舊資料：" +
        "; ".join(errors[:3])
    )

day, df = result

try:
    inst = institutional(day)
    df = df.merge(inst, on="code", how="left")
    inst_ok = True
except Exception as e:
    print("法人資料暫時不可用：", e)
    inst_ok = False
    for col in ("foreign", "trust", "dealer"):
        df[col] = float("nan")

df.insert(0, "day", day.isoformat())

df.to_csv(
    BASE / "latest.csv",
    index=False,
    encoding="utf-8-sig"
)

cols = ["day", "code", "turnover", "close", "volume"]
history = df[cols].copy()
history_path = BASE / "history.csv"

if history_path.exists():
    old = pd.read_csv(
        history_path, dtype={"code": str}
    )
    history = pd.concat(
        [old, history], ignore_index=True
    )

history = history.drop_duplicates(
    ["day", "code"], keep="last"
)
days = sorted(
    history["day"].unique(), reverse=True
)[:16]
history = history[history["day"].isin(days)]

history.to_csv(
    history_path,
    index=False,
    encoding="utf-8-sig"
)

(BASE / "metadata.json").write_text(
    json.dumps({
        "trading_day": day.isoformat(),
        "updated_at": now.isoformat(),
        "stocks": len(df),
        "institutional_available": inst_ok
    }, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("成功儲存", day, len(df), "筆股票資料")
