"""Email alerts sent straight from GitHub Actions (no AI). Credentials come only from GitHub Secrets.

  python3 lib/notify.py failure "<workflow name>" "<run url>"
  python3 lib/notify.py watch "<since ISO UTC>"     # compare files committed after <since> with their previous version

watch sends one mail only when something changed:
  - Taiwan regime overall_light changed (tw-models/latest/regime_tw.json)
  - long list members changed (tw-models/latest/long.json)
  - US market regime level worse (regime/regime.json)
  - a data check failed (problems[0] starts with 資料檢查未通過) in a newly committed file
  - fcn/prices_checked.json status turned to fail
Env: GMAIL_USER, GMAIL_APP_PASSWORD, optional MAIL_TO. Without them it only prints (dry run).
"""
import json, os, smtplib, subprocess, sys
from email.header import Header
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEVEL = {"綠": 0, "黃": 1, "紅": 2}
CHECK_FILES = ["tw-models/latest/regime_tw.json", "tw-models/latest/swing.json", "tw-models/latest/long.json",
               "tw-models/latest/core_satellite.json", "tw-models/latest/after_market.json", "tw-models/paper/latest.json",
               "regime/regime.json", "macro/macro.json", "fx/position.json", "fcn/prices_checked.json"]
FOOTER = "\n\n—\n此信由 GitHub Actions 自動寄出（stock-prices），只在有變化或出錯時寄。模型依公開資料與固定規則產生，非投資建議。"


def git(*a):
    return subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True, text=True, env=dict(os.environ, TZ="UTC")).stdout.strip()


def versions(path, since):
    """(previous, current) JSON of path if its latest commit is after `since`; else None."""
    log = git("log", "-n", "2", "--date=iso-strict-local", "--format=%H %cd", "--", path).splitlines()
    if len(log) < 2:
        return None
    (h1, t1), (h0, _) = log[0].split(), log[1].split()
    if t1[:19] < since[:19]:
        return None
    try:
        return json.loads(git("show", "%s:%s" % (h0, path))), json.loads(git("show", "%s:%s" % (h1, path)))
    except ValueError:
        return None


def send(subject, body):
    user, pw = os.environ.get("GMAIL_USER", "").strip(), os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    print("MAIL:", subject, "\n" + body)
    if not user or not pw:
        print("(no mail credentials: dry run)")
        return
    to = [a.strip() for a in (os.environ.get("MAIL_TO") or user).split(",") if a.strip()]
    msg = MIMEText(body + FOOTER, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = Header(subject, "utf-8"), user, ", ".join(to)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.sendmail(user, to, msg.as_string())


def first_problem(d):
    p = (d or {}).get("problems") or []
    return str(p[0]) if p else ""


def watch(since):
    lines = []
    v = versions("tw-models/latest/regime_tw.json", since)
    if v and v[0].get("overall_light") != v[1].get("overall_light"):
        lines.append("台股水位燈號：%s → %s（總分 %s，資料日 %s）" % (v[0].get("overall_light"), v[1].get("overall_light"), v[1].get("total"), v[1].get("date")))
    v = versions("tw-models/latest/long.json", since)
    if v:
        a = {x["code"]: x["name"] for x in v[0].get("list", [])}
        b = {x["code"]: x["name"] for x in v[1].get("list", [])}
        if set(a) != set(b):
            out = ["%s %s" % (c, a[c]) for c in sorted(set(a) - set(b))]
            inn = ["%s %s" % (c, b[c]) for c in sorted(set(b) - set(a))]
            lines.append("長期名單換股（訊號日 %s）：換入 %s；換出 %s" % (v[1].get("signal_date"), "、".join(inn) or "無", "、".join(out) or "無"))
    v = versions("regime/regime.json", since)
    if v and LEVEL.get(v[1].get("level"), -1) > LEVEL.get(v[0].get("level"), 9):
        lines.append("美股市場風險燈號變差：%s → %s（總分 %s，%s）" % (v[0].get("level"), v[1].get("level"), v[1].get("total"), v[1].get("date_tw")))
    for f in CHECK_FILES:
        v = versions(f, since)
        if not v:
            continue
        p1, p0 = first_problem(v[1]), first_problem(v[0])
        if p1.startswith("資料檢查未通過") and p1 != p0:
            lines.append("%s：%s" % (f, p1))
        if f == "fcn/prices_checked.json" and v[1].get("status") == "fail" and v[0].get("status") != "fail":
            lines.append("美股收盤價檢查未通過（%s）：%s" % (v[1].get("asof"), "；".join(v[1].get("fail_reasons", []))))
        if f == "fcn/prices_checked.json" and v[1].get("mismatch") and v[1].get("mismatch") != v[0].get("mismatch"):
            for m in v[1]["mismatch"]:
                ss = m.get("second_source") or {}
                lines.append("美股收盤價對不上：%s %s 舊 %s → 新 %s（%+.2f%%）%s%s" % (
                    m["ticker"], m["date"], m["old"], m["new"], m["diff_pct"],
                    "，疑似拆合股 %s" % m["integer_multiple"] if m.get("integer_multiple") else "",
                    "，Nasdaq %s（吻合%s）" % (ss.get("value"), ss.get("matches")) if ss.get("value") else ""))
        if f == "fcn/prices_checked.json":
            new_splits = {x["ticker"] for x in v[1].get("splits") or []} - {x["ticker"] for x in v[0].get("splits") or []}
            for x in v[1].get("splits") or []:
                if x["ticker"] in new_splits:
                    lines.append("偵測到拆合股：%s %s，生效日 %s" % (x["ticker"], x["ratio"], x["effective_date"]))
    if lines:
        send("【stock-prices】" + lines[0][:40], "\n".join("・" + x for x in lines))
    else:
        print("nothing to report")


if __name__ == "__main__":
    if sys.argv[1] == "failure":
        send("【stock-prices】排程失敗：%s" % sys.argv[2],
             "GitHub Actions 排程「%s」執行失敗。\n記錄：%s\n\n資料會維持前一次的版本；請找 Claude 查原因。" % (sys.argv[2], sys.argv[3]))
    elif sys.argv[1] == "watch":
        watch(sys.argv[2])
