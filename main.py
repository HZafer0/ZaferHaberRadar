import uvicorn
import yt_dlp
import asyncio
import json
import os
import tempfile
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from youtube_transcript_api import YouTubeTranscriptApi

# ==========================================
# 🔐 GROQ API KEY SİSTEMİ
# ==========================================
KEYS_STRING = os.environ.get("GROQ_KEYS", "KEY_1,KEY_2,KEY_3,KEY_4,KEY_5")
API_KEYS = [k.strip() for k in KEYS_STRING.split(",") if k.strip() and not k.strip().startswith("KEY_")]

if not API_KEYS:
    API_KEYS = ["DUMMY_KEY"]

aktif_key_sirasi = 0

# ==========================================
# 📺 KANAL LİSTESİ
# ==========================================
UNLU_LISTESI = [
    {"id": "altayli",      "ad": "Fatih Altaylı",  "channel_id": "UCzs5_GtMFqh5ydRqSDMEMoA", "url": "https://www.youtube.com/@fatihaltayli/videos"},
    {"id": "ozdemir",      "ad": "Cüneyt Özdemir", "channel_id": "UCzDMBEXS5YiCEnFkbD7dCKg", "url": "https://www.youtube.com/@cuneytozdemir/videos"},
    {"id": "mengu",        "ad": "Nevşin Mengü",   "channel_id": "UCUOSmkF4FKoEp7wuXFXMsCQ", "url": "https://www.youtube.com/@nevsinmengu/videos"},
    {"id": "140journos",   "ad": "140journos",      "channel_id": "UCWNiE_-eFUdmPTuuk8xFd_Q", "url": "https://www.youtube.com/@140journos/videos"},
    {"id": "sozcu",        "ad": "Sözcü TV",        "channel_id": "UCMXvdBCXuQFQFMLWHaVBYyA", "url": "https://www.youtube.com/@sozcutelevizyonu/videos"},
    {"id": "t24",          "ad": "T24 Haber",       "channel_id": "UCpCxQ0BkUy6JrEhMvMi8mpQ", "url": "https://www.youtube.com/@t24habertv/videos"},
    {"id": "veryansin",    "ad": "Veryansın Tv",    "channel_id": "UCqvlQDcDkUbBhGjHXY4GZSA", "url": "https://www.youtube.com/@VeryansinTv/videos"},
    {"id": "onlar",        "ad": "Onlar TV",        "channel_id": "UCnHRjhBDK1L8FhE8XCRE_bQ", "url": "https://www.youtube.com/@OnlarTV/videos"},
    {"id": "cemgurdeniz",  "ad": "Cem Gürdeniz",    "channel_id": None,                         "url": "ytsearch5:Cem Gürdeniz"},
    {"id": "erhematay",    "ad": "Erdem Atay",      "channel_id": None,                         "url": "ytsearch5:Erdem Atay"},
    {"id": "serdarakinan", "ad": "Serdar Akinan",   "channel_id": "UCFLFbIKOekBH_8-mSUexBBA", "url": "https://www.youtube.com/@serdarakinan/videos"},
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
# 🗄️ ÖNBELLEK SİSTEMİ (Hazır bültenler)
# ==========================================
ONBELLEK_DOSYASI = os.path.join(tempfile.gettempdir(), "onbellek.json")
ONBELLEK = {}          # { "altayli,ozdemir": {"html": "...", "zaman": timestamp} }
GUNCELLEME_DURUMU = {} # { "altayli": "hazır" / "işleniyor" / "hata" }
ARKAPLAN_CALISIYOR = False

def onbellek_yukle():
    if os.path.exists(ONBELLEK_DOSYASI):
        try:
            with open(ONBELLEK_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def onbellek_kaydet():
    try:
        with open(ONBELLEK_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(ONBELLEK, f, ensure_ascii=False, indent=2)
    except: pass

ONBELLEK = onbellek_yukle()

# ==========================================
# 📝 TRANSCRIPT ALMA (YENİ API UYUMLU)
# ==========================================
def video_metnini_al(vid):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, FetchedTranscript
        # Yeni API (v0.6+): fetch() video_id keyword argümanı ister
        transcript = YouTubeTranscriptApi.fetch(video_id=vid, languages=['tr', 'en'])
        metin = " ".join([t.get('text', '') if isinstance(t, dict) else t.text for t in transcript])
        if metin.strip():
            return metin[:35000]
    except Exception as e1:
        print(f"Transcript yöntem-1 hatası ({vid}): {e1}")

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.list_transcripts(vid)
        for lang in ['tr', 'en']:
            try:
                t = transcript_list.find_transcript([lang]).fetch()
                metin = " ".join([x['text'] if isinstance(x, dict) else x.text for x in t])
                if metin.strip():
                    return metin[:35000]
            except:
                continue
        for t in transcript_list:
            try:
                fetched = t.fetch()
                metin = " ".join([x['text'] if isinstance(x, dict) else x.text for x in fetched])
                if metin.strip():
                    return metin[:35000]
            except:
                continue
    except Exception as e2:
        print(f"Transcript yöntem-2 hatası ({vid}): {e2}")
    except Exception as e2:
        print(f"Transcript yöntem-2 hatası ({vid}): {e2}")

    return None

# Aynı anda indirilen dosyaları takip et (dosya kilidi önleme)
_indirme_kilitleri = {}
_indirme_kilitleri_lock = asyncio.Lock()

# ==========================================
# 🎧 SES İNDİRME + GROQ WHISPER TRANSKRİPSYON
# ==========================================
def sesi_indir_ve_transkribe_et(vid):
    """Sesi indir, Groq Whisper ile yazıya çevir."""
    import uuid
    import glob as glob_mod
    benzersiz_id = uuid.uuid4().hex[:8]
    dosya_yolu = os.path.join(tempfile.gettempdir(), f"audio_{vid}_{benzersiz_id}.m4a")

    cookie_dosyasi = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
    cookie_opt = {'cookiefile': cookie_dosyasi} if os.path.exists(cookie_dosyasi) else {}

    strategies = [
        {'extractor_args': {'youtube': {'client': ['ios']}}},
        {'extractor_args': {'youtube': {'client': ['android']}}},
        {'extractor_args': {'youtube': {'client': ['web']}}},
    ]

    downloaded = False
    for strategy in strategies:
        try:
            opts = {
                'format': 'bestaudio[filesize<25M]/bestaudio/best',
                'outtmpl': dosya_yolu,
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'noplaylist': True,
                **cookie_opt,
                **strategy
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={vid}"])
            bulunan = glob_mod.glob(dosya_yolu.replace('.m4a', '.*'))
            if bulunan:
                dosya_yolu = bulunan[0]
                downloaded = True
                break
            elif os.path.exists(dosya_yolu):
                downloaded = True
                break
        except Exception as e:
            print(f"İndirme stratejisi başarısız: {e}")
            for f in glob_mod.glob(dosya_yolu.replace('.m4a', '.*')):
                try: os.remove(f)
                except: pass

    if not downloaded:
        raise Exception("Ses indirilemedi.")

    # Groq Whisper ile transkribe et
    key = API_KEYS[aktif_key_sirasi]
    try:
        with open(dosya_yolu, 'rb') as f:
            import httpx as httpx_mod
            response = httpx_mod.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data={"model": "whisper-large-v3", "language": "tr", "response_format": "text"},
                files={"file": (os.path.basename(dosya_yolu), f, "audio/m4a")},
                timeout=120
            )
        response.raise_for_status()
        return response.text.strip()
    finally:
        try: os.remove(dosya_yolu)
        except: pass

# Global API semaphore
_api_sem = None

def get_api_sem():
    global _api_sem
    if _api_sem is None:
        _api_sem = asyncio.Semaphore(1)
    return _api_sem

# ==========================================
# 🤖 GROQ LLM — METİN ÖZETLEME
# ==========================================
async def groq_llm_iste(prompt_metni):
    """Groq LLaMA ile metin özetleme — key rotasyonlu."""
    global aktif_key_sirasi
    toplam_key = len(API_KEYS)
    deneme_sayisi = 0

    async with get_api_sem():
        while deneme_sayisi < toplam_key * 2:
            key = API_KEYS[aktif_key_sirasi]
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [{"role": "user", "content": prompt_metni}],
                            "max_tokens": 4096,
                            "temperature": 0.3
                        }
                    )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                err_str = str(e).lower()
                print(f"Uyarı: Groq Key {aktif_key_sirasi} hatası: {e}")
                if "429" in err_str or "rate" in err_str or "quota" in err_str:
                    aktif_key_sirasi = (aktif_key_sirasi + 1) % toplam_key
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(5)
                deneme_sayisi += 1

    raise Exception("Tüm Groq key'leri denendi, limit aşıldı.")

# guvenli_yapay_zeka_istegi → artık Groq kullanıyor
async def guvenli_yapay_zeka_istegi(prompt_metni, vid=None, ses_dinle=False):
    if ses_dinle and vid:
        # Sesi indir → Whisper ile transkribe et → LLaMA ile özetle
        transkript = await asyncio.to_thread(sesi_indir_ve_transkribe_et, vid)
        tam_prompt = f"{prompt_metni}\n\nVİDEO TRANSKRİPTİ:\n{transkript[:30000]}"
        return await groq_llm_iste(tam_prompt)
    else:
        return await groq_llm_iste(prompt_metni)

# ==========================================
# 📡 VİDEO LİSTESİ ÇEKME
# ==========================================
def get_recent_vids_rss(channel_id, count=3):
    """YouTube RSS feed — bot engeli yok, hızlı, ücretsiz."""
    import urllib.request, xml.etree.ElementTree as ET
    from datetime import timezone

    now = datetime.now()
    limit_ts = (now - timedelta(hours=36)).timestamp()

    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()

        ns = {'atom': 'http://www.w3.org/2005/Atom',
              'yt': 'http://www.youtube.com/xml/schemas/2015'}
        root = ET.fromstring(xml_data)

        vids = []
        for entry in root.findall('atom:entry', ns):
            if len(vids) >= count:
                break
            vid_id_el = entry.find('yt:videoId', ns)
            title_el  = entry.find('atom:title', ns)
            pub_el    = entry.find('atom:published', ns)
            if vid_id_el is None or title_el is None:
                continue
            vid_id = vid_id_el.text
            title  = title_el.text or 'Video'
            if pub_el is not None:
                pub_ts = datetime.strptime(pub_el.text[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
                if pub_ts < limit_ts:
                    print(f"⏭️ RSS 36s dışında, duruldu: {title[:50]}")
                    break
                print(f"✅ RSS: {title[:50]}")
            vids.append((vid_id, title))
        return vids
    except Exception as e:
        print(f"RSS hatası ({channel_id}): {e}")
        return None  # None = hata → yt-dlp'ye geç

def get_recent_vids(query, count=3, channel_id=None):
    now = datetime.now()
    limit_ts = (now - timedelta(hours=36)).timestamp()
    limit_date_str = (now - timedelta(hours=36)).strftime('%Y%m%d')
    is_url = "youtube.com" in query or "youtu.be" in query

    # 1. channel_id varsa direkt RSS dene
    if channel_id:
        rss = get_recent_vids_rss(channel_id, count)
        if rss is not None:
            print(f"📡 RSS: {len(rss)} video bulundu")
            return rss

    # 2. RSS başarısız veya arama sorgusu → yt-dlp
    cookie_dosyasi = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
    cookie_opt = {'cookiefile': cookie_dosyasi} if os.path.exists(cookie_dosyasi) else {}
    search = query if is_url else f"ytsearch10:{query}"

    for strategy in [
        {'extractor_args': {'youtube': {'client': ['ios']}}},
        {'extractor_args': {'youtube': {'client': ['android']}}},
        {'extractor_args': {'youtube': {'client': ['web']}}},
    ]:
        try:
            opts = {'extract_flat': True, 'playlistend': 10, 'quiet': True,
                    'no_warnings': True, 'ignoreerrors': True, 'socket_timeout': 25,
                    **cookie_opt, **strategy}
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(search, download=False)
            if not res:
                continue
            entries = res.get('entries', [])
            if not entries and res.get('id'):
                entries = [res]
            flat = []
            for e in (entries or []):
                if not e: continue
                flat.extend(e['entries']) if e.get('entries') else flat.append(e)
            vids = []
            for entry in flat:
                if not entry or len(vids) >= count: break
                vid_id = entry.get('id')
                title  = entry.get('title', 'Video')
                if not vid_id or vid_id.startswith('ytsearch'): continue
                ts = entry.get('timestamp')
                ud = entry.get('upload_date')
                if ts:
                    if ts < limit_ts: break
                    vids.append((vid_id, title))
                elif ud:
                    if ud < limit_date_str: break
                    vids.append((vid_id, title))
                else:
                    vids.append((vid_id, title))
            if vids:
                return vids
        except Exception as e:
            print(f"yt-dlp başarısız: {e}")

    print(f"❌ Video bulunamadı: {query[:60]}")
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
async def baslik_turkce_cevir(baslik):
    """Video başlığı İngilizce ise Türkçeye çevirir."""
    import re
    # Türkçe karakter veya kelime varsa zaten Türkçe
    turkce_karakterler = re.search(r'[çğıöşüÇĞİÖŞÜ]', baslik)
    turkce_kelimeler = any(k in baslik.lower() for k in ['ve', 'ile', 'bir', 'bu', 'ne', 'da', 'de', 'için', 'haber', 'son', 'nasıl'])
    if turkce_karakterler or turkce_kelimeler:
        return baslik
    # İngilizce görünüyorsa çevir
    try:
        prompt = f'Bu YouTube video başlığını Türkçeye çevir, sadece çeviriyi yaz başka hiçbir şey ekleme: "{baslik}"'
        cevirilen = await guvenli_yapay_zeka_istegi(prompt)
        return cevirilen.strip('"').strip("'") if cevirilen else baslik
    except:
        return baslik

async def process_video(name, vid, vtitle, sem, queue=None):
    if vid in ANALIZ_HAFIZASI:
        return {"name": name, "vid": vid, "title": vtitle, "content": ANALIZ_HAFIZASI[vid]}

    async with sem:
        vtitle_tr = await baslik_turkce_cevir(vtitle)
        konusma_metni = await asyncio.to_thread(video_metnini_al, vid)
        
        try:
            if konusma_metni:
                # Altyazı bulundu — ara durum gönder
                if queue:
                    await queue.put({"type": "subprogress", "vid": vid, "title": vtitle_tr, "durum": f"📄 Altyazı okunuyor: {vtitle_tr[:50]}"})
                prompt = ozetleme_promptu_olustur(name, "altyazı") + f"\n\nALTYAZI METNİ:\n{konusma_metni}"
                text_content = await guvenli_yapay_zeka_istegi(prompt, ses_dinle=False)
            else:
                print(f"⚠️ {vid} için altyazı bulunamadı, ses deneniyor...")
                # Ses indirme başlıyor — kullanıcıya haber ver
                if queue:
                    await queue.put({"type": "subprogress", "vid": vid, "title": vtitle_tr, "durum": f"🎧 Ses indiriliyor: {vtitle_tr[:50]} (1-2 dk sürebilir)"})
                prompt = ozetleme_promptu_olustur(name, "ses") + "\n\nGÖREV: Ekteki ses dosyasını DİNLE ve analiz et."
                text_content = await guvenli_yapay_zeka_istegi(prompt, vid=vid, ses_dinle=True)
            
            ANALIZ_HAFIZASI[vid] = text_content
            hafiza_kaydet(ANALIZ_HAFIZASI)
            return {"name": name, "vid": vid, "title": vtitle_tr, "content": text_content}
        
        except Exception as e:
            hata_mesaji = f"[Bu video işlenemedi: {str(e)[:120]}]"
            return {"name": name, "vid": vid, "title": vtitle_tr, "content": hata_mesaji, "hata": True}

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
# 🔄 ARKA PLAN OTOMATİK GÜNCELLEME
# ==========================================
async def tek_kisi_isle(uid):
    """Tek bir kişinin videolarını çekip önbelleğe al."""
    user = next((u for u in UNLU_LISTESI if u["id"] == uid), None)
    if not user:
        return None

    GUNCELLEME_DURUMU[uid] = "işleniyor"
    try:
        vids = await asyncio.to_thread(get_recent_vids, user["url"], 3, user.get("channel_id"))
        if not vids:
            GUNCELLEME_DURUMU[uid] = "video_yok"
            return None

        sem = asyncio.Semaphore(1)
        notlar = []
        for vid, title in vids:
            res = await process_video(user["ad"], vid, title, sem)
            notlar.append(f"### {res['name']} - Video: {res['title']}\n{res['content']}")

        GUNCELLEME_DURUMU[uid] = "hazır"
        return {"uid": uid, "notlar": notlar, "ad": user["ad"]}
    except Exception as e:
        print(f"Arka plan hata ({uid}): {e}")
        GUNCELLEME_DURUMU[uid] = "hata"
        return None

async def arkaplan_guncelle():
    """Tüm kanalları arka planda işleyip önbellekler. Her 2 saatte tekrar çalışır."""
    global ARKAPLAN_CALISIYOR
    while True:
        ARKAPLAN_CALISIYOR = True
        print("🔄 Arka plan güncellemesi başladı...")

        try:
            # Her kişiyi sırayla işle (API kotasını korumak için)
            tum_notlar = {}
            for u in UNLU_LISTESI:
                sonuc = await tek_kisi_isle(u["id"])
                if sonuc:
                    tum_notlar[u["id"]] = sonuc
                await asyncio.sleep(5)  # Kişiler arası bekleme

            # Her kişi için tekli önbellek oluştur
            for uid, veri in tum_notlar.items():
                sentez = sentez_promptu_olustur(veri["ad"], veri["notlar"])
                try:
                    html = await guvenli_yapay_zeka_istegi(sentez)
                    html = html.replace('```html', '').replace('```', '').strip()
                    ONBELLEK[uid] = {
                        "html": html,
                        "notlar": veri["notlar"],
                        "zaman": datetime.now().isoformat(),
                        "ad": veri["ad"]
                    }
                    onbellek_kaydet()
                    print(f"✅ Önbellek güncellendi: {veri['ad']}")
                except Exception as e:
                    print(f"Sentez hatası ({uid}): {e}")

        except Exception as e:
            print(f"Arka plan genel hata: {e}")

        ARKAPLAN_CALISIYOR = False
        print("✅ Arka plan güncellemesi tamamlandı. 2 saat sonra tekrar çalışacak.")
        await asyncio.sleep(2 * 60 * 60)  # 2 saat bekle

@app.on_event("startup")
async def startup_event():
    """Uygulama başlarken arka plan güncellemeyi başlat."""
    asyncio.create_task(arkaplan_guncelle())
    print("🚀 Arka plan güncelleme görevi başlatıldı.")

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
        <h2 style="color:var(--p); font-size: 1.8rem; margin-bottom: 5px;">ZAFER RADARI</h2>
        <div id="radar-durum" style="font-size:0.78rem; color:var(--muted); margin-bottom:12px;">⏳ Durum yükleniyor...</div>

        <div id="u-list" style="margin: 15px 0; max-height: 38vh; overflow-y: auto;">
            {CHECKS_HTML}
        </div>
        
        <div style="display:flex; gap:10px; margin-bottom:10px;">
            <button class="btn-d" onclick="document.querySelectorAll('.ch').forEach(c => c.checked = true)">Tümünü Seç</button>
            <button class="btn-d" onclick="document.querySelectorAll('.ch').forEach(c => c.checked = false)">Temizle</button>
        </div>

        <button class="btn-p" style="margin-bottom:8px; padding: 15px;" onclick="anindaGoster()">⚡ ANİNDA GÖSTER</button>
        <div style="font-size:0.75rem; color:var(--muted); text-align:center; margin-bottom:12px;">Önbellekteki hazır verileri gösterir</div>

        <button class="btn-d" style="margin-bottom:8px; background:#2d333b; color:#cdd9e5;" onclick="run()">🔄 YENİDEN ANALİZ ET</button>
        <div style="font-size:0.75rem; color:var(--muted); text-align:center; margin-bottom:15px;">Yeni video varsa çekip özetler</div>
        
        <button class="btn-d" style="background:#1f6feb; color:white; border:none; margin-bottom: 15px;" onclick="toggleSpecial()">🔍 ÖZEL VİDEO ANALİZİ</button>
        
        <div id="specialSearchArea" style="display:none; margin-bottom: 15px; padding:15px; background:var(--bg); border:1px solid var(--border); border-radius:8px;">
            <input type="text" id="src" placeholder="YouTube Linki veya Kelime" style="width:100%; padding:10px; margin-bottom:10px; border-radius:5px; border:1px solid var(--border); background:var(--c); color:var(--t); outline:none;">
            <button style="background:#238636; width:100%; padding:10px; color:white; border:none; border-radius:5px; cursor:pointer;" onclick="searchSpecial()">ŞİMDİ ARA VE ANALİZ ET</button>
        </div>

        <button class="btn-d" onclick="alert('ZAFER RADARI v4.1\\nÖnbellekli Sürüm')">HAKKINDA</button>
    </div>

    <div id="main">
        <div id="progress-container">
            <div id="p-text" style="font-weight:bold;">Analiz Başlıyor...</div>
            <div class="progress-bg"><div class="progress-bar" id="p-bar"></div></div>
        </div>
        <div id="box">
            <div style="text-align:center; margin-top:12vh; opacity:0.5;">
                <div style="font-size:3rem; margin-bottom:15px;">⚡</div>
                <h2 style="font-size: 1.8rem; margin-bottom:10px;">Radar Hazır</h2>
                <p style="max-width:400px; margin:0 auto; line-height:1.6;">Arka planda tüm kanallar sürekli izleniyor.<br>
                <b style="color:var(--p);">ANİNDA GÖSTER</b> butonuna bas, hazır bülteni gör.</p>
            </div>
        </div>
    </div>

    <script>
        // Sayfa açılınca durum kontrol et
        async function durumGuncelle() {
            try {
                const res = await fetch('/api/durum');
                const data = await res.json();
                const onbellekSayisi = Object.keys(data.onbellekte || {}).length;
                const toplam = {TOPLAM_KANAL};
                const durum = document.getElementById('radar-durum');
                if (data.calisiyor) {
                    durum.innerHTML = `🔄 Arka plan taraması çalışıyor...`;
                } else if (onbellekSayisi > 0) {
                    durum.innerHTML = `✅ <b>${onbellekSayisi}/${toplam}</b> kanal hazır — anında göster!`;
                    durum.style.color = '#3fb950';
                } else {
                    durum.innerHTML = `⏳ Henüz önbellek yok, ilk tarama bekleniyor...`;
                }
                // Checkbox'lara hazır badge ekle
                document.querySelectorAll('.ch').forEach(cb => {
                    const label = cb.closest('label');
                    if (!label) return;
                    const badge = label.querySelector('.hazir-badge');
                    if (data.onbellekte && data.onbellekte.includes(cb.value)) {
                        if (!badge) {
                            const b = document.createElement('span');
                            b.className = 'hazir-badge';
                            b.textContent = '✅';
                            b.style.cssText = 'font-size:0.75rem; margin-left:5px;';
                            label.querySelector('.item-text').appendChild(b);
                        }
                    }
                });
            } catch(e) {}
        }
        durumGuncelle();
        setInterval(durumGuncelle, 30000); // Her 30 sn güncelle

        async function anindaGoster() {
            const ids = Array.from(document.querySelectorAll('.ch:checked')).map(c => c.value);
            if (ids.length === 0) return alert("Kişi seçin!");
            if (window.innerWidth <= 768) document.getElementById('side').classList.remove('mobile-open');

            const box = document.getElementById('box');
            const pContainer = document.getElementById('progress-container');
            const pBar = document.getElementById('p-bar');
            const pText = document.getElementById('p-text');

            box.innerHTML = "";
            pContainer.style.display = "block";
            pBar.style.width = "30%";
            pText.innerHTML = `⚡ <b>Önbellekten yükleniyor...</b>`;

            try {
                const response = await fetch('/api/aninda', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ids})
                });
                const data = await response.json();
                pBar.style.width = "100%";
                if (data.bos) {
                    pText.innerHTML = `⚠️ Seçilen kişiler için önbellekte veri yok. <b>YENİDEN ANALİZ ET</b> butonuna bas.`;
                } else {
                    pText.innerHTML = `✅ <b>Hazır!</b>`;
                    box.innerHTML = data.html;
                    setTimeout(() => { pContainer.style.display = 'none'; }, 2000);
                }
            } catch(e) {
                pText.innerText = "Hata: " + e.message;
            }
        }

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

        // Önbellek durumunu göster
        const onbellekKeys = {ONBELLEK_KEYS};
        function onbellekGoster() {
            onbellekKeys.forEach(uid => {
                const el = document.getElementById('durum-' + uid);
                if (el) el.innerHTML = '✅';
            });
        }
        onbellekGoster();

        // Her 3 dakikada önbellek durumunu güncelle
        async function durumGuncelle() {
            try {
                const r = await fetch('/api/durum');
                const d = await r.json();
                d.onbellekte.forEach(uid => {
                    const el = document.getElementById('durum-' + uid);
                    if (el) el.innerHTML = '✅';
                });
                Object.entries(d.durumlar).forEach(([uid, durum]) => {
                    const el = document.getElementById('durum-' + uid);
                    if (!el) return;
                    if (durum === 'işleniyor') el.innerHTML = '<span style="font-size:0.7rem;">⏳</span>';
                    else if (durum === 'hata') el.innerHTML = '<span style="font-size:0.7rem; color:#fc8181;">❌</span>';
                    else if (durum === 'video_yok') el.innerHTML = '<span style="background:rgba(255,255,255,0.06); color:#555; font-size:0.65rem; padding:1px 6px; border-radius:10px; margin-left:4px;">yeni yok</span>';
                });
            } catch(e) {}
        }
        setInterval(durumGuncelle, 3 * 60 * 1000);

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
                            if (data.type === 'scanning') {
                                // Kişi için video aranıyor
                                const el = document.getElementById('durum-' + data.uid);
                                if (el) el.innerHTML = '<span style="color:#888; font-size:0.7rem;">🔍</span>';
                            }
                            else if (data.type === 'vid_count') {
                                // Kişi için kaç video bulundu
                                const el = document.getElementById('durum-' + data.uid);
                                if (el) {
                                    if (data.count === 0) {
                                        el.innerHTML = '<span style="background:rgba(255,255,255,0.08); color:#666; font-size:0.65rem; padding:1px 6px; border-radius:10px; margin-left:4px;">yeni yok</span>';
                                    } else {
                                        el.innerHTML = '<span style="background:rgba(99,179,237,0.15); color:#63b3ed; font-size:0.65rem; padding:1px 6px; border-radius:10px; margin-left:4px;">' + data.count + ' video</span>';
                                    }
                                }
                            }
                            else if (data.type === 'start') {
                                total = data.total;
                                if (data.onbellek > 0 && total === 0) {
                                    pText.innerHTML = `⚡ <b>Tüm veriler önbellekte! Sentezleniyor...</b>`;
                                } else if (data.onbellek > 0) {
                                    pText.innerHTML = `⚡ <b>${data.onbellek} kişi önbellekten, ${total} video işlenecek...</b>`;
                                } else {
                                    pText.innerHTML = `🎯 <b>${total} video bulundu, işleniyor...</b>`;
                                }
                            } 
                            else if (data.type === 'progress') {
                                completed = data.completed;
                                const yuzde = data.yuzde !== undefined ? data.yuzde : Math.round((completed / total) * 90);
                                pBar.style.width = yuzde + '%';
                                const durumIcon = data.hata ? '❌' : '⏳';
                                pText.innerHTML = `${durumIcon} <b>${completed}/${total}</b><br><span style="color:var(--muted); font-size:0.85rem;">${data.current_title}</span>`;
                            }
                            else if (data.type === 'synthesizing') {
                                pText.innerHTML = `🧠 <b>Tüm videolar okundu! Bülten yazılıyor...</b>`;
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
async def index():
    checks_html = "".join([
        f'<label class="item" id="item-{u["id"]}">'
        f'<span class="item-text">{u["ad"]} <span id="durum-{u["id"]}" style="font-size:0.75rem; color:var(--muted)"></span></span>'
        f'<input type="checkbox" value="{u["id"]}" class="ch">'
        f'<span class="checkmark"></span></label>'
        for u in UNLU_LISTESI
    ])
    # Önbellek durumunu JS'e göm
    onbellek_keys = list(ONBELLEK.keys())
    html = FULL_HTML_TEMPLATE.replace("{CHECKS_HTML}", checks_html)
    html = html.replace("{ONBELLEK_KEYS}", json.dumps(onbellek_keys))
    html = html.replace("{TOPLAM_KANAL}", str(len(UNLU_LISTESI)))
    return html

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


@app.get("/api/durum")
async def guncelleme_durumu():
    cookie_dosyasi = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
    return {
        "calisiyor": ARKAPLAN_CALISIYOR,
        "durumlar": GUNCELLEME_DURUMU,
        "onbellekte": list(ONBELLEK.keys()),
        "cookie_var": os.path.exists(cookie_dosyasi),
        "son_guncelleme": {uid: ONBELLEK[uid].get("zaman", "?") for uid in ONBELLEK}
    }

from fastapi import UploadFile, File

@app.post("/api/cookie-yukle")
async def cookie_yukle(file: UploadFile = File(...)):
    """YouTube cookie dosyasını yükle (bot engelini aşmak için)."""
    cookie_dosyasi = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
    icerik = await file.read()
    with open(cookie_dosyasi, "wb") as f:
        f.write(icerik)
    return {"durum": "ok", "mesaj": "Cookie yüklendi."}

@app.post("/api/aninda")
async def aninda_goster(req: AnalizRequest):
    """Önbellekteki hazır verileri anında birleştirip döndür."""
    onbellekli = [uid for uid in req.ids if uid in ONBELLEK]

    if not onbellekli:
        return {"bos": True, "html": ""}

    secilen_isimler = []
    toplanmis_notlar = []
    for uid in onbellekli:
        ad = ONBELLEK[uid].get("ad", uid)
        secilen_isimler.append(ad)
        # Önbellekteki ham notları kullan (HTML değil)
        notlar = ONBELLEK[uid].get("notlar", [])
        if notlar:
            for not_ in notlar:
                toplanmis_notlar.append(not_)
        else:
            # Eski format: sadece html var, onu not olarak kullan
            toplanmis_notlar.append(f"### {ad}\n{ONBELLEK[uid].get('html', '')}")

    isimler_metni = ", ".join(secilen_isimler)
    sentez_prompt = sentez_promptu_olustur(isimler_metni, toplanmis_notlar)
    try:
        final_text = await guvenli_yapay_zeka_istegi(sentez_prompt)
        final_html = final_text.replace('```html', '').replace('```', '').strip()
        return {"bos": False, "html": final_html}
    except Exception as e:
        return {"bos": False, "html": f"<div class='card'><p style='color:red;'>Hata: {str(e)}</p></div>"}



async def analyze_videos(req: AnalizRequest):
    async def generate():
        # Önce önbellekte hazır mı bak
        onbellekten = []
        islenecekler = []

        for uid in req.ids:
            if uid in ONBELLEK:
                onbellekten.append(uid)
            else:
                islenecekler.append(uid)

        # Önbellekten gelenleri birleştir
        if onbellekten and not islenecekler:
            # Tüm kişiler önbellekte → anında sentez
            yield f"{json.dumps({'type': 'start', 'total': 0, 'onbellek': True})}\n"
            yield f"{json.dumps({'type': 'synthesizing'})}\n"

            secilen_isimler = []
            toplanmis_notlar = []
            for uid in req.ids:
                if uid in ONBELLEK:
                    ad = ONBELLEK[uid].get("ad", uid)
                    secilen_isimler.append(ad)
                    toplanmis_notlar.append(f"### {ad}\n{ONBELLEK[uid]['html']}")

            isimler_metni = ", ".join(secilen_isimler)
            sentez_prompt = sentez_promptu_olustur(isimler_metni, toplanmis_notlar)
            try:
                final_text = await guvenli_yapay_zeka_istegi(sentez_prompt)
                final_html = final_text.replace('```html', '').replace('```', '').strip()
                yield f"{json.dumps({'type': 'result', 'html': final_html})}\n"
            except Exception as e:
                err_html = f"<div class='card' style='border-color:red;'><p>{str(e)}</p></div>"
                yield f"{json.dumps({'type': 'result', 'html': err_html})}\n"
            return

        # Önbellekte olmayan ya da karışık durum → normal işlem
        vids_to_process = []
        secilen_isimler = []
        toplanmis_notlar = []

        # Önbellektekileri ekle
        for uid in onbellekten:
            ad = ONBELLEK[uid].get("ad", uid)
            secilen_isimler.append(ad)
            toplanmis_notlar.append(f"### {ad}\n{ONBELLEK[uid]['html']}")

        # İşlenecekleri kuyruğa al — video yoksa anında geç
        for uid in islenecekler:
            user = next((u for u in UNLU_LISTESI if u["id"] == uid), None)
            if user:
                yield f"{json.dumps({'type': 'scanning', 'uid': uid, 'ad': user['ad']})}\n"
                vids = await asyncio.to_thread(get_recent_vids, user["url"], 3, user.get("channel_id"))
                vid_sayisi = len(vids)
                yield f"{json.dumps({'type': 'vid_count', 'uid': uid, 'count': vid_sayisi})}\n"
                if vids:
                    # Sadece videosu olan kişiyi ekle
                    secilen_isimler.append(user["ad"])
                    for vid, title in vids:
                        vids_to_process.append({"name": user["ad"], "vid": vid, "title": title})

        if not vids_to_process and not toplanmis_notlar:
            yield f"{json.dumps({'type': 'error', 'message': 'Hiç video bulunamadı.'})}\n"
            return

        aktif_video_sayisi = len(vids_to_process)
        yield f"{json.dumps({'type': 'start', 'total': aktif_video_sayisi, 'onbellek': len(onbellekten)})}\n"

        sem = asyncio.Semaphore(2)
        queue = asyncio.Queue()

        async def process_wrapper(v):
            res = await process_video(v["name"], v["vid"], v["title"], sem, queue=queue)
            await queue.put({"type": "done", "res": res})
            return res

        tasks = [asyncio.create_task(process_wrapper(v)) for v in vids_to_process]
        completed = 0

        while completed < aktif_video_sayisi:
            msg = await queue.get()
            if msg["type"] == "subprogress":
                yuzde = round((completed / max(aktif_video_sayisi, 1)) * 90)
                yield f"{json.dumps({'type': 'progress', 'completed': completed, 'current_title': msg['durum'], 'hata': False, 'yuzde': yuzde})}\n"
            elif msg["type"] == "done":
                res = msg["res"]
                completed += 1
                yuzde = round((completed / aktif_video_sayisi) * 90)
                toplanmis_notlar.append(f"### {res['name']} - Video: {res['title']}\n{res['content']}")
                yield f"{json.dumps({'type': 'progress', 'completed': completed, 'current_title': res['title'], 'hata': res.get('hata', False), 'yuzde': yuzde})}\n"

        await asyncio.gather(*tasks, return_exceptions=True)

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
