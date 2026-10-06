import os, requests

UA = {"User-Agent": "viral-agent/0.1"}
SUBS = ["memes", "dankmemes", "wholesomememes", "Animemes", "awwnime"]

def reddit_top(sub, n=8):
    r = requests.get(f"https://www.reddit.com/r/{sub}/top.json?t=day&limit={n}",
                     headers=UA, timeout=20)
    r.raise_for_status()
    out = []
    for p in r.json()["data"]["children"]:
        d = p["data"]
        if d.get("post_hint") == "image":
            out.append({"sumber": f"r/{sub}", "judul": d["title"], "skor": d["score"],
                        "komentar": d["num_comments"], "gambar": d["url"],
                        "link": "https://reddit.com" + d["permalink"]})
    return out

def anime_trending(n=8):
    q = """{Page(perPage:%d){media(sort:TRENDING_DESC,type:ANIME){
      title{romaji} coverImage{large} averageScore siteUrl}}}""" % n
    r = requests.post("https://graphql.anilist.co", json={"query": q}, timeout=20)
    r.raise_for_status()
    return [{"sumber": "AniList", "judul": m["title"]["romaji"], "skor": m["averageScore"],
             "gambar": m["coverImage"]["large"], "link": m["siteUrl"]}
            for m in r.json()["data"]["Page"]["media"]]

def ranking_gemini(items):
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    prompt = ("Kamu analis konten sosmed. Dari daftar di bawah, pilih 7 yang paling "
              "berpotensi viral di Indonesia. Untuk tiap pilihan beri: judul, alasan "
              "singkat, dan 1 ide caption bahasa Indonesia yang santai. Format rapi.\n\n"
              + "\n".join(f"- [{i['sumber']}] {i['judul']} (skor {i['skor']}) {i['link']}"
                          for i in items))
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

def kirim_telegram(teks, gambar):
    tok, chat = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    base = f"https://api.telegram.org/bot{tok}"
    requests.post(f"{base}/sendMessage", json={"chat_id": chat, "text": teks[:4000]})
    for url in gambar[:3]:
        requests.post(f"{base}/sendPhoto", json={"chat_id": chat, "photo": url})

if __name__ == "__main__":
    items = []
    for s in SUBS:
        try: items += reddit_top(s)
        except Exception as e: print("skip", s, e)
    try: items += anime_trending()
    except Exception as e: print("skip anilist", e)

    items.sort(key=lambda x: x["skor"] or 0, reverse=True)
    items = items[:30]
    kirim_telegram("🔥 Konten viral hari ini\n\n" + ranking_gemini(items),
                   [i["gambar"] for i in items])
