# PROMPT — D:\ADHD panosu (yeni Hermes oturumuna yapıştır)

Görev: `D:\ADHD` altındaki **yerel kişisel kontrol panosunu** sürdür/tamamla.
Önce `D:\ADHD\IDEA.md`'yi (spec) ve `D:\ADHD\README.md`'yi (dosya düzeni + test adımları)
baştan sona oku, sonra uygula. Çelişki varsa spec kazanır.

## Ortam gerçekleri (araştırmaya harcama, doğrulanmış)

- Windows 11. `python` = makine genelinde Python 3.13 (`C:\Python313`);
  **`python3` bu makinede yok** (WindowsApps stub) — her yerde `python` kullan.
- Panonun kendi sanal ortamı `D:\ADHD\.venv` (`setup.cmd` kurar); orada
  `pywebview` 6.x vardır. **Flask hiçbir yerde kurulu değil ve gerekli değil** —
  `app.py` stdlib HTTP sunucusudur (`http.server.ThreadingHTTPServer`).
- `gh` kurulu ve `erenboran` hesabıyla login (keyring, https, scope: repo, workflow, read:org, gist).
- Native `git`/`gh` MSYS yolunu çevirmez: `git -C /d/x` **patlar**, `git -C "D:/x"` çalışır.
  Koddaki tüm subprocess yolları `D:/...` / `C:/...` biçiminde forward-slash olmalı.
- Bazı repolar devasa untracked yığınına sahip → `git status --porcelain
  --untracked-files=no` + 60 sn metrik cache + 300 sn keşif cache **zorunlu**.
- Makinede 2 monitör var; pano penceresi hangi monitörde açılırsa açılsın test
  `tools/smoke_test.py` (API düzeyi) ile yapılır, ekran görüntüsüyle değil.

## Yapılacak (tipik isteklerde)

- Yeni panel/alan → `templates/index.html` + `static/app.css` + `static/app.js`
  (vanilla JS, **tek `fetch(` noktası**: `api()` fonksiyonu), API → `app.py` içindeki
  `App.r_*` metodları, kalıcı veri → `db.py`.
- Yazma sonrası `self.write_export()` çağrısını unutma (aksi halde `data/pano.md` bayat kalır).

## Sınırlar (ihlali = görev başarısız)

- **Salt-okunur git** (`add/commit/push/reset/checkout/stash` yok, `gh repo` yazma komutu yok)
  — istisna: kullanıcının açıkça istediği GitHub **push** işlemi (repoya yazma hariç).
- `D:\ADHD` dışına dosya yazma. **Tek izinli istisna:** `tools/autostart.py install`
  ile Windows Başlangıç klasörüne `ADHD Pano.vbs`.
- Hiçbir veriyi uydurma: okunamayan alan `null` → ekranda `bilinmiyor`.
- Sunucu tarafında LLM/API çağrısı yok, dışarıya ağ isteği yok (Google Fonts dahil).
- `D:\MarketingAPP` (port 5000) uygulamasına dokunma.
- Repoda kişisel veri kalmasın: `data/*` ve `config.json` gitignore'da.

## Doğrulama (bitirmeden önce yap ve çıktıyı göster)

1. `python D:/ADHD/tools/smoke_test.py` → `TUM TESTLER GECTI` (veya `[FAIL]` satırları).
2. `python D:/ADHD/tools/startup_check.py` → **0 KALDI** (autostart kurulu değilse
   ilgili satırlar `ATLANDI` olur).
2. `curl -s http://127.0.0.1:5077/api/state` → gerçek repo adları, branch'ler, gh hesabı
   (ilk 40 satır JSON).
3. Fikir ekle → `data/fikirler.md` **ve** `data/pano.md` içinde o satır; sonra sil.
4. İkinci kez `python app.py` başlat → logda `[BILGI] ... zaten calisiyor`, 5077'de
   tek dinleyici.

## Rapor biçimi

Tek mesaj: (1) çalışan komut, (2) doğrulama çıktıları, (3) değişen dosyalar,
(4) bilinen eksikler, (5) bana 4–7 adımlık elle test listesi (çift tıkla → ne görmeliyim
→ yanlış görürsem nereye bakayım). Uzun anlatım yok.
