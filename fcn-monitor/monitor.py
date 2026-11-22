"""FCN 每日燈號監控：讀取 latest.json 的收盤價，計算每檔商品離敲出／敲入的距離，寄 Email 通知。

燈號規則與「FCN 持股燈號追蹤」網頁一致：
- KO 每日觀察：所有標的現價都 ≥ KO → 🔵 提前出場
- KI 為歐式（EKI）：只在到期日比價；到期前跌破 KI 只是「預覽」
- 已到期商品不再監控；有換股（swap）的改追蹤換股標的現價 vs 換股價

商品條件放在 GitHub 密鑰 FCN_PRODUCTS（JSON，不含客戶姓名），不會寫進任何檔案。
⚠️ 本存放庫是公開的，GitHub Actions 的執行紀錄任何人都看得到，
   所以程式只在紀錄裡印出「幾檔商品、各燈號幾檔」，不印商品內容。

本機測試（只印出信件內容、不寄信）：
    FCN_PRODUCTS="$(cat products.json)" python3 fcn-monitor/monitor.py --dry-run
"""
import datetime, json, os, smtplib, sys
from email.mime.text import MIMEText
from email.header import Header

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEAR_KI = 10.0   # 最弱標的離 KI 不到 10% → 提醒
SOON_DAYS = 14   # 到期日 14 天內 → 提醒

LIGHTS = {
    "red":     ("🔴", "到期比價跌破 KI，恐需換股"),
    "preview": ("🟠", "目前低於 KI（預覽，到期才比價）"),
    "blue":    ("🔵", "全部標的達 KO，將提前出場"),
    "yellow":  ("🟡", "持有中"),
}
ORDER = ["red", "preview", "blue", "yellow"]


def days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def evaluate(prod, prices, asof):
    legs, missing = [], []
    for leg in prod["legs"]:
        p = prices.get(leg["t"])
        if p is None:
            missing.append(leg["t"])
            continue
        legs.append({
            "t": leg["t"], "price": p, "ko": leg["ko"], "ki": leg["ki"],
            "to_ko": round((leg["ko"] / p - 1) * 100, 1),  # 還要漲幾 % 才到 KO（負數代表已超過）
            "to_ki": round((p / leg["ki"] - 1) * 100, 1),  # 離 KI 還有幾 % 緩衝（負數代表已跌破）
        })
    r = {"code": prod["code"], "type": prod.get("type", "FCN"), "maturity": prod.get("maturity", ""),
         "legs": sorted(legs, key=lambda l: l["to_ki"]), "missing": missing, "light": None}
    if not legs:
        return r
    r["worst_ki"] = min(l["to_ki"] for l in legs)
    r["worst_ko"] = max(l["to_ko"] for l in legs)
    r["days_left"] = days_between(asof, r["maturity"]) if r["maturity"] else None
    if r["worst_ko"] <= 0 and not missing:
        r["light"] = "blue"
    elif r["worst_ki"] < 0:
        r["light"] = "red" if r["days_left"] is not None and r["days_left"] <= 0 else "preview"
    else:
        r["light"] = "yellow"
    return r


def evaluate_swap(prod, prices):
    """已到期且換股：追蹤換股標的現價 vs 換股價（k）。"""
    leg = next(l for l in prod["legs"] if l["t"] == prod["swap"])
    p = prices.get(leg["t"])
    out = {"code": prod["code"], "t": leg["t"], "strike": leg["k"], "price": p}
    if p is not None:
        out["pnl"] = round((p / leg["k"] - 1) * 100, 1)
    return out


def render(asof, results, swaps):
    counts = {k: sum(1 for r in results if r["light"] == k) for k in ORDER}
    summary = " ".join(f"{LIGHTS[k][0]}{counts[k]}" for k in ORDER if counts[k])
    if swaps:
        summary += f"｜換股 {len(swaps)} 檔"
    subject = f"FCN 燈號 {asof}：{summary}"
    L = [f"FCN 每日燈號（{asof} 美股收盤價）", "",
         "燈號：🔵 全部達 KO　🟠 低於 KI 預覽（KI 為歐式，到期日才比價）　🔴 到期比價跌破 KI　🟡 持有中", ""]

    soon = [r for r in results if r.get("days_left") is not None and 0 <= r["days_left"] <= SOON_DAYS]
    if soon:
        L.append(f"⏰ {SOON_DAYS} 天內到期：")
        for r in sorted(soon, key=lambda r: r["days_left"]):
            L.append(f"   {r['code']}　{r['maturity']}（剩 {r['days_left']} 天）{LIGHTS[r['light']][0]} 最弱標的離 KI {r['worst_ki']:+.1f}%")
        L.append("")

    for r in sorted(results, key=lambda r: (ORDER.index(r["light"]) if r["light"] else -1, r.get("worst_ki", 0))):
        if r["light"] is None:
            L.append(f"⚪ {r['code']}：抓不到價格（{', '.join(r['missing'])}）")
            continue
        icon, label = LIGHTS[r["light"]]
        tag = "" if r["type"] == "FCN" else f"［{r['type']}］"
        warn = "　⚠️ 接近 KI" if r["light"] == "yellow" and r["worst_ki"] < NEAR_KI else ""
        L.append(f"{icon} {r['code']}{tag}　{label}{warn}")
        L.append(f"    到期 {r['maturity'] or '未填'}"
                 + (f"（剩 {r['days_left']} 天）" if r.get("days_left") is not None else "")
                 + f"｜最弱標的離 KI {r['worst_ki']:+.1f}%｜離全部達 KO 還差 {max(r['worst_ko'], 0):.1f}%")
        for l in r["legs"]:
            mark = "✓KO" if l["to_ko"] <= 0 else ("✗KI" if l["to_ki"] < 0 else "")
            L.append(f"    {l['t']:<5} 收盤 {l['price']:>9.2f}｜KI {l['ki']:>9.2f}（{l['to_ki']:+.1f}%）"
                     f"｜KO {l['ko']:>9.2f}（還差 {l['to_ko']:+.1f}%） {mark}")
        if r["missing"]:
            L.append(f"    ⚠️ 抓不到價格：{', '.join(r['missing'])}")
        L.append("")

    if swaps:
        L.append("── 已換股部位（現價 vs 換股價）──")
        for s in sorted(swaps, key=lambda s: s.get("pnl", 0)):
            if s["price"] is None:
                L.append(f"⚪ {s['code']} {s['t']}：抓不到價格")
                continue
            icon = "📈" if s["pnl"] >= 0 else "📉"
            L.append(f"{icon} {s['code']}　{s['t']:<5} 收盤 {s['price']:>9.2f}｜換股價 {s['strike']:>9.2f}｜損益 {s['pnl']:+.1f}%"
                     + ("　✅ 已回到換股價以上" if s["pnl"] >= 0 else ""))
        L.append("")

    L.append("※ 以每日收盤價估算，未計入 KO 記憶（曾觸價）；實際以商品條件書與「FCN 持股燈號追蹤」網頁為準。")
    return subject, "\n".join(L), counts


def send(subject, body):
    user = os.environ["GMAIL_USER"].strip()
    pw = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    to = [a.strip() for a in (os.environ.get("MAIL_TO") or user).split(",") if a.strip()]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = ", ".join(to)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.sendmail(user, to, msg.as_string())


def main():
    dry = "--dry-run" in sys.argv
    raw = os.environ.get("FCN_PRODUCTS", "").strip()
    if not raw:
        print("沒有設定 FCN_PRODUCTS，略過")
        return
    products = json.loads(raw)
    with open(os.path.join(ROOT, "latest.json"), encoding="utf-8") as f:
        latest = json.load(f)
    asof = latest.get("asof")
    prices = dict(latest.get("prices") or {})
    if not prices and latest.get("history"):  # 當天沒抓齊時，退回最近一個完整交易日
        asof = max(latest["history"])
        prices = latest["history"][asof]

    active = [p for p in products if not p.get("maturity") or p["maturity"] >= asof]
    swapped = [p for p in products if p not in active and p.get("swap")]
    results = [evaluate(p, prices, asof) for p in active]
    swaps = [evaluate_swap(p, prices) for p in swapped]
    subject, body, counts = render(asof, results, swaps)
    print("監控中 %d 檔、已到期略過 %d 檔、換股追蹤 %d 檔，燈號統計：%s"
          % (len(active), len(products) - len(active) - len(swapped), len(swapped),
             {k: v for k, v in counts.items() if v}))
    if dry:
        print("=" * 40); print(subject); print(body)
        return
    send(subject, body)
    print("已寄出")


if __name__ == "__main__":
    main()
