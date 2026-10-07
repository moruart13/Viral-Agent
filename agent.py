import os, re, time, requests
from datetime import datetime, timedelta, timezone

SHORTS_MAX = 60
QUERY_SHORTS = ["meme lucu shorts", "anime shorts", "anime edit shorts",
                "viral shorts indonesia", "meme shorts"]

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

def meme_api(n=8):
    out = []
    for sub in ["memes", "dankmemes", "wholesomememes", "Animemes"]:
        r = requests.get(f"https://meme-api.com/gimme/{sub}/{n}", timeout=20)
        r.raise_for_status()
        for m in r.json()["memes"]:
            out.append({"sumber": f"r/{sub}", "judul": potong(m["title"]), "skor": m["ups"],
                        "gambar": m["url"], "link": m["postLink"]})
    return out

def anime_trending(n=8):
    q = """{Page(perPage:%d){media(sort:TRENDING_DESC,type:ANIME){
      title{romaji} coverImage{large} averageScore siteUrl}}}""" % n
    r = requests.post("https://graphql.anilist.co", json={"query": q}, timeout=20)
    r.raise_for_status()
    return [{"sumber": "AniList", "judul": m["title"]["romaji"], "skor": m["averageScore"] or 0,
             "gambar": m["coverImage"]["large"], "link": m["siteUrl"]}
            for m in r.json()["data"]["Page"]["media"]]

def youtube_trending(n=10):
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        print("skip youtube: YOUTUBE_API_KEY belum diisi")
        return []
    out, ada = [], set()
    for kategori, label in [("", "Umum"), ("23", "Comedy"), ("1", "Film & Animation")]:
        params = {"part": "snippet,statistics", "chart": "mostPopular",
                  "regionCode": "ID", "maxResults": n, "key": key}
        if kategori:
            params["videoCategoryId"] = kategori
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                             params=params, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print("skip youtube", label, e)
            continue
        for v in r.json().get("items", []):
            if v["id"] in ada:
                continue
            ada.add(v["id"])
            out.append({"sumber": f"YouTube {label}", "judul": potong(v["snippet"]["title"]),
                        "skor": int(v["statistics"].get("viewCount", 0)),
                        "gambar": v["snippet"]["thumbnails"]["high"]["url"],
                        "link": f"https://youtu.be/{v['id']}"})
    return out

def youtube_shorts(per_query=15):
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        print("skip shorts: YOUTUBE_API_KEY belum diisi")
        return []
    sejak = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in QUERY_SHORTS:
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/search",
                             params={"part": "snippet", "type": "video", "q": q,
                                     "videoDuration": "short", "order": "viewCount",
                                     "regionCode": "ID", "relevanceLanguage": "id",
                                     "publishedAfter": sejak, "maxResults": per_query,
                                     "key": key}, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print("skip shorts", q, e)
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

def bluesky_hot(n=50):
    r = requests.get(
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getFeed",
        params={"feed": "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot",
                "limit": n},
        timeout=20)
    r.raise_for_status()
    out = []
    for it in r.json().get("feed", []):
        p = it["post"]
        emb = p.get("embed") or {}
        imgs = emb.get("images") or []
        if imgs:
            sumber, gambar = "Bluesky", imgs[0]["fullsize"]
        elif str(emb.get("$type", "")).startswith("app.bsky.embed.video") and emb.get("thumbnail"):
            sumber, gambar = "Bluesky Video", emb["thumbnail"]
        else:
            continue
        rkey = p["uri"].split("/")[-1]
        skor = (p.get("likeCount") or 0) + 2 * (p.get("repostCount") or 0)
        out.append({"sumber": sumber, "judul": potong(p["record"].get("text")),
                    "skor": skor, "gambar": gambar,
                    "link": f"https://bsky.app/profile/{p['author']['handle']}/post/{rkey}"})
    return out

def mastodon_trending(n=40):
    r = requests.get("https://mastodon.social/api/v1/trends/statuses",
                     params={"limit": n}, timeout=20)
    r.raise_for_status()
    out = []
    for s in r.json():
        media = s.get("media_attachments", [])
        imgs = [m for m in media if m.get("type") == "image"]
        vids = [m for m in media if m.get("type") in ("video", "gifv")]
        if imgs:
            sumber, gambar = "Mastodon", imgs[0]["url"]
        elif vids and vids[0].get("preview_url"):
            sumber, gambar = "Mastodon Video", vids[0]["preview_url"]
        else:
            continue
        skor = (s.get("favourites_count") or 0) + 2 * (s.get("reblogs_count") or 0)
        out.append({"sumber": sumber, "judul": potong(s.get("content")),
                    "skor": skor, "gambar": gambar, "link": s["url"]})
    return out

def imgur_hot(n=15):
    cid = os.getenv("IMGUR_CLIENT_ID", "").strip()
    if not cid:
        print("skip imgur: IMGUR_CLIENT_ID belum diisi")
        return []
    r = requests.get("https://api.imgur.com/3/gallery/hot/viral/day",
                     headers={"Authorization": f"Client-ID {cid}"}, timeout=20)
    r.raise_for_status()
    out = []
    for it in r.json().get("data", [])[:n]:
        if it.get("is_album"):
            imgs = it.get("images") or []
            gambar = imgs[0].get("link") if imgs else None
        else:
            gambar = it.get("link")
        if not gambar or not gambar.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        out.append({"sumber": "Imgur", "judul": potong(it.get("title")),
                    "skor": it.get("ups") or it.get("points") or 0,
                    "gambar": gambar, "link": it.get("link") or gambar})
    return out

def giphy_trending(n=10):
    key = os.getenv("GIPHY_API_KEY", "").strip()
    if not key:
        print("skip giphy: GIPHY_API_KEY belum diisi")
        return []
    r = requests.get("https://api.giphy.com/v1/gifs/trending",
                     params={"api_key": key, "limit": n}, timeout=20)
    r.raise_for_status()
    out = []
    for i, g in enumerate(r.json().get("data", [])):
        out.append({"sumber": "Giphy", "judul": potong(g.get("title")),
                    "skor": n - i, "gambar": g["images"]["original_still"]["url"],
                    "link": g["url"]})
    return out

def ranking_gemini(items):
    daftar = "\n".join(
        f"- [{i['sumber']}] {i['judul']} (skor {i['skor']}) {i['link']}" for i in items
    )
    prompt = (
        "Kamu analis konten sosmed. Dari daftar di bawah, pilih 10 yang paling "
        "berpotensi viral di Indonesia. Minimal 5 di antaranya harus konten video "
        "pendek (sumber bertuliskan Shorts atau Video). Untuk tiap pilihan beri: "
        "judul, alasan singkat, dan 1 ide caption bahasa Indonesia yang santai.\n\n"
        + daftar
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
    sumber_data = [("meme_api", meme_api), ("anilist", anime_trending),
                   ("youtube", youtube_trending), ("youtube_shorts", youtube_shorts),
                   ("bluesky", bluesky_hot), ("mastodon", mastodon_trending),
                   ("imgur", imgur_hot), ("giphy", giphy_trending)]
    for nama, fungsi in sumber_data:
        try:
            items += fungsi()
        except Exception as e:
            print("skip", nama, e)

    # skala skor tiap platform beda, jadi ambil per sumber; video pendek dapat jatah lebih banyak
    per_sumber = {}
    for i in sorted(items, key=lambda x: x["skor"] or 0, reverse=True):
        per_sumber.setdefault(i["sumber"], []).append(i)
    items = []
    for nama, daftar in per_sumber.items():
        batas = 6 if ("Short" in nama or "Video" in nama) else 3
        items += daftar[:batas]
    foto = [daftar[0]["gambar"] for daftar in per_sumber.values() if daftar[0].get("gambar")]

    hasil = ranking_gemini(items)
    if not hasil:
        hasil = "(Gemini lagi sibuk, ini daftar mentah)\n\n" + "\n".join(
            f"- [{i['sumber']}] {i['judul']} ({i['skor']}) {i['link']}" for i in items[:20]
        )
    kirim_telegram("🔥 Konten viral hari ini\n\n" + hasil, foto)
