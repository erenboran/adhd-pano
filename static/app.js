/* ADHD panosu — vanilla JS, dis bagimlilik yok, tek fetch noktasi (api()).
 *
 * Tasarim notlari:
 *   * Anlik yenileme (poll) yazarken odagi kaciraz: "ŞU AN" duzenleme sirasinda
 *     render edilmez, listeler scroll konumunu korur.
 *   * Hicbir yerde veri uydurulmaz: okunamayan alan "bilinmiyor" gosterilir.
 */
"use strict";

const UNKNOWN = "bilinmiyor";
const PAGES = ["bugun", "fikirler", "projeler", "yapilanlar", "sistem"];

const state = {
  page: "bugun",
  data: null,
  editingNow: false,
  ideaFilter: "",
  flashTask: null,
  pollMs: 60000,
};

const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
};
const clear = (n) => { while (n.firstChild) n.removeChild(n.firstChild); };

/* ------------------------------------------------------------ bicimlendirme */
function fmtDate(iso) {
  if (!iso) return UNKNOWN;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return UNKNOWN;
  return d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit" });
}
function fmtAgo(iso) {
  if (!iso) return UNKNOWN;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return UNKNOWN;
  const min = Math.round((Date.now() - d.getTime()) / 60000);
  if (min < 1) return "az önce";
  if (min < 60) return min + " dk önce";
  const h = Math.round(min / 60);
  if (h < 48) return h + " sa önce";
  return Math.round(h / 24) + " gün önce";
}
function localDayKey(d) {
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}
function val(v) { return (v === null || v === undefined || v === "") ? UNKNOWN : v; }
function isUnknown(v) { return v === null || v === undefined || v === ""; }
function unknownTxt(text) { return el("span", "unknown", text || UNKNOWN); }
const short = (s, n) => { s = s || ""; return s.length > n ? s.slice(0, n - 1) + "…" : s; };
function ghUrl(remote) {
  if (!remote) return null;
  let m = remote.match(/^git@([^:]+):(.+?)(\.git)?$/);
  if (m) return "https://" + m[1] + "/" + m[2];
  m = remote.match(/^https?:\/\/([^/]+)\/(.+?)(\.git)?$/);
  if (m) return "https://" + m[1] + "/" + m[2];
  return null;
}

/* ------------------------------------------------------------------- toast */
let toastTimer = null;
function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("is-hidden"), 3400);
}

/* -------------------------------------------------------------------- api */
async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({ ok: false, error: "geçersiz JSON" }));
  if (!r.ok || j.ok === false) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}

/* --------------------------------------------------------------- listeler */
function replaceList(ul, build) {
  const top = ul.scrollTop;
  clear(ul);
  build(ul);
  ul.scrollTop = top;
}

function emptyRow(ul, text) {
  const li = el("li");
  li.appendChild(el("span", "empty", text));
  ul.appendChild(li);
}

/* ----------------------------------------------------------------- render */
function renderNow(now) {
  if (state.editingNow) return;
  const span = $("#now-text");
  if (!span) return;
  const empty = isUnknown(now && now.text);
  span.textContent = empty ? "tek görev tanımlı değil — tıkla" : now.text;
  span.classList.toggle("is-empty", empty);
  $("#now-strip").title = empty
    ? "Henüz odak yok — tıkla ve yaz"
    : "Güncellendi: " + fmtDate(now.updated_at) + " · tıkla → yaz → Enter";
}

function renderStats(d) {
  const tasks = d.tasks || [];
  const today = localDayKey(new Date());
  const open = tasks.filter((t) => !t.done).length;
  const doneToday = tasks.filter((t) => t.done && t.done_at && String(t.done_at).slice(0, 10) === today).length;
  $("#stat-open").textContent = String(open);
  $("#stat-done").textContent = String(doneToday);
  $("#stat-ideas").textContent = String(d.idea_count || 0);
  $("#stat-projects").textContent = String((d.projects || []).length);
  $("#stat-done").parentElement.classList.toggle("is-good", doneToday > 0);
  $("#bugun-sub").textContent = open === 0
    ? "Açık görev yok — bugünün listesi boş. İstersen fikirlerine bak."
    : open + " açık görev var. Hepsini değil, yalnız birini seç.";
}

function renderTasks(d) {
  const tasks = d.tasks || [];
  const open = tasks.filter((t) => !t.done);
  const done = tasks.filter((t) => t.done);
  $("#tasks-meta").textContent = open.length + " açık";
  $("#done-meta").textContent = done.length + " tamamlandı";

  replaceList($("#tasks"), (ul) => {
    if (!open.length) { emptyRow(ul, "açık görev yok — Enter ile ekle"); return; }
    for (const t of open) ul.appendChild(taskRow(t));
  });
  replaceList($("#tasks-done"), (ul) => {
    if (!done.length) { emptyRow(ul, "henüz biten görev yok"); return; }
    for (const t of done) ul.appendChild(taskRow(t));
  });
}

function taskRow(t) {
  const li = el("li");
  if (t.done) li.classList.add("done");
  if (state.flashTask === t.id) { li.classList.add("just-done"); state.flashTask = null; }

  const cb = el("input", "cb");
  cb.type = "checkbox";
  cb.checked = !!t.done;
  cb.title = t.done ? "geri al" : "tamamlandı";
  cb.onchange = async () => {
    try {
      const r = await api("POST", "/api/tasks/" + t.id + "/toggle");
      if (r.task && r.task.done) state.flashTask = t.id;
      await load();
      if (r.task && r.task.done) toast("tamamlandı — güzel gidiyorsun");
    } catch (e) { toast("güncellenemedi: " + e.message, true); }
  };
  li.appendChild(cb);
  li.appendChild(el("span", "txt", t.text));
  if (t.project) li.appendChild(el("span", "who", t.project));
  if (t.done && t.done_at) li.appendChild(el("span", "when", fmtDate(t.done_at)));

  const del = el("button", "del", "×");
  del.title = "sil";
  del.onclick = async () => {
    try { await api("DELETE", "/api/tasks/" + t.id); await load(); }
    catch (e) { toast("silinemedi: " + e.message, true); }
  };
  li.appendChild(del);
  return li;
}

function renderIdeas(d) {
  const all = d.ideas || [];
  const q = state.ideaFilter.trim().toLocaleLowerCase("tr");
  const list = q ? all.filter((i) => String(i.text).toLocaleLowerCase("tr").includes(q)) : all;
  $("#ideas-meta").textContent = d.idea_count + " kayıt · data/fikirler.md"
    + (q ? " · " + list.length + " eşleşme" : "");

  replaceList($("#ideas"), (ul) => {
    if (!list.length) {
      emptyRow(ul, all.length ? "aramaya uyan fikir yok" : "henüz fikir yok — `i` ile ekle");
      return;
    }
    for (const it of list) {
      const li = el("li");
      li.appendChild(el("span", "when", fmtDate(it.created_at)));
      li.appendChild(el("span", "txt", it.text));
      const del = el("button", "del", "×");
      del.title = "sil";
      del.onclick = async () => {
        try { await api("DELETE", "/api/ideas/" + it.id); toast("fikir silindi"); await load(); }
        catch (e) { toast("silinemedi: " + e.message, true); }
      };
      li.appendChild(del);
      ul.appendChild(li);
    }
  });
}

function renderProjects(d) {
  const tb = $("#projects tbody");
  clear(tb);
  const ps = d.projects || [];
  const sc = d.scan || {};
  const timeouts = sc.timeout_count || 0;
  $("#projects-sub").textContent = ps.length + " proje · " + (sc.repos_scanned || 0) + " tarandı"
    + (timeouts ? " · " + timeouts + " timeout" : "")
    + " · git ölçümü salt okunur; hiçbir repoya yazılmaz.";

  if (!ps.length) {
    const tr = el("tr");
    const td = el("td", "empty unknown", d.ready ? "repo bulunamadı (config.json → roots)" : "ilk tarama sürüyor…");
    td.colSpan = 6;
    tr.appendChild(td);
    tb.appendChild(tr);
    return;
  }
  for (const p of ps) {
    const tr = el("tr");
    if (p.is_hint) tr.classList.add("hint");
    if (p.timeout) tr.classList.add("timeout");
    if (p.errors && p.errors.length) { tr.classList.add("err"); tr.title = p.errors.join("\n"); }

    const name = el("td");
    name.appendChild(el("span", null, val(p.name)));
    if (p.errors && p.errors.length) name.appendChild(el("span", "meta", " (" + short(p.errors[0], 60) + ")"));
    tr.appendChild(name);

    const br = el("td");
    if (isUnknown(p.branch)) br.appendChild(unknownTxt()); else br.textContent = p.branch;
    tr.appendChild(br);

    const dirty = el("td", "num");
    if (isUnknown(p.dirty)) dirty.appendChild(unknownTxt());
    else {
      const pill = el("span", "pill" + (p.dirty > 0 ? " dirty" : ""), String(p.dirty));
      pill.title = "git status --porcelain --untracked-files=no satır sayısı";
      dirty.appendChild(pill);
    }
    tr.appendChild(dirty);

    const lc = el("td");
    if (isUnknown(p.last_commit_iso)) lc.appendChild(unknownTxt());
    else {
      lc.appendChild(el("div", null, fmtDate(p.last_commit_iso) + "  ·  " + fmtAgo(p.last_commit_iso)));
      lc.appendChild(el("div", "meta", short(p.last_commit_subject || "", 54)));
    }
    tr.appendChild(lc);

    const c7 = el("td", "num");
    if (isUnknown(p.commits_7d)) c7.appendChild(unknownTxt());
    else c7.textContent = String(p.commits_7d) + (p.commits_7d_capped ? "+" : "");
    tr.appendChild(c7);

    const src = el("td");
    const url = ghUrl(p.remote);
    if (url) {
      const a = el("a", null, short(p.remote.replace(/^https?:\/\/|^git@/, ""), 34));
      a.href = url; a.target = "_blank"; a.rel = "noreferrer noopener";
      src.appendChild(a);
    } else if (isUnknown(p.remote)) src.appendChild(unknownTxt());
    else src.textContent = short(p.remote, 34);
    tr.appendChild(src);

    tb.appendChild(tr);
  }
}

function renderCommits(d) {
  const list = d.yapilanlar || [];
  const days = (d.config && d.config.yapilanlar_days) || 7;
  const sc = d.scan || {};
  let meta = "son " + days + " gün · " + list.length + " commit";
  if (sc.yapilanlar_capped && sc.yapilanlar_total)
    meta += " (toplam " + sc.yapilanlar_total + ", ilk " + list.length + " gösteriliyor)";
  $("#yapilanlar-meta").textContent = meta;

  replaceList($("#yapilanlar"), (ul) => {
    if (!list.length) {
      emptyRow(ul, d.ready ? "son " + days + " günde commit yok" : "ilk tarama sürüyor…");
      return;
    }
    for (const c of list) {
      const li = el("li");
      li.appendChild(el("span", "when", fmtDate(c.date)));
      li.appendChild(el("span", "who", c.repo));
      li.appendChild(el("span", "sha", c.sha || UNKNOWN));
      li.appendChild(el("span", "txt", c.subject || UNKNOWN));
      ul.appendChild(li);
    }
  });
}

function kv(parent, k, v, cls) {
  const row = el("div", "kv");
  row.appendChild(el("span", "k", k));
  const vv = el("span", "v" + (cls ? " " + cls : ""));
  if (v instanceof Node) vv.appendChild(v); else vv.textContent = val(v);
  row.appendChild(vv);
  parent.appendChild(row);
  return row;
}

function renderGithub(g) {
  const box = $("#gh-body");
  clear(box);
  if (!g || g.binary === false) { box.appendChild(unknownTxt("gh bulunamadı")); return; }
  kv(box, "Durum", g.authenticated === true ? "giriş yapılmış"
    : (g.authenticated === false ? "giriş yok" : UNKNOWN),
    g.authenticated === true ? "ok" : (g.authenticated === false ? "bad" : "unknown"));
  kv(box, "Hesap", g.account ? (g.account + (g.name ? " (" + g.name + ")" : "")) : null,
    g.account ? "ok" : "unknown");
  kv(box, "Token kapsamı", (g.scopes && g.scopes.length) ? g.scopes.join(", ") : null);
  kv(box, "Repo (gh list)", (g.repo_count === null || g.repo_count === undefined)
    ? null : (g.repo_count + " repo · " + (g.repos_private ?? UNKNOWN) + " private"));
  kv(box, "Son push", g.last_push || null);
  if (g.error) kv(box, "Not", g.error, "warn");
  const repos = g.repos || [];
  if (repos.length) {
    const ul = el("ul", "rows");
    for (const r of repos.slice(0, 8)) {
      const li = el("li");
      li.appendChild(el("span", "txt", r.name || UNKNOWN));
      li.appendChild(el("span", "when", r.visibility || ""));
      li.appendChild(el("span", "who", fmtAgo(r.pushed_at)));
      ul.appendChild(li);
    }
    box.appendChild(ul);
  }
}

function renderUyelik(u) {
  const box = $("#uyelik-body");
  clear(box);
  if (!u || !u.ok) {
    box.appendChild(unknownTxt("uyelikler.json okunamadı"));
    if (u && u.error) kv(box, "Hata", u.error, "warn");
    return;
  }
  const items = u.items || [];
  if (!items.length) { box.appendChild(unknownTxt("kayıt yok")); return; }
  for (const it of items) {
    const bits = [];
    bits.push(it.ad || UNKNOWN);
    bits.push((it.tutar === null || it.tutar === undefined) ? UNKNOWN : (it.tutar + " " + (it.para || "")));
    bits.push(it.yenileme ? ("yenileme " + it.yenileme) : "yenileme " + UNKNOWN);
    if (it.aktif === false) bits.push("pasif");
    const row = kv(box, it.tur || "üyelik", bits.join(" · "), (it.aktif === false ? "unknown" : null));
    if (it.not) row.title = it.not;
  }
}

function renderScan(s, d) {
  const box = $("#scan-body");
  clear(box);
  if (!d.ready) { box.appendChild(unknownTxt("ilk tarama sürüyor…")); return; }
  kv(box, "Son tarama", d.scan_generated_at
    ? fmtDate(d.scan_generated_at) + " · " + fmtAgo(d.scan_generated_at) : null);
  kv(box, "Süre (duvar)", s.wall_sec != null ? s.wall_sec + " sn" : null);
  kv(box, "Süre (git)", s.duration_sec != null ? s.duration_sec + " sn" : null);
  kv(box, "Klasör taraması", s.discovery_sec != null ? s.discovery_sec + " sn" : null);
  kv(box, "Repo / keşif", (s.repos_scanned ?? UNKNOWN) + " / " + (s.repos_discovered ?? UNKNOWN)
    + (s.git_repos != null ? " (git: " + s.git_repos + ")" : ""));
  kv(box, "Taranan klasör", (s.dirs_visited ?? UNKNOWN) + " klasör");
  kv(box, "Timeout", (s.timeout_count ? s.timeout_count + " (" + (s.timeouts || []).join(", ") + ")" : "0"),
    s.timeout_count ? "warn" : null);
  if (s.not_git && s.not_git.length) kv(box, "Git değil", s.not_git.join(", "), "warn");
  if (s.archived && s.archived.length) kv(box, "Arşiv (ölçülmedi)", s.archived.join(", "));
  kv(box, "Cache", "TTL " + (s.cache_ttl_sec ?? UNKNOWN) + " sn · yaş " + (d.cached_age_sec ?? UNKNOWN) + " sn");
  kv(box, "git timeout", (s.git_timeout_sec ?? UNKNOWN) + " sn · " + (s.workers ?? UNKNOWN) + " paralel işçi");
  if (d.scan_error) kv(box, "Hata", d.scan_error, "bad");
  if (s.missing_hint_paths && s.missing_hint_paths.length)
    kv(box, "Eksik yol", s.missing_hint_paths.join(", "), "warn");
}

function renderExport(d) {
  const box = $("#export-body");
  if (box.dataset.path === d.export_path) return;  // tekrar yazma
  box.dataset.path = d.export_path || "";
  clear(box);
  kv(box, "Dosya", d.export_path || null);
  const link = el("a", null, "pano.md önizle");
  link.href = "/api/export";
  link.target = "_blank";
  link.rel = "noreferrer noopener";
  kv(box, "Ajan özeti", link);
  kv(box, "Not", "Görev / fikir / «ŞU AN» her değişiklikte bu dosyaya yazılır; Hermes buradan okur.");
}

function renderBadges(d) {
  const tasks = d.tasks || [];
  const set = (id, n, on) => {
    const b = $("#" + id);
    if (!b) return;
    b.textContent = n ? String(n) : "";
    b.classList.toggle("is-on", !!on);
  };
  set("badge-bugun", tasks.filter((t) => !t.done).length, true);
  set("badge-fikirler", d.idea_count || 0, false);
  set("badge-projeler", (d.projects || []).length, false);
  set("badge-yapilanlar", (d.yapilanlar || []).length, false);

  const mini = $("#status-mini");
  const gh = d.github || {};
  clear(mini);
  const head = el("b", null, gh.account || (d.ready ? "gh: bilinmiyor" : "tarama sürüyor"));
  mini.appendChild(head);
  const tail = [];
  if (gh.repo_count != null) tail.push(gh.repo_count + " repo");
  if (d.ready && d.scan) tail.push((d.scan.repos_scanned ?? "?") + " yerel repo");
  if (tail.length) mini.appendChild(document.createTextNode("\n" + tail.join(" · ")));
}

/* ---------------------------------------------------------------- yukleme */
let inFlight = false;
let pendingForce = false;

async function load(force) {
  if (inFlight) { if (force) pendingForce = true; return; }
  inFlight = true;
  if (force) pendingForce = false;
  try {
    const d = await api("GET", "/api/state" + (force ? "?force=1" : ""));
    state.data = d;
    state.pollMs = Math.max(15, ((d.config && d.config.cache_ttl_sec) || 60)) * 1000;
    renderNow(d.now);
    renderStats(d);
    renderTasks(d);
    renderIdeas(d);
    renderProjects(d);
    renderCommits(d);
    renderGithub(d.github);
    renderUyelik(d.uyelikler);
    renderScan(d.scan || {}, d);
    renderExport(d);
    renderBadges(d);
    schedule((!d.ready || d.refreshing) ? 2500 : state.pollMs);
  } catch (e) {
    toast("pano verisi alınamadı: " + e.message, true);
    schedule(5000);
  } finally {
    inFlight = false;
    if (pendingForce) { pendingForce = false; load(true); }
  }
}

let timer = null;
function schedule(ms) {
  clearTimeout(timer);
  timer = setTimeout(() => load(false), ms);
}

/* ------------------------------------------------------------ sayfa gezinme */
function goto(page, focusSel) {
  if (!PAGES.includes(page)) page = "bugun";
  state.page = page;
  for (const p of PAGES) {
    const sec = $("#page-" + p);
    if (sec) sec.classList.toggle("is-hidden", p !== page);
  }
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.page === page);
  });
  if (location.hash.slice(1) !== page) history.replaceState(null, "", "#" + page);
  window.scrollTo(0, 0);
  if (focusSel) {
    const n = $(focusSel);
    if (n) { n.focus(); if (n.select) n.select(); }
  }
}

/* ------------------------------------------------------------ «ŞU AN» düzenlemesi */
function startNowEdit() {
  if (state.editingNow) return;
  const span = $("#now-text");
  if (!span) return;
  state.editingNow = true;

  const inp = document.createElement("input");
  inp.type = "text";
  inp.maxLength = 300;
  inp.id = "now-input";
  inp.value = span.classList.contains("is-empty") ? "" : span.textContent;
  span.replaceWith(inp);
  inp.focus();
  inp.select();

  const finish = async (save) => {
    if (!state.editingNow) return;
    const text = inp.value.trim();
    state.editingNow = false;
    const ns = document.createElement("span");
    ns.className = "now-text";
    ns.id = "now-text";
    ns.textContent = "kaydediliyor…";
    inp.replaceWith(ns);
    if (save) {
      try {
        await api("POST", "/api/now", { text: text });
        toast("odak güncellendi");
      } catch (e) { toast("kaydedilemedi: " + e.message, true); }
    }
    load();
  };

  inp.onkeydown = (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); finish(true); }
    else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); finish(false); }
  };
  inp.onblur = () => { finish(true); };
}

/* ---------------------------------------------------------------- etkilesim */
function wireNow() {
  $("#now-strip").addEventListener("click", () => startNowEdit());
}

function wireForms() {
  $("#task-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const input = $("#task-input");
    const proj = $("#task-project");
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    try {
      await api("POST", "/api/tasks", { text: text, project: proj.value.trim() || undefined });
      input.value = "";
      proj.value = "";
      input.focus();
      toast("görev eklendi");
      load();
    } catch (e) { toast("görev eklenemedi: " + e.message, true); }
  });

  $("#idea-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const input = $("#idea-input");
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    try {
      const r = await api("POST", "/api/ideas", { text: text });
      input.value = "";
      toast("fikir kaydedildi → data/fikirler.md (#" + r.idea.id + ")");
      load();
    } catch (e) { toast("fikir eklenemedi: " + e.message, true); }
  });

  $("#idea-search").addEventListener("input", (ev) => {
    state.ideaFilter = ev.target.value;
    if (state.data) renderIdeas(state.data);
  });
}

function wireNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => goto(btn.dataset.page));
  });
  window.addEventListener("hashchange", () => goto(location.hash.slice(1)));
}

function wireButtons() {
  $("#btn-refresh").addEventListener("click", () => { load(true); toast("tarama yenileniyor…"); });
  $("#btn-help").addEventListener("click", () => toggleHelp());
  $("#help-close").addEventListener("click", () => toggleHelp(false));
  $("#help").addEventListener("click", (ev) => { if (ev.target.id === "help") toggleHelp(false); });
  $("#btn-theme").addEventListener("click", () => setTheme(
    document.documentElement.dataset.theme === "light" ? "dark" : "light"));
}

function toggleHelp(force) {
  const m = $("#help");
  const show = force === undefined ? m.classList.contains("is-hidden") : force;
  m.classList.toggle("is-hidden", !show);
}

function setTheme(name) {
  document.documentElement.dataset.theme = name;
  try { localStorage.setItem("adhd-theme", name); } catch (e) { /* yok sayilabilir */ }
}

function restoreTheme() {
  let saved = null;
  try { saved = localStorage.getItem("adhd-theme"); } catch (e) { /* yok sayilabilir */ }
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
}

document.addEventListener("keydown", (ev) => {
  const tag = (ev.target.tagName || "").toLowerCase();
  const typing = tag === "input" || tag === "textarea" || tag === "select";
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;

  if (ev.key === "Escape") {
    if (!$("#help").classList.contains("is-hidden")) { toggleHelp(false); return; }
  }
  if (typing) return;

  if (ev.key === "?") { ev.preventDefault(); toggleHelp(); return; }
  if (ev.key >= "1" && ev.key <= "5") { ev.preventDefault(); goto(PAGES[Number(ev.key) - 1]); return; }
  if (ev.key === "t") { ev.preventDefault(); goto("bugun", "#task-input"); return; }
  if (ev.key === "i") { ev.preventDefault(); goto("fikirler", "#idea-input"); return; }
  if (ev.key === "n") { ev.preventDefault(); startNowEdit(); return; }
  if (ev.key === "r") { ev.preventDefault(); load(true); toast("tarama yenileniyor…"); }
});

/* ------------------------------------------------------------------ baslangic */
restoreTheme();
wireNow();
wireForms();
wireNav();
wireButtons();
goto(location.hash.slice(1) || "bugun");
load(false);
