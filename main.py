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

# API anahtarı Render üzerinden çekilecek (Güvenli yöntem)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyAkIs-faygLuYzB9RrL9TLZRe2G2o8lWmo")
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
    {"id": "ekonomist", "ad": "Özgür Demirtaş", "url": "https://www.youtube.com/@ProfDrOzgurDemirtas/videos"},
    {"id": "evrim", "ad": "Evrim Ağacı", "url": "https://www.youtube.com/@evrimagaci/videos"},
    {"id": "dw", "ad": "DW Türkçe", "url": "https://www.youtube.com/@dwturkce/videos"},
    {"id": "t24", "ad": "T24 Haber", "url": "https://www.youtube.com/@t24tv/videos"}
]

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
    async with sem:
        try:
            await asyncio.sleep(1)
            prompt = f"""Şu videoyu analiz et: https://youtube.com/watch?v={vid}. 
            Konu başlıklarını ve çarpıcı fikirleri HTML (card, h4 ve li) olarak özetle. Markdown kullanma."""
            res = await asyncio.to_thread(client.models.generate_content, model='gemini-1.5-flash', contents=prompt)
            html = res.text.replace('```html', '').replace('```', '').strip()
            # Senin şık kart tasarımınla birleştiriyoruz
            final_html = f"<div class='card'><div class='card-header'><span class='badge'>{name}</span></div><h3 class='vid-title'>{vtitle}</h3>{html}<a href='https://youtube.com/watch?v={vid}' target='_blank' class='source-link'>🔗 Orijinal Videoya Git</a></div>"
            return {"type": "result", "html": final_html, "current_title": vtitle}
        except Exception as e:
            return {"type": "result", "html": f"<p>Hata: {str(e)}</p>", "current_title": vtitle}

@app.get("/", response_class=HTMLResponse)
def index():
    checks = "".join([f'<label class="item" data-name="{u["ad"].lower()}"><span class="item-text">{u["ad"]}</span><input type="checkbox" value="{u["id"]}" class="ch"><span class="checkmark"></span></label>' for u in UNLU_LISTESI])
    
    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ZAFER HABER RADARI</title>
        <style>
            :root {{ --p: #ff4757; --bg: #f8fafc; --c: #ffffff; --t: #0f172a; --border: #e2e8f0; --muted: #64748b; }}
            body.dark {{ --bg: #0b0f19; --c: #161b2a; --t: #e2e8f0; --border: #30363d; --muted: #8b949e; }}
            body {{ font-family: 'Segoe UI', sans-serif; margin:0; background: var(--bg); color: var(--t); display: flex; min-height: 100vh; overflow-x: hidden; }}
            #side {{ width: 320px; height: 100vh; background: var(--c); border-right: 1px solid var(--border); position: fixed; padding: 20px; z-index: 100; overflow-y: auto; transition: 0.3s; }}
            #main {{ margin-left: 320px; padding: 40px; flex: 1; }}
            .card {{ background: var(--c); border-radius: 16px; padding: 25px; margin-bottom: 25px; border: 1px solid var(--border); border-left: 5px solid var(--p); box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
            .badge {{ background: var(--p); color: white; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }}
            .btn-p {{ background: var(--p); color: white; border: none; padding: 15px; width: 100%; border-radius: 8px; cursor: pointer; font-weight: bold; }}
            .item {{ display: flex; justify-content: space-between; padding: 10px; border-bottom: 1px solid var(--border); cursor: pointer; }}
            #progress-container {{ display: none; background: var(--c); padding: 20px; border-radius: 12px; border: 1px solid var(--border); margin-bottom: 20px; }}
            .progress-bar {{ height: 8px; background: var(--p); width: 0%; transition: 0.4s; border-radius: 10px; }}
            .source-link {{ color: var(--muted); text-decoration: none; font-size: 0.8rem; margin-top: 10px; display: block; }}
        </style>
    </head>
    <body class="dark">
        <div id="side">
            <h2 style="color:var(--p);">ZAFER RADARI</h2>
            <div id="u-list">{checks}</div>
            <button class="btn-p" onclick="run()" style="margin-top:20px;">RADARI BAŞLAT</button>
        </div>
        <div id="main">
            <div id="progress-container">
                <div id="p-text">Hazırlanıyor...</div>
                <div style="background:var(--border); height:8px; border-radius:10px; margin-top:10px;">
                    <div class="progress-bar" id="p-bar"></div>
                </div>
            </div>
            <div id="box"></div>
        </div>
        <script>
            async function run() {{
                const ids = Array.from(document.querySelectorAll('.ch:checked')).map(c => c.value);
                if(ids.length === 0) return alert("Seçim yapın!");
                
                document.getElementById('box').innerHTML = "";
                document.getElementById('progress-container').style.display = "block";
                
                const res = await fetch('/api/analyze', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ids: ids}})
                }});
                
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let completed = 0;
                let total = 0;

                while(true) {{
                    const {{done, value}} = await reader.read();
                    if(done) break;
                    const lines = decoder.decode(value).split('\\n');
                    for(let line of lines) {{
                        if(!line.trim()) continue;
                        const data = JSON.parse(line);
                        if(data.type === 'start') total = data.total;
                        if(data.type === 'result') {{
                            completed++;
                            document.getElementById('p-bar').style.width = (completed/total*100) + '%';
                            if(data.html) {{
                                const d = document.createElement('div');
                                d.innerHTML = data.html;
                                document.getElementById('box').prepend(d);
                            }}
                        }}
                    }}
                }}
            }}
        </script>
    </body>
    </html>
    """

@app.post("/api/analyze")
async def analyze_videos(req: AnalizRequest):
    async def generate():
        vids_to_process = []
        if req.q:
            vids = get_recent_vids(req.q, 1)
            for vid, title in vids:
                vids_to_process.append({"name": "Özel Arama", "vid": vid, "title": title})
        elif req.ids:
            for uid in req.ids:
                user = next((u for u in UNLU_LISTESI if u["id"] == uid), None)
                if user:
                    vids = get_recent_vids(user["url"], 1)
                    for vid, title in vids:
                        vids_to_process.append({"name": user["ad"], "vid": vid, "title": title})
        
        total = len(vids_to_process)
        yield f"{json.dumps({'type': 'start', 'total': total, 'vids': vids_to_process})}\n"
        
        if total == 0: return

        sem = asyncio.Semaphore(3)
        tasks = [process_video(v["name"], v["vid"], v["title"], sem) for v in vids_to_process]
        
        for coro in asyncio.as_completed(tasks):
            res = await coro
            yield f"{json.dumps(res)}\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
