"""Official TWSE daily public data and optional TWSE MIS quotes. No paid key required."""
import datetime as dt
import requests
import pandas as pd
import streamlit as st

S = requests.Session()
S.headers.update({'User-Agent':'Mozilla/5.0 (compatible; StockRadar/1.0)', 'Accept':'application/json', 'Referer':'https://www.twse.com.tw/'})

def number(v):
    try:
        s=str(v).replace(',','').replace('+','').replace('%','').strip()
        if s in ('','--','---','X','nan','None'): return float('nan')
        return float(s)
    except (ValueError, TypeError): return float('nan')

def get_json(url, params=None):
    r=S.get(url,params=params,timeout=18)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=900, show_spinner=False)
def listed_daily(day):
    j=get_json('https://www.twse.com.tw/exchangeReport/MI_INDEX',{'response':'json','date':day.strftime('%Y%m%d'),'type':'ALLBUT0999'})
    # Prefer the all-securities table by matching column headers, rather than relying on table index.
    fields=None; rows=None
    for k,v in j.items():
        if k.startswith('fields') and isinstance(v,list) and '證券代號' in v and '成交金額' in v:
            suffix=k[6:]; candidate=j.get('data'+suffix)
            if isinstance(candidate,list): fields=v; rows=candidate; break
    if fields is None: raise ValueError('當日尚無完整上市行情，或交易所暫時無法提供資料')
    df=pd.DataFrame(rows,columns=fields)
    rename={'證券代號':'code','證券名稱':'name','成交股數':'volume','成交金額':'turnover','收盤價':'close','漲跌價差':'change','開盤價':'open','最高價':'high','最低價':'low'}
    df=df.rename(columns=rename)
    for c in ['volume','turnover','close','change','open','high','low']:
        if c in df: df[c]=df[c].map(number)
    df=df[df.code.astype(str).str.fullmatch(r'\d{4}')].copy()
    sign_col=next((c for c in df.columns if '漲跌(+/-)' in c or '漲跌(+／-)' in c),None)
    if sign_col:
        df['change']=df['change'].abs()*df[sign_col].astype(str).map(lambda s:-1 if '-' in s or '－' in s else 1)
    df['change']=df['change'].fillna(0)
    df['prev_close']=df['close']-df['change']
    df['pct']=df['change']/df['prev_close'].where(df['prev_close']>0)*100
    df['market']='上市'
    return df

@st.cache_data(ttl=900, show_spinner=False)
def institutional(day):
    j=get_json('https://www.twse.com.tw/fund/T86',{'response':'json','date':day.strftime('%Y%m%d'),'selectType':'ALLBUT0999'})
    if not j.get('data') or not j.get('fields'): raise ValueError('三大法人資料尚未公布')
    df=pd.DataFrame(j['data'],columns=j['fields'])
    code=next((x for x in df if '證券代號' in x),None)
    if code is None: raise ValueError('法人資料格式已更改')
    df=df.rename(columns={code:'code'}); df['code']=df.code.astype(str).str.strip()
    aliases={'foreign':['外陸資買賣超股數(不含外資自營商)','外資及陸資買賣超股數(不含外資自營商)'],
             'trust':['投信買賣超股數'], 'dealer':['自營商買賣超股數']}
    for target,patterns in aliases.items():
        found=next((c for p in patterns for c in df if p in c),None)
        df[target]=df[found].map(number) if found else 0.0
    return df[['code','foreign','trust','dealer']].drop_duplicates('code')

@st.cache_data(ttl=35,show_spinner=False)
def mis_quotes(codes):
    if not codes: return pd.DataFrame()
    # TWSE MIS is an unofficial/unstable public-facing interface; no guaranteed real-time SLA.
    result=[]
    for start in range(0,len(codes),40):
        chunk=codes[start:start+40]
        j=get_json('https://mis.twse.com.tw/stock/api/getStockInfo.jsp',{'ex_ch':'|'.join('tse_'+c+'.tw' for c in chunk),'json':'1','delay':'0'})
        for x in j.get('msgArray',[]):
            price=number(x.get('z'))
            if pd.isna(price): price=number(x.get('y'))
            result.append({'code':x.get('c'),'last':price,'bid':number((x.get('b') or '').split('_')[0]),'ask':number((x.get('a') or '').split('_')[0]),'quote_time':x.get('t',''),'quote_date':x.get('d','')})
    return pd.DataFrame(result)

def recent_trading_days(n=7):
    today=dt.date.today()
    return [today-dt.timedelta(days=i) for i in range(n)]
