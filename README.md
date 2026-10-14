## Overview (English)

Send tasks from your phone to an AI agent running on your PC.

- **frontend/** — mobile-first chat panel (vanilla JS).
- **backend/** — FastAPI server with session auth and WebSocket streaming between the panel and the agent.
- **agent/** — the PC-side client: an AI planner (Google Gemini) plus tools for listing / reading / writing files and
  running terminal commands, restricted to allowed workspace folders and gated by user approval.
- Can be exposed through a tunnel (ngrok / Cloudflare) via `start_public.py`; Docker Compose file included.

Copy `.env.example` to `.env` and fill in your own tokens and Gemini key.

---

# AI PC Agent

Telefon üzerinden web panelden bilgisayardaki AI ajana komut gönderen, FastAPI tabanlı güvenli bir MVP.

## Özellikler

- Mobil öncelikli chat benzeri web panel
- FastAPI backend ve WebSocket akışı
- Ayrı çalışan PC Agent istemcisi
- Oturum doğrulama
- Güvenli workspace sınırları
- Dosya listeleme, okuma ve yazma
- Terminal komutu çalıştırma ve onay kapısı
- Gemini için genişletilebilir AI planner katmanı

## Mimari

- `backend/` kullanıcı paneli, oturumlar, websocket köprüsü ve görev yönetimini tutar
- `agent/` bilgisayarda çalışan istemci, dosya ve terminal araçları ile iş akışını yürütür
- `frontend/` HTML, CSS ve vanilla JavaScript ile hazırlanmış paneli sunar

## Kurulum 1: Windows

### 1. Python kurulumu

Python 3.12 veya üstünü kur. Kurulum sırasında `Add Python to PATH` seçeneğini aktif et.

### 2. Proje klasörüne geç

```powershell
cd C:\path\to\ai-pc-agent
```

### 3. Sanal ortam oluştur

```powershell
python -m venv .venv
```

### 4. Sanal ortamı etkinleştir

```powershell
.\.venv\Scripts\Activate.ps1
```

PowerShell execution policy engel olursa şu komutu bir kez çalıştır:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 5. Backend bağımlılıklarını kur

```powershell
cd backend
pip install -r requirements.txt
```

### 6. Ortam değişkenlerini ayarla

Kök dizindeki `.env.example` dosyasını `.env` olarak kopyala ve değerleri doldur.

Gerekli alanlar:

- `FRONTEND_ACCESS_TOKEN`
- `AGENT_TOKEN`
- `ALLOWED_WORKSPACE_ROOTS`
- `GEMINI_API_KEY` (opsiyonel)

`ALLOWED_WORKSPACE_ROOTS` için örnek:

```powershell
ALLOWED_WORKSPACE_ROOTS=C:\Users\mursel\Projects;C:\Users\mursel\Desktop\AIProjects
```

### 7. Backend başlat

Yeni terminal aç ve şu komutu çalıştır:

```powershell
cd C:\path\to\ai-pc-agent\backend
python main.py
```

Backend adresi:

- Yerel bilgisayardan: `http://127.0.0.1:8000`
- Telefon üzerinden aynı Wi‑Fi ağından: `http://<PC_IP_ADRESI>:8000`

Telefon erişimi için PC'nin LAN IP adresini öğren:

```powershell
ipconfig
```

Çıktıda `IPv4 Address` alanını not et. Örnek:

```text
192.168.1.50
```

Sonra telefonun tarayıcısına şu adresi yaz:

```text
http://192.168.1.50:8000
```

### 8. Agent başlat

Başka bir terminalde:

```powershell
cd C:\path\to\ai-pc-agent\agent
python main.py
```

Agent, `BACKEND_WS_URL` ve `AGENT_TOKEN` ile backend’e bağlanır.

### 9. Web panelini aç

Tarayıcıda şu adresi aç:

- Bilgisayardan: `http://127.0.0.1:8000`
- Telefondan: `http://<PC_IP_ADRESI>:8000`

Giriş ekranında `FRONTEND_ACCESS_TOKEN` değerini gir. Varsayılan örnek değer:

```text
demo-panel-token
```

Agent token ise `.env` dosyasında `AGENT_TOKEN` olarak tanımlıdır:

```text
demo-agent-token
```

## Örnek akış

1. Web panelden: `Masaüstündeki Proje1 klasörünü bul ve içindeki README dosyasını oku.`
2. Agent klasörü arar.
3. Onay gerekmezse güvenli araçlarla dosyayı okur.
4. Sonuç panelde görünür.

## Güvenlik modeli

- Agent yalnızca `ALLOWED_WORKSPACE_ROOTS` içindeki klasörlere erişir
- Path traversal engellenir
- Riskli komutlar için onay gerekir
- Web panel oturum token’ı ile korunur
- Production kullanımında HTTPS/WSS kullanılmalıdır

## Komut onayları

Onay gerektiren örnek işlemler:

- `npm install`
- `pip install`
- `git push`
- `shutdown`
- `restart`
- silme komutları

Web panelde onay kartı görünür. Kullanıcı onaylamadan agent komutu çalıştırmaz.

## Gemini desteği

Bu proje, Gemini tek AI katmanı olarak tasarlanmıştır. `GEMINI_API_KEY` eklenmeden çalışma başlatılmaz; sistem otomatik olarak yerel fallback’a dönmez.

Aktif araçlar:

- `read_file`
- `write_file`
- `list_directory`
- `search_files`
- `run_command`
- `start_program`
- `get_processes`

Riskli komutlar için her zaman kullanıcıdan onay beklenir.

## Uzaktan kontrol (aynı Wi‑Fi gerekmez)

Aynı ağda olmak istemiyorsan, bir ters tünel kullan:

### 1) Cloudflare Tunnel

```powershell
npm install -g cloudflared
cloudflared tunnel --url http://localhost:8000
```

Sonra çıktıda gelen HTTPS URL'yi `.env` içindeki `BACKEND_PUBLIC_URL` ve `BACKEND_WS_URL` alanlarına yaz.

### 2) ngrok

```powershell
ngrok http 8000
```

Aldığın public URL'yi `.env` içine yaz:

```env
BACKEND_PUBLIC_URL=https://<ngrok-host>
BACKEND_WS_URL=wss://<ngrok-host>/ws/agent
```

Bu şekilde telefonun aynı Wi‑Fi içinde olmasına gerek kalmadan paneli ve agent bağlantısını kullanabilirsin.

## Docker ile çalıştırma

`docker-compose.yml` hazırdır. `.env` dosyasını oluşturduktan sonra:

```powershell
docker compose up --build
```

Not: Agent container’ı erişeceği klasörlere bağlıdır; gerçek bilgisayarda çalışan agent için yerel Python çalıştırması daha uygundur.

## Doğrulama

- Backend açık mı: `http://127.0.0.1:8000/api/health`
- Panel açılıyor mu: `http://127.0.0.1:8000`
- Agent bağlandı mı: panelde durum çubuğu

## V1 kapsamı

- Web panel
- FastAPI backend
- WebSocket iletişimi
- PC Agent istemcisi
- Authentication
- Mesaj gönderme ve cevap alma
- Dosya listeleme ve okuma
- Güvenli terminal komutları
- Onay sistemi

## Sonraki sürümler

- V2: Gemini tool calling, otomatik hata çözme, kod düzenleme, terminal analizi
- V3: çoklu bilgisayar, CPU/RAM, çalışan programlar, dosya yükleme/indirme, görev kuyruğu
