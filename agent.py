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
    try:
        items += meme_api()
    except Exception as e:
        print("skip meme_api", e)
    try:
        items += anime_trending()
    except Exception as e:
        print("skip anilist", e)

    items.sort(key=lambda x: x["skor"] or 0, reverse=True)
    items = items[:20]

    hasil = ranking_gemini(items)
    if not hasil:
        hasil = "(Gemini lagi sibuk, ini daftar mentah)\n\n" + "\n".join(
            f"- [{i['sumber']}] {i['judul']} ({i['skor']}) {i['link']}" for i in items[:10]
        )
    kirim_telegram("🔥 Konten viral hari ini\n\n" + hasil, [i["gambar"] for i in items])
