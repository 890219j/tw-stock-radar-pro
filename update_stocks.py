from pathlib import Path
import os
import time
import yfinance as yf
from ai_model import load_stock

folder = Path("ai_data")
folder.mkdir(exist_ok=True)

stocks = [
    "2330", "2317", "2454", "2308",
    "2382", "3231", "3711", "2303",
    "2881", "2882"
]

failed = []

for code in stocks:
    path = folder / f"{code}.csv"
    temp = folder / f"{code}.tmp.csv"

    try:
        old_date = None
        if path.exists():
            old = load_stock(path)
            if not old.empty:
                old_date = old.index.max()

        data = yf.download(
            f"{code}.TW",
            period="5y",
            interval="1d",
            auto_adjust=True,
            multi_level_index=True,
            progress=False,
            threads=False,
            timeout=20,
        )

        if data is None or data.empty:
            raise ValueError("未取得行情")

        data.to_csv(temp)
        checked = load_stock(temp)

        if len(checked) < 300:
            raise ValueError("歷史資料筆數異常")

        new_date = checked.index.max()

        if old_date is not None and new_date < old_date:
            raise ValueError("新資料比原資料舊")

        os.replace(temp, path)
        print(f"✅ {code}: {new_date.date()}")

    except Exception as e:
        failed.append(code)
        print(f"❌ {code}: {e}")

    finally:
        temp.unlink(missing_ok=True)

    time.sleep(1)

print("更新結束")
print("失敗股票：", failed)

if failed:
    raise SystemExit(1)
