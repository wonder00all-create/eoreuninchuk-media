"""GitHub Actions 에서 돌아가는 예약 게시기.

schedule/queue.json 에서 시간이 된 '대기' 항목을 인스타그램 공식 API로 올리고 결과를 기록한다.
미디어는 미리 GitHub Pages 공개 주소에 올라가 있어야 한다(예약.py 가 해 줌).
환경변수: IG_TOKEN (GitHub Secrets). 표준 라이브러리만 쓴다.
"""
import os, sys, json, time, datetime, urllib.request, urllib.parse, urllib.error

VER = "v23.0"
FB = "https://graph.facebook.com"
KST = datetime.timezone(datetime.timedelta(hours=9))
QUEUE = "schedule/queue.json"
CONF = json.load(open("config.json", encoding="utf-8"))
IG_ID = CONF["ig_user_id"]
TOKEN = os.environ.get("IG_TOKEN", "").strip()
MAX_PER_RUN = 2

def log(*a):
    print(datetime.datetime.now(KST).strftime("%H:%M:%S"), *a, flush=True)

def ig(path, params=None, method="POST"):
    params = dict(params or {}, access_token=TOKEN)
    url = f"{FB}/{VER}/{path}"
    data = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method), timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:300]
        raise RuntimeError(f"{path}: {msg}")

def wait(cid, limit=900):
    t0 = time.time()
    while time.time() - t0 < limit:
        code = ig(cid, {"fields": "status_code"}, "GET").get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"컨테이너 {cid} 상태 {code}")
        time.sleep(10)
    raise RuntimeError(f"컨테이너 {cid} 처리 시간 초과")

def already_posted(caption):
    """최근 게시물에 같은 캡션이 있으면 True (기록 실패로 인한 중복 게시 방지)"""
    r = ig(f"{IG_ID}/media", {"fields": "caption,permalink,timestamp", "limit": 10}, "GET")
    for m in r.get("data", []):
        if (m.get("caption") or "").strip() == caption.strip():
            return m.get("permalink")
    return None

def publish(e):
    cap = e["caption"]
    if e["kind"] == "carousel":
        kids = [ig(f"{IG_ID}/media", {"image_url": u, "is_carousel_item": "true"})["id"] for u in e["media"]]
        for k in kids:
            wait(k)
        cid = ig(f"{IG_ID}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": cap})["id"]
    elif e["kind"] == "reel":
        cid = ig(f"{IG_ID}/media", {"media_type": "REELS", "video_url": e["media"][0],
                                    "caption": cap, "share_to_feed": "true"})["id"]
    else:
        raise RuntimeError("알 수 없는 종류: " + e["kind"])
    wait(cid)
    mid = ig(f"{IG_ID}/media_publish", {"creation_id": cid})["id"]
    return ig(mid, {"fields": "permalink"}, "GET").get("permalink")

def main():
    if not TOKEN:
        sys.exit("IG_TOKEN 이 없어요 (GitHub Secrets 확인).")
    me = ig(IG_ID, {"fields": "username"}, "GET")
    log("계정:", me.get("username"))
    queue = json.load(open(QUEUE, encoding="utf-8"))
    now = datetime.datetime.now(KST)
    due = [e for e in queue if e.get("status") == "대기"
           and datetime.datetime.fromisoformat(e["when"]) <= now]
    log(f"예약 {len(queue)}건 중 지금 올릴 것 {len(due)}건")
    for e in due[:MAX_PER_RUN]:
        log("올리는 중:", e["id"], e["kind"])
        try:
            link = already_posted(e["caption"])
            if link:
                log("이미 올라가 있어서 기록만 함:", link)
            else:
                link = publish(e)
                log("게시 완료:", link)
            e.update(status="완료", permalink=link, posted_at=datetime.datetime.now(KST).isoformat(timespec="minutes"))
        except Exception as ex:
            log("실패:", ex)
            e.update(status="실패", error=str(ex)[:300])
        json.dump(queue, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
