import os, requests

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
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    daftar = "\n".join(
        f"- [{i['sumber']}] {i['judul']} (skor {i['skor']}) {i['link']}" for i in items
    )
    prompt = (
        "Kamu analis konten sosmed. Dari daftar di bawah, pilih 7 yang paling "
        "berpotensi viral di Indonesia. Untuk tiap pilihan beri: judul, alasan "
        "singkat, dan 1 ide caption bahasa Indonesia yang santai.\n\n" + daftar
    )
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": os.environ["GEMINI_API_KEY"].strip()},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=180,
    )
    if not r.ok:
        print("GEMINI ERROR:", r.status_code, r.text)
        r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

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
    kirim_telegram("🔥 Konten viral hari ini\n\n" + ranking_gemini(items),
                   [i["gambar"] for i in items])
