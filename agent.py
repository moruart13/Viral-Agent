import os, time, requests

MODELS = (os.getenv("GEMINI_MODEL") or
          "gemini-3.8-flash,gemini-3.8-flash-lite,gemini-flash-latest").split(",")

def meme_api(n=8):
    out = []
    for sub in ["memes", "dankmemes", "wholesomememes", "Animemes"]:
        r = requests.get(f"https://meme-api.com/gimme/{sub}/{n}", timeout=20)
        r.raise_for_status()
        for m in r.json()["memes"]:
            out.append({"sumber": f"r/{sub}", "judul": m["title"], "skor": m["ups"],
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
            out.append({"sumber": f"YouTube {label}", "judul": v["snippet"]["title"],
                        "skor": int(v["statistics"].get("viewCount", 0)),
                        "gambar": v["snippet"]["thumbnails"]["high"]["url"],
                        "link": f"https://youtu.be/{v['id']}"})
    return out

def ranking_gemini(items):
    daftar = "\n".join(
        f"- [{i['sumber']}] {i['judul']} (skor {i['skor']}) {i['link']}" for i in items
    )
    prompt = (
        "Kamu analis konten sosmed. Dari daftar di bawah, pilih 7 yang paling "
        "berpotensi viral di Indonesia. Untuk tiap pilihan beri: judul, alasan "
        "singkat, dan 1 ide caption bahasa Indonesia yang santai.\n\n" + daftar
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
    for url in gambar[:3]:
        requests.post(f"{base}/sendPhoto", json={"chat_id": chat, "photo": url})

if __name__ == "__main__":
    items = []
    for nama, fungsi in [("meme_api", meme_api), ("anilist", anime_trending),
                         ("youtube", youtube_trending)]:
        try:
            items += fungsi()
        except Exception as e:
            print("skip", nama, e)

    # skor tiap platform beda skala (views vs upvotes), jadi ambil per sumber biar seimbang
    per_sumber = {}
    for i in sorted(items, key=lambda x: x["skor"] or 0, reverse=True):
        per_sumber.setdefault(i["sumber"], []).append(i)
    items = [i for daftar in per_sumber.values() for i in daftar[:4]]

    hasil = ranking_gemini(items)
    if not hasil:
        hasil = "(Gemini lagi sibuk, ini daftar mentah)\n\n" + "\n".join(
            f"- [{i['sumber']}] {i['judul']} ({i['skor']}) {i['link']}" for i in items[:12]
        )
    kirim_telegram("🔥 Konten viral hari ini\n\n" + hasil, [i["gambar"] for i in items])
