import os,json,time,urllib.request,urllib.parse
KEY=os.environ["TWELVEDATA_KEY"]
SYMS=["AMAT", "ARM", "ASML", "AVGO", "GOOG", "INTC", "KLAC", "MU", "NVDA", "SOXX", "SPY", "TSLA", "TSM"]
PRODS=json.loads('[["方鼎鈺", "00952281", "2026-07-06", "TSM", 418.45, 251.07], ["方鼎鈺", "00952281", "2026-07-06", "AVGO", 446.77, 268.06], ["方鼎鈺", "00952281", "2026-07-06", "GOOG", 376.43, 225.85], ["張清慶", "00952281", "2026-07-06", "TSM", 418.45, 251.07], ["張清慶", "00952281", "2026-07-06", "AVGO", 446.77, 268.06], ["張清慶", "00952281", "2026-07-06", "GOOG", 376.43, 225.85], ["蔡麗娟", "00952379", "2026-08-20", "TSM", 436.96, 240.32], ["蔡麗娟", "00952379", "2026-08-20", "MU", 991.64, 545.4], ["蔡麗娟", "00952379", "2026-08-20", "TSLA", 406.55, 223.6], ["蔡麗娟", "00952379", "2026-08-20", "ARM", 327.87, 180.32], ["蔡麗娟", "0095H031", "2026-07-30", "AMAT", 585.88, 380.82], ["蔡麗娟", "0095H031", "2026-07-30", "ASML", 1778.46, 1155.99], ["蔡麗娟", "0095H031", "2026-07-30", "KLAC", 244.49, 158.91], ["吳天民", "0095G968", "2026-07-22", "INTC", 127.86, 70.32], ["吳天民", "0095G968", "2026-07-22", "NVDA", 212.45, 116.84], ["吳天民", "0095G968", "2026-07-22", "TSM", 441.4, 242.77], ["王瀞儀", "0095G533", "2026-06-22", "INTC", 120.61, 66.3355], ["王瀞儀", "0095G533", "2026-06-22", "NVDA", 220.78, 121.429], ["王瀞儀", "0095G533", "2026-06-22", "TSLA", 433.45, 238.3975], ["王瀞儀", "0095H031", "2026-07-30", "AMAT", 585.88, 380.82], ["王瀞儀", "0095H031", "2026-07-30", "ASML", 1778.46, 1155.99], ["王瀞儀", "0095H031", "2026-07-30", "KLAC", 244.49, 158.91], ["柯金連", "0095H041", "2026-07-31", "SOXX", 603.39, 362.03], ["柯金連", "0095H041", "2026-07-31", "SPY", 733.58, 440.14], ["柯金連", "0095H041", "2026-07-31", "TSM", 436.39, 261.83]]')
START="2026-06-22";END="2026-10-05"
series={}
def get(batch):
    q=urllib.parse.urlencode(dict(symbol=",".join(batch),interval="1day",start_date=START,end_date=END,outputsize=5000,apikey=KEY))
    for _ in range(3):
        r=json.load(urllib.request.urlopen("https://api.twelvedata.com/time_series?"+q))
        if isinstance(r,dict) and r.get("code")==429: time.sleep(65); continue
        return r
    return {}
groups=[SYMS[i:i+7] for i in range(0,len(SYMS),7)]
for gi,g in enumerate(groups):
    if gi: time.sleep(65)
    r=get(g)
    if len(g)==1: r={g[0]:r}
    for s in g:
        v=r.get(s,{})
        series[s]={x["datetime"]:float(x["close"]) for x in v.get("values",[])}
        print(s,len(series[s]),v.get("status"),v.get("message"))
out={"series":series,"summary":[]}
for c,code_,ks,t,ko,ki in PRODS:
    xs=[(dt,p) for dt,p in series.get(t,{}).items() if dt>=ks]
    mx=max(xs,key=lambda z:z[1]) if xs else None
    mn=min(xs,key=lambda z:z[1]) if xs else None
    out["summary"].append(dict(client=c,code=code_,ticker=t,from_=ks,n=len(xs),max=mx,min=mn,ko=ko,ki=ki,ko_hit=bool(mx and mx[1]>=ko),below_ki=bool(mn and mn[1]<ki)))
json.dump(out,open("backfill.json","w"),ensure_ascii=False,indent=1)
