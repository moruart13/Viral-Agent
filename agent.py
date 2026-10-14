import os, re, time, requests
from datetime import datetime, timedelta, timezone

# ====== PENGATURAN (ubah di sini) ======
TIKTOK_TAGS = ["ardrawing", "vandraw", "arttok", "digitalart"]   # tanpa tanda #
IG_TAGS = ["ardrawing", "vandraw", "digitalart"]
TIKTOK_AKUN = []   # contoh: ["namaakun"] kalau VanDraw itu akun
IG_AKUN = []       # contoh: ["namaakun"]
HASIL_PER_TAG = 5          # makin kecil makin murah
BATAS_ITEM_APIFY = 40      # batas keras jumlah hasil per sekali jalan
QUERY_YOUTUBE = ["ar drawing", "ar drawing shorts", "vandraw",
                 "digital art process shorts", "art timelapse shorts"]
SUB_ART = ["Art", "drawing", "DigitalPainting", "AnimeART"]
SHORTS_MAX = 60
HARI_MUNDUR = 14
# =======================================

MODELS = (os.getenv("GEMINI_MODEL") or
          "gemini-3.8-flash,gemini-3.8-flash-lite,gemini-flash-latest").split(",")

def potong(teks, n=120):
    teks = re.sub(r"<[^>]+>", " ", teks or "")
    teks = re.sub(r"\s+", " ", teks).strip()
    return teks[:n] if teks else "(tanpa teks)"

def durasi_detik(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 9999
    j, mn, d = (int(x or 0) for x in m.groups())
    return j * 3600 + mn * 60 + d

def apify_run(actor, payload):
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        print("skip apify: APIFY_TOKEN belum diisi")
        return None
    r = requests.post(
        f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
        params={"timeout": 240, "maxItems": BATAS_ITEM_APIFY, "maxTotalChargeUsd": "1"},
        headers={"Authorization": f"Bearer {token}"},
        json=payload, timeout=290)
    if not r.ok:
        print("APIFY ERROR:", actor, r.status_code, r.text[:300])
        return None
    return r.json()

def tiktok_apify():
    payload = {"resultsPerPage": HASIL_PER_TAG}
    if TIKTOK_TAGS:
        payload["hashtags"] = TIKTOK_TAGS
    if TIKTOK_AKUN:
        payload["profiles"] = TIKTOK_AKUN
    data = apify_run("clockworks~tiktok-scraper", payload)
    out = []
    for it in data or []:
        if not it.get("webVideoUrl"):
            continue
        out.append({"sumber": "TikTok Video", "judul": potong(it.get("text")),
                    "skor": int(it.get("playCount") or 0),
                    "gambar": (it.get("videoMeta") or {}).get("coverUrl"),
                    "link": it["webVideoUrl"]})
    return out

def instagram_apify():
    urls = [f"https://www.instagram.com/explore/tags/{t}/" for t in IG_TAGS]
    urls += [f"https://www.instagram.com/{a}/" for a in IG_AKUN]
    data = apify_run("apify~instagram-scraper", {
        "directUrls": urls, "resultsType": "posts", "resultsLimit": HASIL_PER_TAG})
    out = []
    for it in data or []:
        if not it.get("url"):
            continue
        skor = int(it.get("videoPlayCount") or it.get("likesCount") or 0)
        out.append({"sumber": "Instagram Reels", "judul": potong(it.get("caption")),
                    "skor": skor, "gambar": it.get("displayUrl"), "link": it["url"]})
    return out

def youtube_shorts(per_query=15):
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        print("skip youtube: YOUTUBE_API_KEY belum diisi")
        return []
    sejak = (datetime.now(timezone.utc) - timedelta(days=HARI_MUNDUR)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in QUERY_YOUTUBE:
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/search",
                             params={"part": "snippet", "type": "video", "q": q,
                                     "videoDuration": "short", "order": "viewCount",
                                     "publishedAfter": sejak, "maxResults": per_query,
                                     "key": key}, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print("skip youtube", q, e)
            continue
        for it in r.json().get("items", []):
            vid = it["id"]["videoId"]
            if vid not in ids:
                ids.append(vid)
    out = []
    for k in range(0, len(ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                         params={"part": "snippet,statistics,contentDetails",
                                 "id": ",".join(ids[k:k + 50]), "key": key}, timeout=20)
        r.raise_for_status()
        for v in r.json().get("items", []):
            if durasi_detik(v["contentDetails"]["duration"]) > SHORTS_MAX:
                continue
            out.append({"sumber": "YouTube Shorts", "judul": potong(v["snippet"]["title"]),
                        "skor": int(v["statistics"].get("viewCount", 0)),
                        "gambar": v["snippet"]["thumbnails"]["high"]["url"],
                        "link": f"https://youtube.com/shorts/{v['id']}"})
    return out

def reddit_art(n=10):
    out = []
    for sub in SUB_ART:
        try:
            r = requests.get(f"https://meme-api.com/gimme/{sub}/{n}", timeout=20)
            r.raise_for_status()
        except Exception as e:
            print("skip reddit", sub, e)
            continue
        for m in r.json().get("memes", []):
            if m.get("nsfw") or m.get("spoiler"):
                continue
            out.append({"sumber": f"r/{sub}", "judul": potong(m["title"]), "skor": m["ups"],
                        "gambar": m["url"], "link": m["postLink"]})
    return out

def ranking_gemini(items):
    daftar = "\n".join(
        f"- [{i['sumber']}] {i['judul']} (skor {i['skor']}) {i['link']}" for i in items
    )
    prompt = (
        "Kamu analis konten sosmed khusus seni dan gambar. Dari daftar di bawah, pilih "
        "10 yang paling berpotensi viral di kalangan pecinta seni di Indonesia. Minimal "
        "5 di antaranya harus video (AR drawing, VanDraw, atau proses menggambar; sumber "
        "bertuliskan Shorts, Video, atau Reels). Untuk tiap pilihan beri: judul, alasan "
        "singkat, dan 1 ide konten orisinal bahasa Indonesia yang terinspirasi darinya "
        "(bukan repost mentah).\n\n" + daftar
    )
    key = os.environ["GEMINI_API_KEY"].strip()
    for model in MODELS:
        model = model.strip()
        for percobaan in range(2):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": key},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=60,
                )
            except requests.exceptions.RequestException as e:
                print("GEMINI koneksi/timeout:", model, e)
                time.sleep(10)
                continue
            if r.ok:
                print("Gemini sukses pakai", model)
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            print("GEMINI ERROR:", model, r.status_code, r.text[:300])
            if r.status_code in (400, 403, 404):
                break
            time.sleep(15)
    return None

def kirim_telegram(teks, gambar):
    tok = os.environ["TELEGRAM_TOKEN"].strip()
    chat = os.environ["TELEGRAM_CHAT_ID"].strip()
    base = f"https://api.telegram.org/bot{tok}"
    r = requests.post(f"{base}/sendMessage", json={"chat_id": chat, "text": teks[:4000]})
    if not r.ok:
        print("TELEGRAM ERROR:", r.status_code, r.text)
    for url in gambar[:8]:
        requests.post(f"{base}/sendPhoto", json={"chat_id": chat, "photo": url})

if __name__ == "__main__":
    items = []
    sumber_data = [("tiktok", tiktok_apify), ("instagram", instagram_apify),
                   ("youtube", youtube_shorts), ("reddit_art", reddit_art)]
    for nama, fungsi in sumber_data:
        try:
            items += fungsi()
        except Exception as e:
            print("skip", nama, e)

    per_sumber = {}
    ada = set()
    for i in sorted(items, key=lambda x: x["skor"] or 0, reverse=True):
        if i["link"] in ada:
            continue
        ada.add(i["link"])
        per_sumber.setdefault(i["sumber"], []).append(i)
    items = []
    for nama, daftar in per_sumber.items():
        pendek = any(k in nama for k in ("Short", "Video", "Reels"))
        items += daftar[:6 if pendek else 3]
    foto = [daftar[0]["gambar"] for daftar in per_sumber.values() if daftar[0].get("gambar")]

    hasil = ranking_gemini(items)
    if not hasil:
        hasil = "(Gemini lagi sibuk, ini daftar mentah)\n\n" + "\n".join(
            f"- [{i['sumber']}] {i['judul']} ({i['skor']}) {i['link']}" for i in items[:20]
        )
    kirim_telegram("🎨 Konten art viral hari ini\n\n" + hasil, foto)
