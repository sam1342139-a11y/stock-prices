"""FCN 每日燈號監控：讀取 latest.json 的收盤價，計算每檔商品離敲出／敲入的距離，寄 Email 通知。

商品條件放在 GitHub 密鑰 FCN_PRODUCTS（JSON 格式，不含客戶姓名），不會寫進任何檔案。
⚠️ 本存放庫是公開的，GitHub Actions 的執行紀錄任何人都看得到，
   所以程式只在紀錄裡印出「幾檔商品、幾個燈號」，不印商品內容。

本機測試（只印出信件內容、不寄信）：
    FCN_PRODUCTS="$(cat products.json)" python3 fcn-monitor/monitor.py --dry-run
"""
import datetime, json, os, smtplib, sys
from email.mime.text import MIMEText
from email.header import Header

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEAR_KI = 10.0  # 離敲入價不到 10% → 橘燈
NEAR_KO = 3.0   # 最弱標的離敲出價不到 3% → 藍燈提示即將敲出

LIGHTS = {
    "ki":   ("🔴", "已跌破敲入價"),
    "near": ("🟠", "接近敲入價"),
    "ko":   ("🔵", "全部標的已達敲出價"),
    "koso": ("🔷", "接近敲出"),
    "ok":   ("🟢", "正常"),
}
ORDER = ["ki", "near", "koso", "ko", "ok"]


def evaluate(prod, prices):
    legs, missing = [], []
    for leg in prod["legs"]:
        p = prices.get(leg["t"])
        if p is None:
            missing.append(leg["t"])
            continue
        legs.append({
            "t": leg["t"], "price": p, "ko": leg["ko"], "ki": leg["ki"],
            "to_ko": round((leg["ko"] / p - 1) * 100, 1),  # 還要漲幾 % 才到敲出價（負數代表已超過）
            "to_ki": round((p / leg["ki"] - 1) * 100, 1),  # 離敲入價還有幾 % 緩衝（負數代表已跌破）
        })
    if not legs:
        return {"code": prod["code"], "light": None, "legs": [], "missing": missing}
    worst_ki = min(l["to_ki"] for l in legs)
    worst_ko = max(l["to_ko"] for l in legs)  # 敲出通常要「所有標的」都達標，看最弱的那檔
    if worst_ki <= 0:
        light = "ki"
    elif worst_ki < NEAR_KI:
        light = "near"
    elif worst_ko <= 0 and not missing:
        light = "ko"
    elif worst_ko < NEAR_KO:
        light = "koso"
    else:
        light = "ok"
    return {"code": prod["code"], "light": light, "worst_ki": worst_ki, "worst_ko": worst_ko,
            "legs": sorted(legs, key=lambda l: l["to_ki"]), "missing": missing,
            "maturity": prod.get("maturity", "")}


def render(asof, results):
    counts = {k: sum(1 for r in results if r["light"] == k) for k in ORDER}
    summary = " ".join(f"{LIGHTS[k][0]}{counts[k]}" for k in ORDER if counts[k])
    subject = f"FCN 燈號 {asof}：{summary}"
    lines = [f"FCN 每日燈號（{asof} 美股收盤價）", "",
             "燈號說明：🔴 已跌破敲入價　🟠 離敲入價不到 %d%%　🔷 最弱標的離敲出價不到 %d%%　🔵 全部達敲出價　🟢 正常"
             % (NEAR_KI, NEAR_KO), ""]
    for r in sorted(results, key=lambda r: ORDER.index(r["light"]) if r["light"] else -1):
        if r["light"] is None:
            lines.append(f"⚪ {r['code']}：抓不到價格（{', '.join(r['missing'])}）")
            continue
        icon, label = LIGHTS[r["light"]]
        extra = f"，到期日 {r['maturity']}" if r.get("maturity") else ""
        lines.append(f"{icon} {r['code']}　{label}　最弱標的離敲入 {r['worst_ki']:+.1f}%，"
                     f"離敲出還差 {max(r['worst_ko'], 0):.1f}%{extra}")
        for l in r["legs"]:
            lines.append(f"    {l['t']:<5} 收盤 {l['price']:>9.2f}｜敲入 {l['ki']:>9.2f}（緩衝 {l['to_ki']:+.1f}%）"
                         f"｜敲出 {l['ko']:>9.2f}（還差 {l['to_ko']:+.1f}%）")
        if r["missing"]:
            lines.append(f"    ⚠️ 抓不到價格：{', '.join(r['missing'])}")
        lines.append("")
    lines += ["※ 以每日收盤價估算，實際是否敲出或敲入，以商品條件書的觀察日與規則為準。"]
    return subject, "\n".join(lines), counts


def send(subject, body):
    user = os.environ["GMAIL_USER"].strip()
    pw = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    to = [a.strip() for a in os.environ.get("MAIL_TO", user).split(",") if a.strip()]
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
    asof = latest.get("asof") or "?"
    prices = dict(latest.get("prices") or {})
    if not prices and latest.get("history"):  # 當天沒抓齊時，退回最近一個完整交易日
        asof = max(latest["history"])
        prices = latest["history"][asof]
    results = [evaluate(p, prices) for p in products]
    subject, body, counts = render(asof, results)
    print("商品 %d 檔，燈號統計：%s" % (len(products), {k: v for k, v in counts.items() if v}))
    if dry:
        print("=" * 40); print(subject); print(body)
        return
    send(subject, body)
    print("已寄出")


if __name__ == "__main__":
    main()
