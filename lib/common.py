"""各資料程式共用的小工具。只用 Python 內建功能。

- 每個輸出 JSON 都會有 generated_at_utc、problems、sources
- API 金鑰只從環境變數讀（GitHub Actions 由 Secrets 帶入）
- --dry-run：輸出改寫到 .dryrun/ 資料夾（不進版控），不動正式檔案
"""
import ast, csv, datetime, io, json, os, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (compatible; stock-prices-bot; +https://github.com/sam1342139-a11y/stock-prices)"
TW = datetime.timezone(datetime.timedelta(hours=8))


def is_dry_run():
    return "--dry-run" in sys.argv


def out_path(rel):
    """正式執行寫到 repo 內；--dry-run 寫到 .dryrun/ 底下同樣路徑。"""
    base = os.path.join(ROOT, ".dryrun") if is_dry_run() else ROOT
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def read_path(rel):
    """讀取既有檔案：dry-run 時優先讀 .dryrun/ 的版本，沒有再讀正式檔。"""
    if is_dry_run():
        p = os.path.join(ROOT, ".dryrun", rel)
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, rel)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def tw_today():
    return utc_now().astimezone(TW).date()


def http_get(url, headers=None, retries=3, timeout=60):
    h = {"User-Agent": UA}
    h.update(headers or {})
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8-sig")
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:  # 權限、方案、網址錯誤：重試也沒用，直接回報
                body = e.read().decode("utf-8", "replace")[:300]
                raise RuntimeError("HTTP %d：%s" % (e.code, body)) from None
            last = e
            time.sleep(3 * (i + 1))
        except Exception as e:  # 網路偶發錯誤：稍等再試
            last = e
            time.sleep(3 * (i + 1))
    raise last


def http_json(url, headers=None):
    return json.loads(http_get(url, headers))


def twelvedata(endpoint, **params):
    """呼叫 Twelve Data。金鑰只從 TWELVEDATA_KEY 環境變數讀，用標頭送出。"""
    key = os.environ.get("TWELVEDATA_KEY", "").strip()
    if not key:
        raise RuntimeError("沒有設定 TWELVEDATA_KEY")
    url = "https://api.twelvedata.com/%s?%s" % (endpoint, urllib.parse.urlencode(params))
    for attempt in range(3):
        try:
            data = http_json(url, {"Authorization": "apikey " + key})
        except RuntimeError as e:  # HTTP 4xx：把 Twelve Data 的 JSON 錯誤訊息取出來
            msg = str(e)
            try:
                j = json.loads(msg.split("：", 1)[1])
                m = j.get("message") or ""
                if "available exclusively with" in m:
                    msg = "Twelve Data 目前方案不支援這個功能（需要升級到 Grow 以上方案）"
                elif j.get("code") == 401:
                    msg = "Twelve Data 金鑰錯誤或沒有提供（請檢查 GitHub 密鑰 TWELVEDATA_KEY）"
                elif j.get("code") == 404:
                    msg = "Twelve Data 找不到這個代號或資料"
                else:
                    msg = "Twelve Data 錯誤 %s：%s" % (j.get("code"), m)
            except (IndexError, ValueError):
                pass
            raise RuntimeError(msg) from None
        if isinstance(data, dict) and data.get("code") == 429:  # 每分鐘額度用完，等一分鐘
            time.sleep(65)
            continue
        if isinstance(data, dict) and data.get("status") == "error":
            raise RuntimeError("Twelve Data %s: %s" % (data.get("code"), data.get("message")))
        return data
    raise RuntimeError("Twelve Data 額度用完（429），重試 3 次仍失敗")


def fred(series_id, start):
    """FRED 公開 CSV（免金鑰）。回傳 [(YYYY-MM-DD, float), ...]，略過無資料的日期。"""
    q = urllib.parse.urlencode({"id": series_id, "cosd": start})
    rows = []
    for row in csv.reader(io.StringIO(http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?" + q))):
        if len(row) != 2 or row[0] in ("DATE", "observation_date"):
            continue
        try:
            rows.append((row[0], float(row[1])))
        except ValueError:
            continue
    return rows


def us_symbols():
    """從 fetch_prices.py 讀出 26 檔美股清單（不寫死在這裡）。"""
    src = open(os.path.join(ROOT, "fetch_prices.py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SYMBOLS" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise RuntimeError("fetch_prices.py 裡找不到 SYMBOLS")


def write_json(rel, payload, problems, sources):
    """寫出 JSON：固定把 generated_at_utc、problems、sources 放最前面。"""
    data = {
        "generated_at_utc": utc_now().strftime("%Y-%m-%d %H:%M:%S"),
        "problems": problems,
        "sources": sources,
    }
    data.update(payload)
    path = out_path(rel)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def read_json(rel, default=None):
    try:
        with open(read_path(rel), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_csv(rel, header, rows):
    path = out_path(rel)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return path


def read_csv(rel):
    try:
        with open(read_path(rel), encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []
