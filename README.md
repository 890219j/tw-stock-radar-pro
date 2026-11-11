# 台股資金雷達 PRO — iPhone 雲端版

## 部署到 Streamlit Community Cloud

1. 登入 https://github.com 並建立新的 GitHub repository，例如 `tw-stock-radar-pro`。如果你不希望程式公開，可先選 Private，並確認目前 Streamlit Community Cloud 帳戶支援部署私人 repository。
2. 將本壓縮檔**內層的所有檔案**上傳到 repository 根目錄，包含 `.streamlit/config.toml`、`app.py`、`data.py`、`requirements.txt`。GitHub 網頁上傳時，隱藏的 `.streamlit` 資料夾可能需要透過「Create new file」建立 `.streamlit/config.toml`，並貼入本專案的內容。
3. 登入 https://share.streamlit.io ，點選 Create app / New app，選擇 GitHub repository、branch `main`、entrypoint `app.py`，然後 Deploy。
4. 等候安裝套件與啟動。若出現錯誤，開啟 Manage app → Logs 檢查。部署成功後，複製 `https://...streamlit.app` 網址到 iPhone Safari。
5. iPhone Safari 點「分享」→「加入主畫面」→「加入」。

## 重要限制
- 只有上市股票（TWSE）；不含上櫃 TPEx。
- 日資料和法人買賣超通常在收盤後更新；MIS 盤中報價為非授權即時串流、可能延遲或無法使用。
- 雲端使用系統暫存目錄 SQLite：**容器重新啟動可能遺失資料**，不是持久儲存。欲永久保存，需外接託管資料庫。
- 免費雲端可能休眠，沒有背景定時掃描與 iPhone 推播；必須開啟網頁才能看最新掃描。
- 「成交金額」不等於淨流入；法人數值為股數換算張數，並非實際現金金額。
- 公開資料介面可能變更或限制請求。遵守來源服務條款。
- 不需要券商帳號密碼，不提供自動下單。

## 本機執行
```
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
