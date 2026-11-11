import datetime as dt
import os
import tempfile
import sqlite3
import time
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from data import listed_daily,institutional,mis_quotes,recent_trading_days

st.set_page_config(page_title='台股資金雷達 PRO',page_icon='📡',layout='wide')
DB=Path(os.environ.get('RADAR_DB_PATH', str(Path(tempfile.gettempdir()) / 'stock_radar_pro.db')))

def connect():
    c=sqlite3.connect(DB,timeout=10)
    c.execute('CREATE TABLE IF NOT EXISTS daily (day TEXT, code TEXT, turnover REAL, close REAL, volume REAL, PRIMARY KEY(day,code))')
    return c

def save_history(day,df):
    with connect() as c:
        c.executemany('INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?)',[(day.isoformat(),str(r.code),float(r.turnover),float(r.close) if pd.notna(r.close) else None,float(r.volume)) for r in df.itertuples()])

def historical():
    with connect() as c: return pd.read_sql_query('SELECT * FROM daily',c)

@st.cache_data(ttl=600,show_spinner=False)
def load_latest():
    errors=[]
    for day in recent_trading_days(9):
        try:
            d=listed_daily(day)
            if len(d)>100: return day,d
        except Exception as e: errors.append(f'{day}: {e}')
    raise RuntimeError('近 9 日無法取得上市資料。請稍後重試。最近錯誤：'+'; '.join(errors[:2]))

st.title('📡 台股資金雷達 PRO')
st.caption('上市股票｜交易所公開資料｜法人淨買賣超｜產業自訂分類｜盤中報價（盡力取得）｜本機警報')
with st.sidebar:
    st.header('控制中心')
    if st.button('🔄 重新取得資料',use_container_width=True):
        st.cache_data.clear(); st.rerun()
    enable_live=st.toggle('查詢盤中報價',value=False,help='MIS 非保證即時來源，部分時段可能沒有成交價')
    live_count=st.slider('盤中報價查詢檔數',10,100,40,10,disabled=not enable_live)
    threshold=st.slider('異常成交金額倍數門檻',1.2,5.0,1.8,0.1)
    st.caption('每次按重新取得資料才會強制更新；盤中報價快取約 35 秒。')
try:
    day,df=load_latest()
except Exception as e:
    st.error(str(e)); st.stop()
try:
    inst=institutional(day)
    df=df.merge(inst,on='code',how='left')
    inst_ok=True
except Exception as e:
    inst_ok=False
    st.warning(f'法人資料暫時不可用：{e}。不會將缺失值當成零。')
    for c in ['foreign','trust','dealer']: df[c]=np.nan

df['inst_net']=df[['foreign','trust','dealer']].sum(axis=1,min_count=3)
df['turnover_100m']=df.turnover/1e8
for c in ['foreign','trust','dealer','inst_net']: df[c+'_lots']=df[c]/1000
save_history(day,df)
hist=historical()
previous=hist[hist.day<day.isoformat()]
if len(previous):
    base=previous.sort_values('day').groupby('code').tail(5).groupby('code').turnover.agg(['mean','count']).reset_index()
    base.columns=['code','turnover_avg','history_days']
    df=df.merge(base,on='code',how='left')
    df['turnover_ratio']=df.turnover/df.turnover_avg.replace(0,np.nan)
else:
    df['turnover_ratio']=np.nan;df['history_days']=0

st.info(f'資料交易日：{day.isoformat()}｜成交額與法人：日資料（非盤中即時）｜目前已累積 {hist.day.nunique()} 個交易日的本機歷史。')
if hist.day.nunique()<4:
    st.caption('⚠️ 異常量能需累積至少 3 個過去交易日才有參考價值；首次執行不會憑空產生歷史資料。')

search=st.text_input('🔎 股票代號或名稱',placeholder='例如 2330、台積電')
filtered=df[df.code.str.contains(search,regex=False)|df.name.astype(str).str.contains(search,regex=False)] if search else df

m1,m2,m3,m4=st.columns(4)
m1.metric('上市股票成交總額',f'{df.turnover.sum()/1e8:,.0f} 億')
m2.metric('法人合計淨買賣超',f'{df.inst_net.sum()/1000:+,.0f} 張' if inst_ok else '資料未公布')
m3.metric('上漲 / 下跌',f'{int((df.pct>0).sum())} / {int((df.pct<0).sum())}')
m4.metric('當日股票數',f'{len(df):,}')

tabs=st.tabs(['🔥 資金排行','🏦 法人追蹤','🗺️ 資金熱力圖','⚡ 盤中報價','🚨 警報與觀察名單','📚 歷史資料'])
with tabs[0]:
    top=filtered.sort_values('turnover',ascending=False).head(30)
    st.plotly_chart(px.bar(top.head(20).sort_values('turnover_100m'),x='turnover_100m',y='name',orientation='h',hover_data=['code','pct'],labels={'turnover_100m':'成交金額（億元）','name':'股票'}),use_container_width=True)
    st.dataframe(top[['code','name','close','pct','turnover_100m','volume','turnover_ratio']].rename(columns={'code':'代號','name':'名稱','close':'收盤','pct':'漲跌幅%','turnover_100m':'成交額(億)','volume':'成交股數','turnover_ratio':'成交額/歷史均值'}),hide_index=True,use_container_width=True)
with tabs[1]:
    if inst_ok:
        kind=st.selectbox('排序依據',['inst_net_lots','foreign_lots','trust_lots','dealer_lots'],format_func=lambda x:{'inst_net_lots':'三大法人合計','foreign_lots':'外資','trust_lots':'投信','dealer_lots':'自營商'}[x])
        buy,sell=st.columns(2)
        cols=['code','name','foreign_lots','trust_lots','dealer_lots','inst_net_lots']
        with buy:
            st.subheader('買超前 20')
            st.dataframe(filtered.nlargest(20,kind)[cols],hide_index=True,use_container_width=True)
        with sell:
            st.subheader('賣超前 20')
            st.dataframe(filtered.nsmallest(20,kind)[cols],hide_index=True,use_container_width=True)
        st.caption('法人數值單位：張（1 張 = 1,000 股）；不同股票價格不同，張數不可直接視為金額。')
    else: st.warning('法人資料未公布，請稍後重新整理。')
with tabs[2]:
    st.caption('依股票成交金額大小顯示方塊，顏色表示漲跌幅；不是資金淨流入圖。')
    heat=filtered.nlargest(80,'turnover').dropna(subset=['pct','turnover'])
    if len(heat):
        fig=px.treemap(heat,path=[px.Constant('台股上市'), 'name'],values='turnover',color='pct',color_continuous_scale='RdYlGn',color_continuous_midpoint=0,hover_data=['code','turnover_100m'])
        fig.update_layout(height=650,margin=dict(t=10,l=10,r=10,b=10))
        st.plotly_chart(fig,use_container_width=True)
    st.subheader('自訂產業分類')
    st.caption('可上傳 CSV，欄位為 code,sector。未提供時僅按個股呈現，不會捏造產業分類。')
    up=st.file_uploader('上傳產業分類 CSV',type='csv')
    if up:
        try:
            sectors=pd.read_csv(up,dtype={'code':str})
            if not {'code','sector'}.issubset(sectors.columns): raise ValueError('CSV 需要 code,sector 欄位')
            merged=df.merge(sectors[['code','sector']].drop_duplicates('code'),on='code',how='left')
            sec=merged.dropna(subset=['sector']).groupby('sector',as_index=False).agg(turnover=('turnover','sum'),count=('code','count'))
            sec['億元']=sec.turnover/1e8
            st.plotly_chart(px.bar(sec.sort_values('億元',ascending=False),x='sector',y='億元',hover_data=['count']),use_container_width=True)
        except Exception as e: st.error(f'分類檔無法讀取：{e}')
with tabs[3]:
    st.warning('MIS 報價為公開網站介面，非交易所授權行情串流；可能延遲、空值或被限制。不能用於自動下單或高頻交易。')
    if enable_live:
        codes=filtered.nlargest(live_count,'turnover').code.tolist()
        try:
            q=mis_quotes(tuple(codes))
            if len(q):
                out=q.merge(df[['code','name','close']],on='code',how='left')
                st.dataframe(out.rename(columns={'code':'代號','name':'名稱','last':'最近成交價','bid':'最佳買價','ask':'最佳賣價','quote_time':'報價時間','quote_date':'報價日期','close':'日資料收盤價'}),hide_index=True,use_container_width=True)
                st.caption('報價日期與時間以來源回傳為準；收盤價欄位屬日資料，不能混同即時成交價。')
            else: st.info('目前沒有可用報價。')
        except Exception as e: st.error(f'盤中報價查詢失敗：{e}')
    else: st.info('請在左側開啟「查詢盤中報價」。')
with tabs[4]:
    st.subheader('異常量能 + 上漲 + 法人買超')
    valid=df[(df.history_days>=3)&(df.turnover_ratio>=threshold)&(df.pct>0)]
    if inst_ok: valid=valid[valid.inst_net>0]
    st.dataframe(valid.sort_values('turnover_ratio',ascending=False)[['code','name','pct','turnover_100m','turnover_ratio','inst_net_lots']],hide_index=True,use_container_width=True)
    st.caption('警報為本頁資料掃描結果，不會在網頁關閉後推播。欲持續監控需部署排程及通知服務。')
    watch=st.text_input('自訂觀察清單（代號以逗號分隔）','2330,2317,2454')
    codes=[x.strip() for x in watch.split(',') if x.strip()]
    st.dataframe(df[df.code.isin(codes)][['code','name','close','pct','turnover_100m','inst_net_lots']],hide_index=True,use_container_width=True)
with tabs[5]:
    st.dataframe(hist.sort_values(['day','turnover'],ascending=[False,False]).head(500),hide_index=True,use_container_width=True)
    st.download_button('下載已累積歷史 CSV',hist.to_csv(index=False).encode('utf-8-sig'),'radar_history.csv','text/csv')
    st.download_button('下載當日完整 CSV',df.to_csv(index=False).encode('utf-8-sig'),f'radar_{day}.csv','text/csv')
st.divider()
st.caption('本系統為研究與觀察工具，不構成投資建議。成交金額與漲跌幅只能反映交易活動，不能證明特定主力買進；法人買賣超是股數淨額，不能直接解讀為現金流入。')
