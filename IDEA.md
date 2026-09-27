# IDEA — D:\ADHD panosu (spec)

Görev: `D:\ADHD` altında benim için **yerel bir kişisel kontrol panosu** kur/tutr.
Flask **yok** — sunucu yalnızca Python standart kütüphanesidir (harici paket gerekmez).
Tam dosya düzeni ve test adımları `README.md`'dedir; bu dosya davranış spec'idir.

## Zorunlu davranışlar

1. `127.0.0.1:5077`, CDN'siz tek sayfa, kanat çubuğu + 5 sayfa
   (Bugün / Fikirler / Projeler / Yapılanlar / Sistem) + üstte sabit «ŞU AN» şeridi.
2. Veri: SQLite (`ideas`, `tasks`, `now_state`), fikir ayrıca `data/fikirler.md`'ye,
   ajan özeti her değişiklikte `data/pano.md` dosyasına atomik yazılır.
3. `git` **salt-okunur** (`rev-parse`, `log`, `status`, `remote get-url`);
   `gh` yalnız `auth status` / `api user` / `repo list`.
4. **Donma yasak:** tarama arka planda, `/api/state` asla taramayı beklemez,
   her git çağrısında ayrı `git_timeout_sec` (20 sn), `git status --porcelain
   --untracked-files=no`, 4 paralel işçi, `GIT_OPTIONAL_LOCKS=0`,
   klasör keşfi 300 sn, metrik 60 sn cache.
5. **Veri uydurma yasak:** okunamayan alan `null` kalır, ekranda `bilinmiyor` görünür.
6. **Çift açılma korumasi:** port doluysa süreç hata vermez, çalışan panoyu gösterir
   (port kontrolü `connect` ile yapılır — `bind` + `SO_REUSEADDR` Windows'ta yanıltır).
7. PC açılışında otomatik başlangıç: `tools/autostart.py install`
   (Windows Başlangıç klasörüne `ADHD Pano.vbs`, konsolsuz, 4 sn gecikme).
8. Masaüstü penceresi: `pywebview` + WebView2 (`edgechromium` zorlanır, IE'ye düşmez);
   kurulu değilse/pencere açılmazsa otomatik tarayıcıya düşer.

## Test kapısı

`python tools/smoke_test.py` (port 5078) yeşil olmalı; elle test adımları README'de.

## Sınırlar

- Yazma yalnız `D:\ADHD` içinde. **Tek istisna:** kullanıcının talebiyle Windows
  Başlangıç klasörüne `ADHD Pano.vbs` (kaldırma: `autostart.py uninstall`).
- Dışarıya ağ isteği yok; sunucu tarafında LLM/API yok.
- `D:\MarketingAPP` (port 5000) uygulamasına dokunulmaz.
- GitHub repo **herkese açık**: `data/*` ve `config.json` gitignore'da kalır.
