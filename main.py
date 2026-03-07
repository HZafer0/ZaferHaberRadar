import uvicorn
import yt_dlp
import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from typing import List
from youtube_transcript_api import YouTubeTranscriptApi

# ==========================================
# 🔐 5'Lİ API KEY SİSTEMİ
# ==========================================
KEYS_STRING = os.environ.get("GEMINI_KEYS", "KEY_1, KEY_2, KEY_3, KEY_4, KEY_5")
API_KEYS = [k.strip() for k in KEYS_STRING.split(",") if k.strip()]

if not API_KEYS:
    API_KEYS = ["DUMMY_KEY"]

aktif_key_sirasi = 0

# ==========================================
# 📺 KANAL LİSTESİ
# ==========================================
UNLU_LISTESI = [
    {"id": "altayli", "ad": "Fatih Altaylı", "url": "https://www.youtube.com/@fatihaltayli/videos"},
    {"id": "ozdemir", "ad": "Cüneyt Özdemir", "url": "https://www.youtube.com/@cuneytozdemir/streams"},
    {"id": "mengu", "ad": "Nevşin Mengü", "url": "https://www.youtube.com/@nevsinmengu/videos"},
    {"id": "140journos", "ad": "140journos", "url": "https://www.youtube.com/@140journos/videos"},
    {"id": "sozcu", "ad": "Sözcü TV", "url": "https://www.youtube.com/@sozcutelevizyonu/streams"},
    {"id": "t24", "ad": "T24 Haber", "url": "ytsearch5:T24 Haber son"},
    {"id": "veryansin", "ad": "Veryansın Tv", "url": "https://www.youtube.com/@VeryansinTv/videos"},
    {"id": "onlar", "ad": "Onlar TV", "url": "https://www.youtube.com/@OnlarTV/videos"},
    {"id": "cemgurdeniz", "ad": "Cem Gürdeniz", "url": "ytsearch3:Cem Gürdeniz Veryansın son"},
    {"id": "erhematay", "ad": "Erdem Atay", "url": "ytsearch3:Erdem Atay Veryansın son"},
    {"id": "serdarakinan", "ad": "Serdar Akinan", "url": "https://www.youtube.com/@serdarakinan/videos"}
]

# ==========================================
# 🧠 HAFIZA SİSTEMİ (RENDER UYUMLU)
# ==========================================
HAFIZA_DOSYASI = os.path.join(tempfile.gettempdir(), "hafiza.json")

def hafiza_yukle():
    if os.path.exists(HAFIZA_DOSYASI):
        try:
            with open(HAFIZA_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def hafiza_kaydet(hafiza_verisi):
    try:
        with open(HAFIZA_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(hafiza_verisi, f, ensure_ascii=False, indent=2)
    except:
        pass

ANALIZ_HAFIZASI = hafiza_yukle()

# ==========================================
# 📝 TRANSCRIPT ALMA (GELİŞTİRİLMİŞ)
# ==========================================
def video_metnini_al(vid):
    """
    Önce Türkçe transcript dener, sonra İngilizce, 
    sonra otomatik oluşturulmuş altyazıları dener.
    """
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(vid)
        
        # 1. Önce manuel Türkçe
        try:
            transcript = transcript_list.find_manually_created_transcript(['tr']).fetch()
            metin = " ".join([t['text'] for t in transcript])
            return metin[:35000]
        except:
            pass
        
        # 2. Otomatik Türkçe
        try:
            transcript = transcript_list.find_generated_transcript(['tr']).fetch()
            metin = " ".join([t['text'] for t in transcript])
            return metin[:35000]
        except:
            pass
        
        # 3. Herhangi bir dil (ilk bulunan)
        try:
            for t in transcript_list:
                fetched = t.fetch()
                metin = " ".join([item['text'] for item in fetched])
                return metin[:35000]
        except:
            pass
            
    except Exception as e:
        print(f"Transcript hatası ({vid}): {e}")
    
    return None

# ==========================================
# 🎧 SES İNDİRME (SON ÇARE - GELİŞTİRİLMİŞ)
# ==========================================
def sesi_indir_ve_dinle(vid, key, prompt_metni):
    dosya_yolu = os.path.join(tempfile.gettempdir(), f"temp_audio_{vid}.m4a")
    try:
        # Birden fazla client stratejisi dene
        strategies = [
            {'extractor_args': {'youtube': {'client': ['ios']}}},
            {'extractor_args': {'youtube': {'client': ['android_embedded']}}},
            {'extractor_args': {'youtube': {'client': ['web_embedded']}}},
        ]
        
        downloaded = False
        for strategy in strategies:
            try:
                opts = {
                    'format': 'bestaudio[filesize<25M]/bestaudio/best',
                    'outtmpl': dosya_yolu,
                    'quiet': True,
                    'nocheckcertificate': True,
                    'noplaylist': True,
                    **strategy
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([f"https://www.youtube.com/watch?v={vid}"])
                if os.path.exists(dosya_yolu):
                    downloaded = True
                    break
            except Exception as strat_e:
                print(f"Strateji başarısız: {strat_e}")
                continue
        
        if not downloaded:
            raise Exception("Tüm indirme stratejileri başarısız oldu.")

        client = genai.Client(api_key=key)
        audio_file = client.files.upload(file=dosya_yolu)
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',  
            contents=[prompt_metni, audio_file]
        )
        
        if os.path.exists(dosya_yolu):
            os.remove(dosya_yolu)
        try:
            client.files.delete(name=audio_file.name)
        except:
            pass
            
        return response.text.strip()
    except Exception as e:
        if os.path.exists(dosya_yolu):
            os.remove(dosya_yolu)
        raise e

# ==========================================
# 🤖 GÜVENLİ YAPAY ZEKA MOTORU
# ==========================================
async def guvenli_yapay_zeka_istegi(prompt_metni, vid=None, ses_dinle=False):
    global aktif_key_sirasi
    toplam_key = len(API_KEYS)
    deneme_sayisi = 0
    
    while deneme_sayisi < toplam_key:
        mevcut_key = API_KEYS[aktif_key_sirasi]
        try:
            if ses_dinle and vid:
                res_text = await asyncio.to_thread(sesi_indir_ve_dinle, vid, mevcut_key, prompt_metni)
                await asyncio.sleep(3)
                return res_text
            else:
                temp_client = genai.Client(api_key=mevcut_key)
                res = await asyncio.to_thread(
                    temp_client.models.generate_content,
                    model='gemini-2.5-flash',  
                    contents=prompt_metni
                )
                await asyncio.sleep(2)
                return res.text.strip()
        except Exception as e:
            err_str = str(e).lower()
            print(f"Uyarı: Key {aktif_key_sirasi} hatası: {e}")
            
            # Kota bittiyse sonraki key'e geç
            if "quota" in err_str or "429" in err_str or "rate" in err_str:
                aktif_key_sirasi = (aktif_key_sirasi + 1) % toplam_key
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(3)
            
            deneme_sayisi += 1
            
    return "⚠️ Sistem yoğunluğu nedeniyle bu video işlenemedi."

# ==========================================
# 📡 VİDEO LİSTESİ ÇEKME (GELİŞTİRİLMİŞ)
# ==========================================
def get_recent_vids(query, count=3):
    now = datetime.now()
    limit_ts = (now - timedelta(hours=36)).timestamp()
    limit_date_str = (now - timedelta(hours=36)).strftime('%Y%m%d')
    
    # Birden fazla strateji dene
    strategies = [
        {'extractor_args': {'youtube': {'client': ['ios']}}},
        {'extractor_args': {'youtube': {'client': ['android']}}},
        {'extractor_args': {'youtube': {'client': ['web']}}},
    ]
    
    for strategy in strategies:
        try:
            opts = {
                'extract_flat': True,
                'playlist_end': 8,  # Daha fazla video tara
                'quiet': True,
                'ignoreerrors': True,
                'socket_timeout': 20,
                **strategy
            }
            search = query if ("youtube.com" in query or "youtu.be" in query) else f"ytsearch5:{query}"
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(search, download=False)
                vids = []
                
                if res and 'entries' in res:
                    for entry in res['entries']:
                        if not entry:
                            continue
                        if len(vids) >= count:
                            break
                        
                        vid_id = entry.get('id')
                        title = entry.get('title', 'Video')
                        ts = entry.get('timestamp')
                        upload_date = entry.get('upload_date')
                        
                        if ts and ts >= limit_ts:
                            vids.append((vid_id, title))
                        elif upload_date and upload_date >= limit_date_str:
                            vids.append((vid_id, title))
                        elif not ts and not upload_date:
                            # Tarih bilgisi yoksa ekle (yayınlar için)
                            vids.append((vid_id, title))
                
                if vids:
                    return vids
                    
        except Exception as e:
            print(f"Video çekme stratejisi başarısız: {e}")
            continue
    
    return []

# ==========================================
# 🎯 VİDEO ÖZET PROMPT (GELİŞTİRİLMİŞ)
# ==========================================
def ozetleme_promptu_olustur(name, kaynak="altyazi"):
    return f"""Sen bir haber analisti asistanısın.

KİŞİ: {name}
KAYNAK: Bu videonun {kaynak} metni sana verilmiştir.

GÖREVİN:
Bu kişinin videosunda hangi güncel haber/olay konularından bahsettiğini ve her konu hakkında ne düşündüğünü çıkar.

ÇIKTI FORMATI (kesinlikle bu formatta yaz):
KONU: [Konu başlığı]
YORUM: {name} bu konuda [yorumu/görüşü] dedi.

---
KONU: [Konu başlığı 2]
YORUM: {name} bu konuda [yorumu/görüşü] dedi.

KURALLAR:
- Sadece videoda gerçekten bahsedilen konuları yaz
- Kişinin ağzından çıkmayan hiçbir şeyi uydurma
- En az 3, en fazla 7 konu çıkar
- Her yorumu 1-3 cümleyle özetle
- Tarih/saat bilgisi ekleme
- Türkçe yaz"""

# ==========================================
# 🔄 VİDEO İŞLEME
# ==========================================
async def process_video(name, vid, vtitle, sem):
    if vid in ANALIZ_HAFIZASI:
        return {"name": name, "vid": vid, "title": vtitle, "content": ANALIZ_HAFIZASI[vid]}

    async with sem:
        konusma_metni = await asyncio.to_thread(video_metnini_al, vid)
        
        if konusma_metni:
            prompt = ozetleme_promptu_olustur(name, "altyazı") + f"\n\nALTYAZI METNİ:\n{konusma_metni}"
            text_content = await guvenli_yapay_zeka_istegi(prompt, ses_dinle=False)
        else:
            print(f"⚠️ {vid} için altyazı bulunamadı, ses deneniyor...")
            prompt = ozetleme_promptu_olustur(name, "ses") + "\n\nGÖREV: Ekteki ses dosyasını DİNLE ve analiz et."
            text_content = await guvenli_yapay_zeka_istegi(prompt, vid=vid, ses_dinle=True)
        
        if "⚠️ Sistem yoğunluğu" not in text_content:
            ANALIZ_HAFIZASI[vid] = text_content
            hafiza_kaydet(ANALIZ_HAFIZASI)
            
        return {"name": name, "vid": vid, "title": vtitle, "content": text_content}

# ==========================================
# 🧩 SENTEZLEYİCİ PROMPT (GELİŞTİRİLMİŞ)
# ==========================================
def sentez_promptu_olustur(isimler_metni, toplanmis_notlar):
    return f"""Sen Türkiye'nin en iyi haber editörüsün.

Aşağıda şu kişilerin son videolarından çıkarılmış özetler var: {isimler_metni}

GÖREVİN: Bu notları ORTAK GÜNDEM KONULARINA göre grupla ve düzenli bir haber bülteni hazırla.

ÖRNEK - Aynı konudan bahsedenler bir kartda toplanmalı:
Eğer hem Fatih Altaylı hem Cüneyt Özdemir "ekonomi krizi"nden bahsettiyse → tek kartta iki yorum yan yana.
Eğer sadece biri bir konudan bahsettiyse → yine de o konu için kart aç.

KESİN YASAKLAR:
1. Tarih/saat bilgisi ekleme
2. Listede olmayan kişilerin adını kullanma (sadece: {isimler_metni})
3. Uydurma bilgi ekleme — sadece verilen notlardaki bilgileri kullan
4. Markdown kullanma (**, ##, * vs. yasak)

ÇIKTI: Sadece saf HTML ver, başka hiçbir şey yazma.

HTML FORMATI (her konu için bir kart):

<div class='card'>
    <div class='card-header'><span class='badge'>GÜNDEM</span></div>
    <h3 class='vid-title'>📌 [Konu Başlığı]</h3>
    <div class='topic'>
        <p style='margin-top:0; font-weight:bold;'>Olay Nedir?</p>
        <p style='color:var(--muted);'>[2-3 cümlelik özet]</p>
        <hr>
        <p style='font-weight:bold;'>Kim Ne Dedi?</p>
        <ul>
            <li><b>[Kişi Adı]:</b> [Görüşü 1-2 cümle]</li>
            <li><b>[Kişi Adı 2]:</b> [Görüşü 1-2 cümle]</li>
        </ul>
    </div>
</div>

İŞTE TOPLANAN NOTLAR:
{chr(10).join(toplanmis_notlar)}"""

# ==========================================
# 🚀 FASTAPI UYGULAMASI
# ==========================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class AnalizRequest(BaseModel):
    ids: List[str] = []

class SearchRequest(BaseModel):
    q: str

# ==========================================
# 🖥️ HTML ARAYÜZ
# ==========================================
FULL_HTML_TEMPLATE = """
<!DOCTYPE html>
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
        body { font-family: 'Segoe UI', system-ui, sans-serif; margin:0; background: var(--bg); color: var(--t); display: flex; transition: background 0.3s, color 0.3s; overflow-x: hidden; min-height: 100vh; }
        #side { width: 320px; height: 100vh; background: var(--c); border-right: 1px solid var(--border); position: fixed; padding: 70px 20px 25px 20px; overflow-y: auto; z-index: 100; box-shadow: 2px 0 10px rgba(0,0,0,0.05); }
        #main { margin-left: 320px; padding: 70px 40px 40px 40px; flex: 1; max-width: 1100px; }
        @media (max-width: 768px) {
            #side { transform: translateX(-100%); width: 280px; transition: 0.3s; }
            #side.mobile-open { transform: translateX(0); }
            #main { margin-left: 0; padding: 70px 15px 20px 15px; width: 100%; }
            .top-btn { top: 10px; width: 40px; height: 40px; font-size: 1.2rem; }
            .menu-toggle { left: 10px; display: flex !important; }
        }
        .top-btn { position: fixed; top: 15px; width: 45px; height: 45px; border-radius: 12px; background: var(--c); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; z-index: 1000; cursor: pointer; color: var(--t); }
        .menu-toggle { left: 15px; display: none; }
        .theme-toggle { right: 15px; }
        .card { background: var(--c); border-radius: 16px; padding: 25px; margin-bottom: 25px; border: 1px solid var(--border); border-left: 5px solid var(--p); }
        .card-header { margin-bottom: 15px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
        .badge { background: var(--p); color: white; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }
        .vid-title { margin: 10px 0; font-size: 1.2rem; color: var(--p); }
        .topic { background: rgba(128,128,128,0.05); border-radius: 8px; padding: 20px; margin-top: 15px; border: 1px solid var(--border); }
        .topic ul { margin: 15px 0 0 0; padding-left: 0; }
        .topic li { margin-bottom: 10px; padding: 10px; background: var(--bg); border-radius: 8px; list-style: none; border-left: 3px solid var(--border); }
        .topic b { color: var(--p); }
        button { width: 100%; padding: 12px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; margin-bottom: 8px; color: white; }
        .btn-p { background: linear-gradient(135deg, #ff4757, #ff6b81); }
        .btn-d { background: var(--bg); border: 1px solid var(--border); color: var(--t); }
        .item { padding: 12px 10px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; cursor: pointer; border-radius: 8px; }
        .item input { position: absolute; opacity: 0; cursor: pointer; height: 0; width: 0; }
        .checkmark { height: 22px; width: 22px; background-color: var(--bg); border: 2px solid var(--border); border-radius: 6px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .item input:checked ~ .checkmark { background-color: var(--p); border-color: var(--p); }
        .checkmark:after { content: ""; display: none; width: 5px; height: 10px; border: solid white; border-width: 0 2px 2px 0; transform: rotate(45deg); margin-bottom: 2px; }
        .item input:checked ~ .checkmark:after { display: block; }
        #progress-container { display: none; margin-bottom: 30px; background: var(--c); padding: 20px; border-radius: 12px; border: 1px solid var(--border); }
        .progress-bg { background: var(--border); height: 8px; border-radius: 10px; overflow: hidden; margin-top: 15px; }
        .progress-bar { width: 0%; height: 100%; background: var(--p); transition: width 0.4s ease; }
        .error-note { background: rgba(255,71,87,0.1); border: 1px solid var(--p); border-radius: 8px; padding: 10px; margin-top: 10px; font-size: 0.85rem; color: var(--p); }
    </style>
</head>
<body class="dark">
    <button class="top-btn menu-toggle" onclick="document.getElementById('side').classList.toggle('mobile-open')">☰</button>
    <button class="top-btn theme-toggle" onclick="document.body.classList.toggle('dark')">🌓</button>

    <div id="side">
        <h2 style="color:var(--p); font-size: 1.8rem; margin-bottom: 15px;">ZAFER RADARI</h2>
        <div id="u-list" style="margin: 15px 0; max-height: 40vh; overflow-y: auto;">
            {CHECKS_HTML}
        </div>
        
        <div style="display:flex; gap:10px;">
            <button class="btn-d" onclick="document.querySelectorAll('.ch').forEach(c => c.checked = true)">Tümünü Seç</button>
            <button class="btn-d" onclick="document.querySelectorAll('.ch').forEach(c => c.checked = false)">Temizle</button>
        </div>
        
        <button class="btn-p" style="margin-top:20px; margin-bottom:15px; padding: 15px;" onclick="run()">HABER BÜLTENİNİ HAZIRLA</button>
        
        <button class="btn-d" style="background:#1f6feb; color:white; border:none; margin-bottom: 15px;" onclick="toggleSpecial()">🔍 ÖZEL VİDEO ANALİZİ</button>
        
        <div id="specialSearchArea" style="display:none; margin-bottom: 15px; padding:15px; background:var(--bg); border:1px solid var(--border); border-radius:8px;">
            <input type="text" id="src" placeholder="YouTube Linki veya Kelime" style="width:100%; padding:10px; margin-bottom:10px; border-radius:5px; border:1px solid var(--border); background:var(--c); color:var(--t); outline:none;">
            <button style="background:#238636; width:100%; padding:10px; color:white; border:none; border-radius:5px; cursor:pointer;" onclick="searchSpecial()">ŞİMDİ ARA VE ANALİZ ET</button>
        </div>

        <button class="btn-d" onclick="alert('ZAFER RADARI v4.0\\nGeliştirilmiş YouTube & AI Sürümü')">HAKKINDA</button>
    </div>

    <div id="main">
        <div id="progress-container">
            <div id="p-text" style="font-weight:bold;">Analiz Başlıyor...</div>
            <div class="progress-bg"><div class="progress-bar" id="p-bar"></div></div>
        </div>
        <div id="box">
            <div style="text-align:center; margin-top:15vh; opacity:0.4;">
                <h2 style="font-size: 2rem;">Radar Hazır</h2>
                <p>Kişileri seçip bülteni hazırlayın veya Özel Analiz yapın.</p>
            </div>
        </div>
    </div>

    <script>
        function toggleSpecial() {
            const area = document.getElementById('specialSearchArea');
            area.style.display = area.style.display === 'block' ? 'none' : 'block';
        }

        async function searchSpecial() {
            const q = document.getElementById('src').value;
            if(!q) return alert("Lütfen bir link veya kelime girin!");
            if (window.innerWidth <= 768) document.getElementById('side').classList.remove('mobile-open');
            
            const box = document.getElementById('box');
            const pContainer = document.getElementById('progress-container');
            const pBar = document.getElementById('p-bar');
            const pText = document.getElementById('p-text');
            
            box.innerHTML = "";
            pContainer.style.display = "block"; pBar.style.width = "50%";
            pText.innerHTML = `🔍 <b>Özel analiz yapılıyor...</b>`;
            
            try {
                const response = await fetch('/api/search', { 
                    method: 'POST', 
                    headers: {'Content-Type': 'application/json'}, 
                    body: JSON.stringify({q: q}) 
                });
                const data = await response.json();
                pBar.style.width = "100%";
                pText.innerHTML = `✅ <b>Analiz tamamlandı!</b>`;
                box.innerHTML = data.html;
                setTimeout(() => { pContainer.style.display = 'none'; }, 3000);
            } catch(e) { 
                pText.innerText = "Hata oluştu: " + e.message;
            }
        }

        async function run() { 
            const ids = Array.from(document.querySelectorAll('.ch:checked')).map(c => c.value); 
            if(ids.length === 0) return alert("Kişi seçin!"); 
            if (window.innerWidth <= 768) document.getElementById('side').classList.remove('mobile-open');
            
            const box = document.getElementById('box');
            const pContainer = document.getElementById('progress-container');
            const pBar = document.getElementById('p-bar');
            const pText = document.getElementById('p-text');
            
            box.innerHTML = "";
            pContainer.style.display = "block"; pBar.style.width = "0%";
            pText.innerText = "Videolar aranıyor...";
            
            try {
                const response = await fetch('/api/analyze', { 
                    method: 'POST', 
                    headers: {'Content-Type': 'application/json'}, 
                    body: JSON.stringify({ids: ids}) 
                });
                const reader = response.body.getReader();
                const decoder = new TextDecoder("utf-8");
                let completed = 0, total = 0, buffer = "";

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
                                pText.innerHTML = `🎯 <b>${total} video bulundu, işleniyor...</b>`;
                            } 
                            else if (data.type === 'progress') {
                                completed = data.completed;
                                pBar.style.width = Math.round((completed / total) * 100) + '%';
                                pText.innerHTML = `⚡ <b>${completed}/${total}</b> — <span style="color:var(--muted)">${data.current_title}</span>`;
                            }
                            else if (data.type === 'synthesizing') {
                                pText.innerHTML = `🧠 <b>Bülten yazılıyor...</b>`;
                                pBar.style.width = "95%";
                            }
                            else if (data.type === 'result') {
                                pBar.style.width = "100%";
                                pText.innerHTML = `✅ <b>Hazır!</b>`;
                                if (data.html) box.innerHTML = data.html;
                                setTimeout(() => { pContainer.style.display = 'none'; }, 3000);
                            }
                            else if (data.type === 'error') {
                                pText.innerHTML = `❌ <b>Hata:</b> ${data.message}`;
                            }
                        } catch(err) {}
                    }
                }
            } catch(e) { 
                pText.innerText = "Bağlantı hatası: " + e.message; 
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    checks_html = "".join([
        f'<label class="item"><span class="item-text">{u["ad"]}</span><input type="checkbox" value="{u["id"]}" class="ch"><span class="checkmark"></span></label>'
        for u in UNLU_LISTESI
    ])
    return FULL_HTML_TEMPLATE.replace("{CHECKS_HTML}", checks_html)

@app.post("/api/search")
async def special_search(req: SearchRequest):
    vids = await asyncio.to_thread(get_recent_vids, req.q, 1)
    if not vids:
        return {"html": "<div class='card'><h3 style='color:red;'>❌ Video bulunamadı!</h3><p>YouTube engeli veya geçersiz link olabilir. Direkt video linki deneyin.</p></div>"}
    
    vid, title = vids[0]
    konusma_metni = await asyncio.to_thread(video_metnini_al, vid)
    
    kaynak = "altyazı" if konusma_metni else "ses"
    ortak_prompt = f"""Bu video "{title}" başlığına sahiptir.
İçinde konuşulanları ve gündem maddelerini detaylıca, madde madde özetle.
Kendi yorumunu katma. Türkçe yaz."""
    
    try:
        if konusma_metni:
            prompt = ortak_prompt + f"\n\nALTYAZI METNİ:\n{konusma_metni}"
            text_content = await guvenli_yapay_zeka_istegi(prompt, ses_dinle=False)
        else:
            prompt = ortak_prompt + "\n\nGÖREV: Ekteki ses dosyasını DİNLE ve detaylıca analiz et."
            text_content = await guvenli_yapay_zeka_istegi(prompt, vid=vid, ses_dinle=True)
            
        formatted_content = text_content.replace('\n', '<br>').replace('**', '').replace('##', '')
        
        html_cikti = f"""
        <div class='card' style='border-left-color: #1f6feb;'>
            <div class='card-header'>
                <span class='badge' style='background:#1f6feb;'>ÖZEL ANALİZ</span>
                <span style='font-size:0.8rem; color:var(--muted); margin-left:10px;'>Kaynak: {kaynak}</span>
            </div>
            <h3 class='vid-title'>{title}</h3>
            <div class='topic'>
                <p style='color:var(--t); line-height: 1.7;'>{formatted_content}</p>
            </div>
        </div>
        """
        return {"html": html_cikti}
    except Exception as e:
        return {"html": f"<div class='card'><h3 style='color:red;'>Analiz Hatası</h3><p>{str(e)}</p></div>"}


@app.post("/api/analyze")
async def analyze_videos(req: AnalizRequest):
    async def generate():
        vids_to_process = []
        secilen_isimler = []
        
        for uid in req.ids:
            user = next((u for u in UNLU_LISTESI if u["id"] == uid), None)
            if user:
                secilen_isimler.append(user["ad"])
                vids = await asyncio.to_thread(get_recent_vids, user["url"], 3)
                if vids:
                    for vid, title in vids:
                        vids_to_process.append({"name": user["ad"], "vid": vid, "title": title})
        
        if not vids_to_process:
            yield f"{json.dumps({'type': 'error', 'message': 'Hiç video bulunamadı. YouTube engeli olabilir.'})}\n"
            return

        aktif_video_sayisi = len(vids_to_process)
        yield f"{json.dumps({'type': 'start', 'total': aktif_video_sayisi})}\n"
        
        # Semaphore(2) → 2 video paralel işle, daha hızlı
        sem = asyncio.Semaphore(2)
        
        async def process_wrapper(v):
            return await process_video(v["name"], v["vid"], v["title"], sem)
            
        tasks = [process_wrapper(v) for v in vids_to_process]
        toplanmis_notlar = []
        completed = 0
        
        for coro in asyncio.as_completed(tasks):
            res = await coro
            completed += 1
            toplanmis_notlar.append(f"### {res['name']} - Video: {res['title']}\n{res['content']}")
            yield f"{json.dumps({'type': 'progress', 'completed': completed, 'current_title': res['title']})}\n"
                
        yield f"{json.dumps({'type': 'synthesizing'})}\n"
        
        isimler_metni = ", ".join(secilen_isimler)
        sentez_prompt = sentez_promptu_olustur(isimler_metni, toplanmis_notlar)

        try:
            final_text = await guvenli_yapay_zeka_istegi(sentez_prompt, ses_dinle=False)
            final_html = final_text.replace('```html', '').replace('```', '').strip()
            yield f"{json.dumps({'type': 'result', 'html': final_html})}\n"
        except Exception as e:
            err_html = f"<div class='card' style='border-color:red;'><h3 class='vid-title' style='color:red;'>Sentez Hatası</h3><p>{str(e)}</p></div>"
            yield f"{json.dumps({'type': 'result', 'html': err_html})}\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
