# ADHD — Notion hissi yerel pano (fikir · görev · proje takibi)

Tamamen **yerel**, **tek pencere**, **çevrimdışı** çalışan kişisel pano.
Fikirlerini, görevlerini ve aktif projelerini (git ölçümleri) tek yerde görürsün;
`data/pano.md` dosyası sayesinde **Hermes/ajanlar** da durumunu okuyabilir.

- **Sıfır zorunlu bağımlılık:** Flask, pip, CDN, internet *gerekmez* — sadece Python
  standart kütüphanesi. `python app.py` her makinede çalışır.
- **İsteğe bağlı masaüstü penceresi:** `pywebview` + WebView2 ile gerçek uygulama
  penceresi (görev çubuğu simgesi, konsolsuz). Kurulu değilse otomatik tarayıcıya düşer.
- **PC açılışında otomatik başlar:** `tools/autostart.py install`.

## Ne gösteriyor

| Sayfa (kanat çubuğu) | Kaynak | Ne var |
|---|---|---|
| **Bugün** (varsayılan) | SQLite `tasks` | tek odak «ŞU AN» şeridi, 4 sayaç, açık/tamamlanan görevler, proje etiketi |
| **Fikirler** | SQLite + `data/fikirler.md` | hızlı kayıt (`i`), canlı arama, silme |
| **Projeler** | `git` (salt okunur) | branch, değişen dosya, son commit, 7 günde commit, GitHub linki |
| **Yapılanlar** | `git log --since=7.days` | son 7 günün commit'leri, en yeni üstte |
| **Sistem** | `gh` CLI + JSON | gh hesabı, üyelikler, tarama ölçümleri, Hermes export bağlantısı |

`bilinmiyor` = okunamayan alan. **Hiçbir yerde 0 veya tahmin uydurulmaz.**

## ADHD tasarım kararları

- Üstte sabit **«ŞU AN»**: tek görev, 21px, tıkla-yaz-Enter. Düzenleme sırasında
  anlık yenileme odak **kaçırmez** (JS bu alanı baypas eder).
- Solda kalıcı kanat çubuğu → sayfa başına **tek iş**, listeler kısa ve gruplu.
- Sayaçlar (açık görev / bugün biten / fikir / proje) motivasyon için; uydurma yok,
  hepsi veritabanından gerçek sayı.
- Görev işaretlenince **hafif «pop»** animasyonu; `prefers-reduced-motion` ile kapanır.
- Koyu tema varsayılan, ◐ ile açık tema (tercih `localStorage`+`.webview` içinde saklanır).
- Klavye: `1-5` sayfa, `t` görev, `i` fikir, `n` ŞU AN, `r` yenile, `?` yardım, `Esc` kapat.

## Kurulum (yeni makine)

```bat
D:\ADHD\setup.cmd      :: .venv kurar + pywebview yükler + testleri koşar + isterse açılışı bağlar
```

1. `.venv` yoksa `python -m venv .venv` çalışır, `pip install pywebview` ile native pencere açılır.
2. `tools\smoke_test.py` koşar (port 5078, ~2 dk) — `[OK]`/`[FAIL]` listesi görürsün.
3. «PC açılışında otomatik açılsın mı?» → `Y` derse Başlangıç klasörüne `ADHD Pano.vbs` konur.

> `setup.cmd` yoksa da pano çalışır: `config.json` → `roots` boşsa hiç repo taranmaz,
> masaüstü penceresi yerine tarayıcı açılır.

## Çalıştırma

| Ne istiyorsun | Komut |
|---|---|
| Masaüstü penceresi (önerilen) | `start_adhd.cmd` (ya da `python app.py`) |
| Tarayıcıda | `python app.py --browser` |
| Sadece sunucu (arayüz yok) | `python app.py --no-browser` |
| JS hatalarını görmek | `python app.py --window --debug` |
| Port testi | `python app.py --port 5099` |
| Açılışta kur | `python app.py --autostart install` (`uninstall` / `status`) |
| Linux/macOS | `./start_adhd.sh` |

**Çift açılma koruması:** pano zaten çalışıyorsa yeni süreç hata vermez,
çalışan pano penceresini gösterir ve çıkar (log: `[BILGI] ... zaten calisiyor`).

## PC açılışında çalıştırma

```bat
python tools\autostart.py install     :: %APPDATA%\...\Startup\ADHD Pano.vbs
python tools\autostart.py status
python tools\autostart.py uninstall
```

VBS 4 sn bekler (sürücü/ağ hazır olsun), konsolsuz başlatır, log `data/pano.log` dosyasına yazılır.

## Hermes / ajan uyumu

Pano her görev, fikir ve «ŞU AN» değişikliğinde **`data/pano.md`** dosyasını atomik olarak yeniden yazar:

```
# ADHD panosu — anlık durum (otomatik yazılır)
## SU AN (tek odak)
## Gorevler (4 acik / 9 toplam)
## Fikirler (12 toplam, son 20)
## Yapilanlar (son 7 gun): 18 commit
## Aktif projeler / Tarama / GitHub
```

Ajan bunu dosyadan okur (`GET /api/export` da aynı içeriği döner). Manuel spec dosyaları
`IDEA.md` (spec) ve `PROMPT.md` (yeni oturuma yapıştırılan brief) olduğu gibi korunur.

## Dosya düzeni

```
D:\ADHD\
  app.py                  stdlib HTTP sunucusu + API + tarama + masaüstü pencere
  scanner.py              repo keşfi + git ölçümleri (salt okunur) + cache
  ghclient.py             `gh` salt-okunur çağrıları
  db.py                   SQLite (ideas, tasks, now_state) + fikirler.md yazımı
  config.json             senin makine yapılandırman (gitignore)
  config.example.json     temiz örnek (repo'da)
  templates/index.html    tek sayfa (kanat çubuğu + sayfalar)
  static/app.css app.js   yerel stil + vanilla JS
  static/favicon.svg
  start_adhd.cmd/.sh      çalıştırıcılar
  setup.cmd               kurulum: .venv + pywebview + test + açılış
  tools/smoke_test.py     uçtan uca otomatik test (port 5078)
  tools/autostart.py      PC açılışına bağla / kaldır (start_boot.vbs üretir)
  tools/startup_check.py  kurulum + açılış doğrulama raporu (33 kontrol)
  data/adhd.db            SQLite — GİTIGNORE
  data/fikirler.md        fikirlerin insan-okunur kopyası — GİTIGNORE
  data/pano.md            ajan özeti — GİTIGNORE
  data/uyelikler.json     üyelik listesi — GİTIGNORE
  data/pano.log           log (ilk bakılacak yer) — GİTIGNORE
  .webview/               pywebview yerel depolaması (tema) — GİTIGNORE
```

## Otomatik test

```bash
python tools/smoke_test.py        # port 5078; çalışan pano ile çakışmaz
python tools/startup_check.py     # kurulum + otomatik açılış doğrulaması
```

Kapsadıkları: soğuk başlangıçta donma yok (<1 sn), gerçek repo/branch/commit verisi,
cache TTL, zorla yenileme, fikir/görev/«ŞU AN» yazımı (`fikirler.md` + `pano.md`),
404/405/path-traversal, timeout yolunda `bilinmiyor` davranışı, CDN referansı yok,
WebView2 + pywebview hazır olup olmadığı.

`startup_check.py` ayrıca şunları doğrular: `webview` (pywebview) import edilebiliyor,
`gh` CLI sürümü, dosyalar UTF-8, README bölümleri, port 5077 + `server.lock` canlı mı,
`Startup\ADHD Pano.vbs` kaynakla aynı mı, VBS içindeki python/app yolları var mı ve o
python `webview` kurabiliyor mu, gizli+kademeli başlangıç, ekran sayısı, disk, `pano.log`
hatasız. Çıktı `--json` ile makine-okunur; **`KALDI` yoksa çıkış 0**.

## Elle test (senin yapman gereken)

1. **Açılış:** `start_adhd.cmd` → ~2 sn içinde masaüstü penceresi açılmalı (tarayıcıda
   açılıyorsa `setup.cmd` çalıştırıp `.venv` oluştuğunu kontrol et). Pencere açılmazsa
   `data/pano.log` son satırlarına bak.
2. **ŞU AN:** üst şeride tıkla → `X yaz` → Enter. Yazı kaydedilmeli, sayfayı
   değiştirmeden yazmaya devam ederken anlık yenileme yazdığın metni silmemeli.
3. **Görev:** Bugün → «Yeni görev» kutusuna yaz → Enter. Görev listeye düşmeli, solda
   sayı (açık görev) artmalı. Kutuyu işaretle → «tamamlandı» animasyonu + Tamamlananlar
   altına geçmeli, «bugün biten» sayacı artmalı. `data/pano.md` içinde görünmeli.
4. **Fikir:** `i` tuşu → yaz → Enter → «fikir kaydedildi» bildirimi → `data/fikirler.md`
   dosyasında o satır olmalı, canlı arama ile filtrelenmeli, `×` ile silince dosyadan da gitmeli.
5. **Sayfalar:** `1-5` tuşlarıyla gezin. Projeler'de gerçek branch/ad/git linki,
   Yapılanlar'da son 7 günün commit'leri, Sistem'de `erenboran` gh hesabı görünmeli.
   `bilinmiyor` yazan alan **hatta değil** — düzeltmeye çalışma, ölçüm okunamamıştır.
6. **Yenileme + çift açılma:** `r` → Tarama kutusundaki «Son tarama» tazelenmeli.
   Pano açıkken `start_adhd.cmd`'ye tekrar çift tıklarsan **ikinci pencere** açılmalı
   ama logda `[BILGI] ... zaten calisiyor` yazmalı, `Get-NetTCPConnection` 5077 tek dinleyici göstermeli.
7. **PC açılışı:** `python tools\autostart.py install` → bilgisayarı yeniden başlat →
   pano konsolsuz kendiliğinden açılmalı. `uninstall` ile geri alınmalı.
8. **Doğrulama raporu:** `python tools\startup_check.py` → **33 GECTI, 0 KALDI**
   görmelisin (autostart kurulu değilse ilgili satırlar `ATLANDI` olur, `KALDI` olmaz).

## API

| Uç | Ne yapar |
|---|---|
| `GET /api/state` | tüm pano verisi (cache'li; `?force=1` yeni tarama) |
| `GET /api/health` | tarama durumu, cache yaşı, son hata |
| `GET /api/export` | Hermes için markdown özet (`data/pano.md` ile aynı) |
| `POST /api/refresh` | taramayı tazele (arka planda) |
| `POST /api/ideas` `DELETE /api/ideas/<id>` | fikir ekle / sil (DB + `fikirler.md` + `pano.md`) |
| `POST /api/tasks` `POST /api/tasks/<id>/toggle` `DELETE /api/tasks/<id>` | görevler |
| `POST /api/now` | üst şeritteki tek görev |

## Sınırlar (uyulan kurallar)

- `git` **salt okunur**: `rev-parse`, `log`, `status`, `remote get-url`.
  `add/commit/push/reset/checkout/stash` yok. `gh` yalnız `auth status`, `api user`, `repo list`.
- Sunucu tarafında LLM/API çağrısı yok, dışarıya ağ isteği yok (font/CSS/JS yerel).
- Panoya yalnız `D:\ADHD` içinde yazılır; taranan repolara dokunulmaz.
- Repoda kişisel veri **yok**: `data/*` ve `config.json` gitignore'da.

## GitHub notu

Repo herkese açık; bu yüzden `data/*` (görevlerin, fikirlerin, logların) ve
`config.json` (disk yolların) commit edilmez. Yine de GitHub'a koymak istersen:

```bash
git add -f config.json data/fikirler.md     # bilerek açığa çıkardıkların
```

## Bilinen eksikler / sonraki adımlar

- Fikirler tek dosyada düz metin; elle eklenen satırlar panoda görünmez (pano yalnız
  kendi eklediklerini listeler).
- `gh repo list` 15 kayıtla sınırlı (`github.repos_limit`).
- Odak zamanlayıcı (Pomodoro), görev son tarihi ve etiket filtresi yok — istenirse eklenir.
- Pencere kapanınca sunucu da kapanır (tek süreç). Arka planda durmasını istersen
  `--no-browser` + ayrı servis gerekir.
