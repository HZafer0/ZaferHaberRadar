import uvicorn
import yt_dlp
import asyncio
import json
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from google import genai
from typing import List

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI()

UNLU_LISTESI = [
    {"id": "altayli", "ad": "Fatih Altaylı", "url": "https://www.youtube.com/@fatihaltayli/videos"},
    {"id": "ozdemir", "ad": "Cüneyt Özdemir", "url": "https://www.youtube.com/@cuneytozdemir/videos"},
    {"id": "mengu", "ad": "Nevşin Mengü", "url": "https://www.youtube.com/@nevsinmengu/videos"},
    {"id": "140journos", "ad": "140journos", "url": "https://www.youtube.com/@140journos/videos"},
    {"id": "metan", "ad": "Adem Metan", "url": "https://www.youtube.com/@AdemMetan/videos"},
    {"id": "sozcu", "ad": "Sözcü TV", "url": "https://www.youtube.com/@sozcutelevizyonu/videos"},
    {"id": "babala", "ad": "BaBaLa TV", "url": "https://www.youtube.com/@BabalaTV/videos"},
    {"id": "ekonomist", "ad": "Özgür Demirtaş", "url": "https://www.youtube.com/@Prof.Dr.ÖzgürDemirtaş/videos"},
    {"id": "evrim", "ad": "Evrim Ağacı", "url": "https://www.youtube.com/@evrimagaci/videos"},
    {"id": "dw", "ad": "DW Türkçe", "url": "https://www.youtube.com/@dwturkce/videos"},
    {"id": "t24", "ad": "T24 Haber", "url": "https://www.youtube.com/@t24tv/videos"}
]

# --- HAFIZA (CACHE) SİSTEMİ ---
HAFIZA_DOSYASI = "hafiza.json"

def hafiza_yukle():
    if os.path.exists(HAFIZA_DOSYASI):
        try:
            with open(HAFIZA_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def hafiza_kaydet(hafiza_verisi):
    try:
        with open(HAFIZA_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(hafiza_verisi, f, ensure_ascii=False, indent=2)
    except: pass

ANALIZ_HAFIZASI = hafiza_yukle()
# ------------------------------

class AnalizRequest(BaseModel):
    ids: List[str] = []
    q: str = None

def get_recent_vids(query, count=1):
    try:
        opts = {'extract_flat': True, 'playlist_end': count, 'quiet': True}
        search = query if "youtube.com" in query or "youtu.be" in query else f"ytsearch{count}:{query}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(search, download=False)
            vids = []
            if 'entries' in res:
                for entry in res['entries'][:count]:
                    vids.append((entry['id'], entry.get('title', 'Video')))
            return vids
    except: return []

async def process_video(name, vid, vtitle, sem):
    # 1. ADIM: VİDEO HAFIZADA VAR MI KONTROL ET!
    if vid in ANALIZ_HAFIZASI:
        # Varsa hiç Google'a sorma, bekleme yapma, direkt hafızadan gönder!
        return {"type": "result", "html": ANALIZ_HAFIZASI[vid], "current_title": f"{vtitle} (Hafızadan)"}

    # 2. ADIM: YOKSA ANALİZ ET VE HAFIZAYA KAYDET
    async with sem:
        try:
            await asyncio.sleep(3) # Kota dostu bekleme
            prompt = f"""Şu videoyu analiz et: https://youtube.com/watch?v={vid}.
            LÜTFEN TÜM VİDEOYU ÖZETLEME! Sadece videoda konuşulan ana "Konu Başlıklarını" bul.
            Her konunun altına o kişinin o konuda söylediği en önemli, çarpıcı şeyleri ve fikirleri madde madde yaz.
            SADECE şu HTML yapısını döndür (markdown kullanma):
            <div class='card'>
                <div class='card-header'><span class='badge'>{name}</span></div>
                <h3 class='vid-title'>{vtitle}</h3>
                <div class='topic'>
                    <h4 class='topic-title'>📌 [Konu Başlığı]</h4>
                    <ul><li>[Söylediği önemli söz/fikir]</li></ul>
                </div>
                <a href='https://youtube.com/watch?v={vid}' target='_blank' class='source-link'>🔗 Orijinal Videoya Git</a>
            </div>
            """
            res = await asyncio.to_thread(client.models.generate_content, model='gemini-1.5-flash', contents=prompt)
            html = res.text.replace('```html', '').replace('```', '').strip()
            
            # Başarılı analizi hafızaya ekle ve dosyaya kaydet
            ANALIZ_HAFIZASI[vid] = html
            hafiza_kaydet(ANALIZ_HAFIZASI)
            
            return {"type": "result", "html": html, "current_title": vtitle}
        except Exception as e:
            err_html = f"<div class='card' style='border-left: 5px solid red;'><div class='card-header'><span class='badge' style='background:red;'>HATA</span></div><h3 class='vid-title'>{vtitle}</h3><p style='color:red;'>⚠️ Bu videonun analizi sırasında bir hata oluştu. (Yapay zeka yanıt veremedi veya API kotası doldu)</p></div>"
            return {"type": "result", "html": err_html, "current_title": vtitle}

# --- ARAYÜZ (HTML) KODLARI ---
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZAFER HABER RADARI</title>
    <style>
        :root { --p: #ff4757; --bg: #f8fafc; --c: #ffffff; --t: #0f172a; --border: #e2e8f0; --muted: #64748b; }
        body.dark { --bg: #0b0f19; --c: #161b2a; --t: #e2e8f0; --border: #30363d; --muted: #8b949e; }
        ::-webkit-scrollbar { width: 0px; background: transparent; }
        * { scrollbar-width: none; box-sizing: border-box; }
        body { font-family: 'Segoe UI', system-ui, sans-serif; margin:0; background: var(--bg); color: var(--t); display: flex; transition: 0.3s; min-height: 100vh; }
        #side { width: 320px; height: 100vh; background: var(--c); border-right: 1px solid var(--border); position: fixed; padding: 70px 20px 25px 20px; overflow-y: auto; z-index: 100; transition: 0.4s; }
        #main { margin-left: 320px; padding: 70px 40px 40px 40px; flex: 1; max-width: 1100px; transition: 0.4s; }
        .top-btn { position: fixed; top: 15px; width: 45px; height: 45px; border-radius: 12px; background: var(--c); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; z-index: 1000; cursor: pointer; font-size: 1.4rem; color: var(--t); }
        .theme-toggle { right: 15px; }
        .card { background: var(--c); border-radius: 16px; padding: 25px; margin-bottom: 25px; border: 1px solid var(--border); border-left: 5px solid var(--p); }
        .card-header { margin-bottom: 15px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
        .badge { background: var(--p); color: white; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }
        .vid-title { margin: 10px 0; font-size: 1.2rem; }
        .topic { background: rgba(128,128,128,0.05); border-radius: 8px; padding: 15px; margin-top: 15px; border-left: 3px solid var(--p); }
        .topic-title { margin: 0 0 10px 0; font-size: 1.05rem; }
        .topic ul { margin: 0; padding-left: 20px; color: var(--muted); }
        .source-link { display: inline-block; margin-top: 20px; font-size: 0.85rem; color: var(--muted); text-decoration: none; font-weight: 600; }
        input[type="text"] { width: 100%; padding: 12px; background: var(--bg); border: 1px solid var(--border); color: var(--t); border-radius: 8px; margin-bottom: 15px; }
        button.btn-p { width: 100%; padding: 15px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; background: linear-gradient(135deg, #ff4757, #ff6b81); color: white; margin-top: 20px; }
        button.btn-d { width: 100%; padding: 12px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; background: var(--bg); color: var(--t); margin-bottom: 5px; }
        .item { padding: 12px 10px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; cursor: pointer; border-radius: 8px; }
        .item input { position: absolute; opacity: 0; cursor: pointer; }
        .checkmark { height: 22px; width: 22px; background: var(--bg); border: 2px solid var(--border); border-radius: 6px; display: flex; align-items: center; justify-content: center; }
        .item input:checked ~ .checkmark { background: var(--p); border-color: var(--p); }
        .item input:checked ~ .checkmark:after { content: ""; display: block; width: 5px; height: 10px; border: solid white; border-width: 0 2px 2px 0; transform: rotate(45deg); margin-bottom: 2px; }
        #progress-container { display: none; margin-bottom: 30px; background: var(--c); padding: 20px; border-radius: 12px; border: 1px solid var(--border); }
        .progress-bg { background: var(--border); height: 8px; border-radius: 10px; overflow: hidden; margin-top: 15px; }
        .progress-bar { width: 0%; height: 100%; background: var(--p); transition: 0.4s; }
    </style>
</head>
<body class="dark">
    <button class="top-btn theme-toggle" onclick="document.body.classList.toggle('dark')">🌓</button>
    <div id="side">
        <h2 style="color:var(--p); margin:0 0 15px 0; font-size: 1.8rem;">ZAFER RADARI</h2>
        <div id="u-list">{CHECKS}</div>
        <div style="display:flex; gap:10px; margin-top:15px;">
            <button class="btn-d" onclick="document.querySelectorAll('.ch').forEach(c => c.checked = true)">Tümünü Seç</button>
            <button class="btn-d" onclick="document.querySelectorAll('.ch').forEach(c => c.checked = false)">Temizle</button>
        </div>
        <button class="btn-p" onclick="run()">RADARI BAŞLAT</button>
    </div>
    <div id="main">
        <div id="progress-container">
            <div id="p-text">Hedefler taranıyor...</div>
            <div class="progress-bg"><div class="progress-bar" id="p-bar"></div></div>
        </div>
        <div id="box"><div style="text-align:center; margin-top:15vh; opacity:0.4;"><h2>Radar Beklemede</h2></div></div>
    </div>
    <script>
        async function run() {
            const ids = Array.from(document.querySelectorAll('.ch:checked')).map(c => c.value);
            if(ids.length === 0) return alert("Kişi seçin!");
            
            const box = document.getElementById('box');
            const pCont = document.getElementById('progress-container');
            const pBar = document.getElementById('p-bar');
            const pText = document.getElementById('p-text');
            
            box.innerHTML = ""; pCont.style.display = "block"; pBar.style.width = "0%"; pText.innerText = "Bağlanıyor...";
            
            try {
                const res = await fetch('/api/analyze', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ids: ids}) });
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let completed = 0, total = 0, buffer = "";

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, {stream: true});
                    const lines = buffer.split('\\n');
                    buffer = lines.pop(); 

                    for (let line of lines) {
                        if (!line.trim()) continue;
                        const data = JSON.parse(line);
                        if (data.type === 'start') {
                            total = data.total; pText.innerHTML = `🎯 Toplam ${total} video bulunuyor...`;
                        } else if (data.type === 'result') {
                            completed++; pBar.style.width = Math.round((completed / total) * 100) + '%';
                            pText.innerHTML = `⏳ ${completed} / ${total} tamamlandı. Son analiz: ${data.current_title}`;
                            if (data.html) box.insertAdjacentHTML('afterbegin', data.html);
                        }
                    }
                }
                pText.innerHTML = "✅ Tüm işlemler bitti!"; setTimeout(() => pCont.style.display = 'none', 3000);
            } catch(e) { pText.innerText = "Hata oluştu."; }
        }
    </script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def index():
    checks_html = "".join([f'<label class="item"><span class="item-text">{u["ad"]}</span><input type="checkbox" value="{u["id"]}" class="ch"><span class="checkmark"></span></label>' for u in UNLU_LISTESI])
    return HTML_TEMPLATE.replace("{CHECKS}", checks_html)

@app.post("/api/analyze")
async def analyze_videos(req: AnalizRequest):
    async def generate():
        vids_to_process = []
        if req.q:
            vids = get_recent_vids(req.q, 1)
            for vid, title in vids:
                vids_to_process.append({"name": "Özel Arama", "vid": vid, "title": title})
        else:
            for uid in req.ids:
                user = next((u for u in UNLU_LISTESI if u["id"] == uid), None)
                if user:
                    vids = get_recent_vids(user["url"], 1)
                    for vid, title in vids:
                        vids_to_process.append({"name": user["ad"], "vid": vid, "title": title})
        
        yield f"{json.dumps({'type': 'start', 'total': len(vids_to_process)})}\n"
        
        sem = asyncio.Semaphore(1)
        tasks = [process_video(v["name"], v["vid"], v["title"], sem) for v in vids_to_process]
        for coro in asyncio.as_completed(tasks):
            res = await coro
            yield f"{json.dumps(res)}\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
