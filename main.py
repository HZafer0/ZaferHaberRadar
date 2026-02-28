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

# ==========================================
# 🧠 HAFIZA (CACHE) SİSTEMİ 
# ==========================================
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
# ==========================================

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
    # 1. BİREYSEL VİDEO ANALİZİ VE HAFIZA KONTROLÜ
    if vid in ANALIZ_HAFIZASI:
        return {"name": name, "vid": vid, "title": vtitle, "content": ANALIZ_HAFIZASI[vid], "cached": True}

    async with sem:
        try:
            await asyncio.sleep(4) # Kota koruması
            prompt = f"""Şu videoyu analiz et: https://youtube.com/watch?v={vid}. 
            Sadece videoda konuşulan ana "Konu Başlıklarını" ve o konularda kişinin söylediği spesifik fikirleri düz metin ve madde madde yaz. Detaya girme, sadece ne dediğini özetle."""
            
            # Google'ın en güncel ve çalışan 2.5 modeli
            res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.5-flash', contents=prompt)
            text_content = res.text.strip()
            
            ANALIZ_HAFIZASI[vid] = text_content
            hafiza_kaydet(ANALIZ_HAFIZASI)
            
            return {"name": name, "vid": vid, "title": vtitle, "content": text_content, "cached": False}
        except Exception as e:
            return {"name": name, "vid": vid, "title": vtitle, "content": f"Hata: {str(e)}", "cached": False}

# ==========================================
# EKSİKSİZ, ORİJİNAL TASARIM (HTML/CSS/JS)
# ==========================================
FULL_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZAFER HABER RADARI</title>
    <link rel="icon" type="image/png" href="/logo.png">
    <style>
        :root { --p: #ff4757; --bg: #f8fafc; --c: #ffffff; --t: #0f172a; --border: #e2e8f0; --muted: #64748b; }
        body.dark { --bg: #0b0f19; --c: #161b2a; --t: #e2e8f0; --border: #30363d; --muted: #8b949e; }
        ::-webkit-scrollbar { width: 0px; background: transparent; }
        * { scrollbar-width: none; box-sizing: border-box; }
        body { font-family: 'Segoe UI', system-ui, sans-serif; margin:0; background: var(--bg); color: var(--t); display: flex; transition: background 0.3s, color 0.3s; overflow-x: hidden; min-height: 100vh; }
        #side { width: 320px; height: 100vh; background: var(--c); border-right: 1px solid var(--border); position: fixed; padding: 70px 20px 25px 20px; overflow-y: auto; z-index: 100; box-shadow: 2px 0 10px rgba(0,0,0,0.05); transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1); transform: translateX(0); }
        #side.closed { transform: translateX(-100%); }
        #main { margin-left: 320px; padding: 70px 40px 40px 40px; flex: 1; max-width: 1100px; transition: margin-left 0.4s cubic-bezier(0.4, 0, 0.2, 1); }
        #main.expanded { margin-left: 0; max-width: 900px; margin: 0 auto; }
        @media (max-width: 768px) {
            #side { transform: translateX(-100%); width: 280px; box-shadow: 5px 0 25px rgba(0,0,0,0.2); }
            #side.mobile-open { transform: translateX(0); }
            #main { margin-left: 0 !important; padding: 70px 15px 20px 15px; width: 100%; }
            .top-btn { top: 10px; width: 40px; height: 40px; font-size: 1.2rem; }
            .menu-toggle { left: 10px; }
            .theme-toggle { right: 10px; }
        }
        .top-btn { position: fixed; top: 15px; width: 45px; height: 45px; border-radius: 12px; background: var(--c); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; z-index: 1000; cursor: pointer; font-size: 1.4rem; box-shadow: 0 2px 10px rgba(0,0,0,0.05); color: var(--t); transition: 0.2s; }
        .top-btn:hover { background: var(--border); }
        .menu-toggle { left: 15px; }
        .theme-toggle { right: 15px; }
        .card { background: var(--c); border-radius: 16px; padding: 25px; margin-bottom: 25px; border: 1px solid var(--border); box-shadow: 0 4px 15px -3px rgba(0, 0, 0, 0.05); transition: transform 0.2s; border-left: 5px solid var(--p); }
        .card-header { margin-bottom: 15px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
        .badge { background: var(--p); color: white; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; text-transform: uppercase; }
        .vid-title { margin: 10px 0; font-size: 1.2rem; line-height: 1.4; color: var(--p); }
        .topic { background: rgba(128,128,128,0.05); border-radius: 8px; padding: 20px; margin-top: 15px; border: 1px solid var(--border); }
        .topic p { line-height: 1.6; }
        .topic ul { margin: 15px 0 0 0; padding-left: 20px; color: var(--t); font-size: 0.95rem; line-height: 1.7; }
        .topic li { margin-bottom: 10px; }
        .topic b { color: var(--p); }
        input[type="text"] { width: 100%; padding: 12px; background: var(--bg); border: 1px solid var(--border); color: var(--t); border-radius: 8px; margin-bottom: 15px; outline: none; }
        button { width: 100%; padding: 12px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; margin-bottom: 8px; color: white; transition: 0.2s; }
        .btn-p { background: linear-gradient(135deg, #ff4757, #ff6b81); }
        .btn-s { background: #238636; margin-top: 5px; }
        .btn-d { background: var(--bg); border: 1px solid var(--border); color: var(--t); font-size: 0.85rem; }
        #specialSearchArea { margin: 20px 0; padding: 15px; background: var(--c); border-radius: 12px; border: 1px solid var(--border); display: none; }
        .section-title { font-size: 0.75rem; font-weight: 800; text-transform: uppercase; color: var(--muted); margin: 20px 0 10px 0; display: block; }
        .item { padding: 12px 10px; border-bottom: 1px solid var(--border); font-size: 0.95rem; display: flex; align-items: center; justify-content: space-between; cursor: pointer; border-radius: 8px; transition: background 0.2s; user-select: none; }
        .item:hover { background: rgba(128,128,128,0.05); }
        .item-text { font-weight: 500; color: var(--t); }
        .item input { position: absolute; opacity: 0; cursor: pointer; height: 0; width: 0; }
        .checkmark { height: 22px; width: 22px; background-color: var(--bg); border: 2px solid var(--border); border-radius: 6px; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }
        .item:hover input ~ .checkmark { border-color: var(--p); }
        .item input:checked ~ .checkmark { background-color: var(--p); border-color: var(--p); }
        .checkmark:after { content: ""; display: none; width: 5px; height: 10px; border: solid white; border-width: 0 2px 2px 0; transform: rotate(45deg); margin-bottom: 2px; }
        .item input:checked ~ .checkmark:after { display: block; }
        #progress-container { display: none; margin-bottom: 30px; background: var(--c); padding: 20px; border-radius: 12px; border: 1px solid var(--border); box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        .progress-bg { background: var(--border); height: 8px; border-radius: 10px; overflow: hidden; margin-top: 15px; }
        .progress-bar { width: 0%; height: 100%; background: var(--p); transition: width 0.4s ease, background 0.4s; }
        #p-text { font-size: 0.95rem; font-weight: 600; color: var(--t); line-height: 1.4; }
        #aboutModal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 2000; align-items: center; justify-content: center; backdrop-filter: blur(3px); }
        .modal-content { background: var(--c); padding: 30px; border-radius: 16px; width: 90%; max-width: 400px; text-align: center; border: 1px solid var(--border); box-shadow: 0 10px 30px rgba(0,0,0,0.2); animation: popIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275); }
        .modal-title { color: var(--p); margin-top: 0; font-size: 1.5rem; }
        @keyframes popIn { 0% { transform: scale(0.8); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }
    </style>
</head>
<body class="dark">
    <button class="top-btn menu-toggle" onclick="toggleMenu()">☰</button>
    <button class="top-btn theme-toggle" onclick="toggleTheme()">🌓</button>

    <div id="side">
        <h2 style="color:var(--p); margin:0; font-size: 1.8rem; margin-bottom: 15px;">ZAFER RADARI</h2>
        
        <span class="section-title">KİŞİ LİSTESİNDE ARA</span>
        <input type="text" id="listSearch" placeholder="Gazeteci/Kanal Bul..." onkeyup="filterList()">
        
        <div id="u-list" style="margin: 15px 0; max-height: 35vh; overflow-y: auto; padding-right: 5px;">
            {CHECKS_HTML}
        </div>
        
        <div style="display:flex; gap:10px;">
            <button class="btn-d" onclick="setAll(true)">Tümünü Seç</button>
            <button class="btn-d" onclick="setAll(false)">Temizle</button>
        </div>
        
        <button class="btn-p" style="margin-top:20px; padding: 15px;" onclick="run()">HABER BÜLTENİNİ HAZIRLA</button>
        
        <hr style="opacity:0.2; margin: 25px 0; border-color: var(--border);">
        
        <button class="btn-d" style="background:#1f6feb; color:white; border:none;" onclick="toggleSpecial()">🔍 ÖZEL VİDEO ANALİZİ</button>
        <div id="specialSearchArea">
            <input type="text" id="src" placeholder="Örn: Celal Şengör Son Video">
            <button class="btn-s" onclick="search()">ŞİMDİ ARA VE ANALİZ ET</button>
        </div>
        
        <button class="btn-d" style="margin-top: 15px;" onclick="toggleAbout()">Hakkımızda</button>
    </div>

    <div id="main">
        <div id="progress-container">
            <div id="p-text">Hedefler taranıyor...</div>
            <div class="progress-bg"><div class="progress-bar" id="p-bar"></div></div>
        </div>
        <div id="box">
            <div style="text-align:center; margin-top:15vh; opacity:0.4;">
                <h2 style="font-size: 2rem;">Radar Beklemede</h2>
                <p style="font-size: 1.1rem;">Menüden seçim yapıp Haber Bültenini Hazırla butonuna basın.</p>
            </div>
        </div>
    </div>

    <div id="aboutModal">
        <div class="modal-content">
            <h3 class="modal-title">Hakkımızda</h3>
            <p style="color: var(--t); font-size: 1.05rem; line-height: 1.6; margin: 20px 0;">
                Bu site, YouTube'daki güncel haberleri ve yorumları sizin için izler, birbiriyle birleştirir ve tek bir "Gazete Özeti" halinde önünüze sunar. <b>HZafer</b> tarafından geliştirilmiştir.
            </p>
            <button class="btn-d" style="background: var(--bg); border: 2px solid var(--border);" onclick="toggleAbout()">Kapat</button>
        </div>
    </div>

    <script>
        function toggleTheme() { document.body.classList.toggle('dark'); }
        function toggleMenu() { 
            if (window.innerWidth <= 768) { document.getElementById('side').classList.toggle('mobile-open'); }
            else { document.getElementById('side').classList.toggle('closed'); document.getElementById('main').classList.toggle('expanded'); }
        }
        function autoCloseMenu() { if (window.innerWidth <= 768) { document.getElementById('side').classList.remove('mobile-open'); } }
        function toggleAbout() { const modal = document.getElementById('aboutModal'); modal.style.display = modal.style.display === 'flex' ? 'none' : 'flex'; }
        function toggleSpecial() { const area = document.getElementById('specialSearchArea'); area.style.display = area.style.display === 'block' ? 'none' : 'block'; }
        
        function filterList() { 
            const val = document.getElementById('listSearch').value.toLowerCase(); 
            document.querySelectorAll('.item').forEach(el => { 
                el.style.display = el.getAttribute('data-name').includes(val) ? 'flex' : 'none'; 
            }); 
        }
        
        function setAll(v) { document.querySelectorAll('.ch').forEach(c => c.checked = v); }
        
        async function search() { const val = document.getElementById('src').value; if(!val) return; autoCloseMenu(); api({ q: val }); }
        async function run() { const ids = Array.from(document.querySelectorAll('.ch:checked')).map(c => c.value); if(ids.length === 0) return alert("Lütfen en az bir kişi seçin!"); autoCloseMenu(); api({ ids: ids }); }

        async function api(body) {
            const box = document.getElementById('box');
            const pContainer = document.getElementById('progress-container');
            const pBar = document.getElementById('p-bar');
            const pText = document.getElementById('p-text');
            
            box.innerHTML = "";
            pContainer.style.display = "block";
            pBar.style.width = "0%";
            pBar.style.background = "var(--p)";
            pText.innerText = "Bağlantı kuruluyor...";
            
            try {
                const response = await fetch('/api/analyze', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
                const reader = response.body.getReader();
                const decoder = new TextDecoder("utf-8");
                let completed = 0; let total = 0; let buffer = ""; 

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, {stream: true});
                    const lines = buffer.split('\\n');
                    buffer = lines.pop(); 

                    for (let line of lines) {
                        if (!line.trim()) continue;
                        try {
                            const data = JSON.parse(line);
                            if (data.type === 'start') {
                                total = data.total; 
                                if(total === 0) { pText.innerText = "Uygun video bulunamadı."; pBar.style.width = '100%'; }
                                else { pText.innerHTML = `🎯 <b>Toplam ${total} video kaynağı dinleniyor...</b>`; }
                            } 
                            else if (data.type === 'progress') {
                                completed = data.completed;
                                pBar.style.width = Math.round((completed / total) * 100) + '%';
                                pText.innerHTML = `🎯 <b>${completed} / ${total} video not edildi.</b><br>⏳ Son dinlenen: <span style="color:var(--muted)">${data.current_title}</span>`;
                            }
                            else if (data.type === 'synthesizing') {
                                pText.innerHTML = `🧠 <b>Tüm videolar dinlendi!</b><br>✨ Yapay Zeka şimdi olayları grupluyor ve "Günün Özetini" yazıyor...`;
                                pBar.style.background = "#1f6feb";
                            }
                            else if (data.type === 'result') {
                                pText.innerHTML = `✅ <b>Haber Bülteni Hazır!</b>`;
                                pBar.style.background = "var(--p)";
                                if (data.html) { box.innerHTML = data.html; }
                            }
                        } catch(err) { console.error("JSON Parse Hatası:", err); }
                    }
                }
                setTimeout(() => { pContainer.style.display = 'none'; }, 4000);
            } catch(e) { pText.innerText = "Bağlantı hatası oluştu."; console.error(e); }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    checks_html = "".join([f'<label class="item" data-name="{u["ad"].lower()}"><span class="item-text">{u["ad"]}</span><input type="checkbox" value="{u["id"]}" class="ch"><span class="checkmark"></span></label>' for u in UNLU_LISTESI])
    return FULL_HTML_TEMPLATE.replace("{CHECKS_HTML}", checks_html)

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
        
        toplanmis_notlar = []
        completed = 0
        
        # 2. VİDEOLARI TEK TEK OKU VE NOT AL (UI'a sadece progress bildir, html basma)
        for coro in asyncio.as_completed(tasks):
            res = await coro
            completed += 1
            toplanmis_notlar.append(f"KAYNAK ({res['name']}): {res['content']}")
            yield f"{json.dumps({'type': 'progress', 'completed': completed, 'current_title': res['title']})}\n"
            
        # 3. YZ'YA TÜM NOTLARI VERİP SENTEZLEME YAPTIR (Arayüze "Sentezleniyor" sinyali gönder)
        yield f"{json.dumps({'type': 'synthesizing'})}\n"
        
        sentez_prompt = f"""
        Aşağıda Türkiye'deki çeşitli gazetecilerin/kanalların son videolarından çıkarılmış notlar var.
        Senden istediğim bunları KİŞİLERE GÖRE DEĞİL, KONULARA (OLAYLARA) GÖRE BİRLEŞTİRMEN.

        Lütfen şu HTML formatını kullanarak bir "Günün Bülteni" hazırla:

        <div class='card'>
            <div class='card-header'><span class='badge' style='background:#1f6feb;'>GÜNDEM MADDESİ</span></div>
            <h3 class='vid-title'>📌 [Ortak Konu / Olayın Adı]</h3>
            <div class='topic'>
                <p style='margin-top:0; color:var(--t); font-weight:bold; font-size:1.1rem;'>Olay Nedir?</p>
                <p style='color:var(--muted); font-size:0.95rem;'>[Olayın tarafsız, anlaşılır, kısa bir özeti]</p>
                <hr style='border:none; border-top:1px solid var(--border); margin:15px 0;'>
                <p style='margin-top:0; color:var(--t); font-weight:bold; font-size:1.1rem;'>Kim Ne Dedi?</p>
                <ul>
                    <li><b>[Gazeteci Adı]:</b> [Ne dediği/Yorumu]</li>
                    <li><b>[Diğer Gazeteci Adı]:</b> [Ne dediği/Yorumu]</li>
                </ul>
            </div>
        </div>

        Eğer aynı konudan birden fazla kişi bahsetmişse "Kim Ne Dedi" listesine hepsini alt alta ekle.
        Sadece 1 kişi bahsetmiş olsa bile formata uydur.
        Birden fazla konu varsa yukarıdaki <div class='card'> yapısını çoğaltarak tüm gündemleri dök.
        Markdown (```html) kullanma, sadece saf HTML kodu üret.

        İŞTE NOTLAR:
        {" ".join(toplanmis_notlar)}
        """

        try:
            final_res = await asyncio.to_thread(client.models.generate_content, model='gemini-2.5-flash', contents=sentez_prompt)
            final_html = final_res.text.replace('```html', '').replace('```', '').strip()
            
            # 4. SONUCU EKRANA BAS
            yield f"{json.dumps({'type': 'result', 'html': final_html})}\n"
        except Exception as e:
            err_html = f"<div class='card' style='border-color:red;'><h3 class='vid-title' style='color:red;'>Hata Oluştu</h3><p>Sentezleme sırasında hata yaşandı: {str(e)}</p></div>"
            yield f"{json.dumps({'type': 'result', 'html': err_html})}\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
