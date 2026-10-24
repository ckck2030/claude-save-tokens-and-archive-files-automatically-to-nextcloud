<?php // Claude Archive viewer 1.15.0 (Tokens tab; thread chains: garden-planner-v1, -v2, ...; pending named-handoff links ignored)
require_once __DIR__ . '/lib.php';
require_login(); ?>
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude Archive</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f5f7;--card:#fff;--ink:#1b1e24;--muted:#6b7280;--faint:#a0a6b1;--line:#e6e8ec;--hover:#f2f4f8;--accent:#2457d6;--accent-bg:#eaf0fd;--ok:#1f9d55;--warn:#d97706;--mono:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;--sans:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--ink:#e7e9ee;--muted:#9aa1ad;--faint:#666d79;--line:#262b35;--hover:#1e222b;--accent:#8aabff;--accent-bg:#1d2642}}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:16px/1.5 var(--sans);font-variant-numeric:tabular-nums;display:flex;flex-direction:column}
a{color:var(--accent);text-decoration:none}
button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}

/* top bar */
header{display:flex;align-items:center;gap:28px;padding:0 28px;height:60px;background:var(--card);border-bottom:1px solid var(--line);flex:none}
header h1{font-size:18px;margin:0;font-weight:700;white-space:nowrap}
.sort{display:flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;flex:none}
.sort button{padding:7px 12px;font-size:16px;color:var(--muted)}
.sort button.on{background:var(--accent-bg);color:var(--accent);font-weight:600}
body.tab-projects .sort,body.tab-tokens .sort{display:none}
.tk-per{display:flex;gap:6px;margin:0 0 18px}.tk-per button{padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--muted);font:inherit;cursor:pointer}.tk-per button.on{color:var(--ink);border-color:var(--accent)}
.tk-bar{height:8px;border-radius:4px;background:var(--line);overflow:hidden;display:flex;margin:6px 0 2px}.tk-bar i{display:block;height:100%}
.tk-b{background:#9aa1ad}.tk-a{background:#c2610c}.tk-w{background:var(--accent)}
.tk-key{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:15px;margin-bottom:6px}.tk-key span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;background:var(--c)}
.tk-note{color:var(--muted);font-size:15px;margin-top:10px}
#q{flex:1;max-width:420px;padding:8px 14px;border:1px solid var(--line);border-radius:9px;background:var(--bg);color:var(--ink);font:16px var(--sans)}
#q:focus{outline:2px solid var(--accent);outline-offset:-1px}
mark{background:#fde68a;color:inherit;border-radius:3px;padding:0 1px}
.empty{color:var(--muted);text-align:center;padding:40px}
.tabs{display:flex;gap:4px;height:100%}
.tab{height:100%;padding:0 14px;font-weight:600;color:var(--muted);border-bottom:2px solid transparent}
.tab.on{color:var(--ink);border-bottom-color:var(--accent)}
.meter{margin-left:auto;display:flex;align-items:center;gap:10px;font-size:16px;color:var(--muted);white-space:nowrap}
.bar{width:120px;height:9px;background:var(--line);border-radius:9px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ok)}.bar i.warn{background:var(--warn)}

/* layout: content + optional file pane */
.layout{flex:1;display:flex;min-height:0}
main{flex:1;overflow:auto;padding:28px 28px 80px}
.col{max-width:900px;margin:0 auto}
.pane{display:none;width:46%;flex:none;border-left:1px solid var(--line);background:var(--card);flex-direction:column}
body.pane-open .pane{display:flex}
.pane-head{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--line)}
.pane-head .nm{font-family:var(--mono);font-size:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.pane-head a,.pane-head button{font-size:16px;font-weight:500;color:var(--accent);white-space:nowrap}
.pane-head .x{font-size:20px;line-height:1;color:var(--muted);padding:0 4px}
.pane-body{flex:1;overflow:auto;background:var(--bg)}
.pane-body iframe{width:100%;height:100%;border:0;background:#fff;display:block}
.pane-body img{display:block;max-width:100%;margin:20px auto;box-shadow:0 2px 14px rgba(0,0,0,.12)}
.pane-body pre{margin:0;padding:18px 20px;font:16px/1.6 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}

/* summary strip */
.summary{display:flex;gap:28px;margin:0 0 22px;color:var(--muted);font-size:16px}
.summary b{display:block;font-size:20px;color:var(--ink);font-weight:700}

/* cards */
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin-bottom:16px}
.card h2{margin:0 0 12px;font-size:19px;display:flex;align-items:baseline;gap:10px}
.card h2 .t{font:500 16px var(--mono);color:var(--muted)}
.ac{display:flex;flex-direction:column;gap:14px}
.lbl{font-size:16px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin:2px 0 4px}

/* accordion rows */
details{border-radius:7px}
summary{list-style:none;cursor:pointer;display:flex;align-items:baseline;gap:8px;padding:5px 8px;margin:0 -8px;border-radius:7px}
summary::-webkit-details-marker{display:none}
summary:hover{background:var(--hover)}
summary .ar{width:16px;flex:none;color:var(--faint);font-size:16px;transition:transform .15s;display:inline-block}
details[open]>summary .ar{transform:rotate(90deg)}
summary{justify-content:flex-start}
.sep{color:var(--faint)}
.dt{color:var(--muted)}
summary .t,.time{font:16px var(--mono);color:var(--muted);white-space:nowrap;min-width:46px;text-align:right;flex:none}
.inner{margin:2px 0 10px 66px;padding:8px 0 4px 12px;border-left:2px solid var(--line)}

/* inside a project */
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.btn{display:inline-flex;align-items:center;gap:5px;padding:4px 11px;border:1px solid var(--line);border-radius:7px;font-size:16px;font-weight:500;color:var(--ink);background:var(--card)}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.btn.hand{padding:0 10px;margin-left:10px;flex:none}
.btn.done{border-color:var(--ok);color:var(--ok)}
.entry{display:flex;gap:10px;padding:3px 0}
.entry .c{font:16px var(--mono);color:var(--faint);width:84px;flex:none;padding-top:1px}
.entry .tx{color:var(--muted)}
.files{margin:4px 0 2px}
.file{display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:3px 8px;margin:0 -8px;border-radius:6px}
.file:hover{background:var(--hover)}
.file.sel{background:var(--accent-bg)}
.file .fn{font:16px var(--mono);color:var(--accent);overflow-wrap:anywhere}
.file .sz{font:16px var(--mono);color:var(--faint);flex:none}
.kind{font-size:16px;font-weight:500;padding:0 8px;min-width:118px;text-align:center;border-radius:5px;flex:none;background:var(--hover);color:var(--muted)}
.k-source{color:#2457d6;background:#e8eefc}.k-executables,.k-plugin,.k-installer{color:#1f9d55;background:#e4f5ea}.k-documentation,.k-report{color:#7c3aed;background:#efe9fd}.k-design,.k-images{color:#c2610c;background:#fdf1e0}.k-backup{color:#b91c1c;background:#fde8e8}
.older>summary{font-size:16px;color:var(--muted);padding:3px 8px}
.notes{margin-top:12px;padding-top:10px;border-top:1px solid var(--line)}
.note{display:flex;gap:10px;font-size:16px;padding:2px 0}.note .c{font:16px var(--mono);color:var(--faint);width:84px;flex:none}
.biz-head{font-size:16px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:22px 0 8px;display:flex}
.biz-head{gap:8px;text-transform:none;letter-spacing:0;font-size:17px}
.biz-head .t{font:500 16px var(--mono)}
.proj-card{padding:6px 22px}
/* thread chains: a group of related projects (garden-planner-v1, -v2, ...) */
.chainv{font:500 16px ui-monospace,Consolas,monospace;color:var(--muted);background:var(--hover);border:1px solid var(--line);border-radius:5px;padding:0 6px;white-space:nowrap;flex:none}
.chain{margin:6px 0;padding:2px 0 2px 10px;border-left:2px solid var(--line)}
.chain-head{display:flex;align-items:baseline;gap:8px;padding:5px 8px 3px 0;color:var(--muted)}
.chain-head .nm{font-weight:600;color:var(--ink)}
.sub{font-size:16px;color:var(--faint);font-family:var(--mono)}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 18px;border-radius:9px;font-size:16px;opacity:0;transition:opacity .2s;pointer-events:none;max-width:90vw}
.toast.on{opacity:1}
.foot{color:var(--faint);font-size:16px;margin-top:24px;text-align:center}
@media(max-width:900px){.pane{position:fixed;inset:60px 0 0 0;width:auto;z-index:5}main{padding:16px}header{gap:14px;padding:0 14px}.meter{display:none}}
</style></head><body>
<header>
  <h1>Claude Archive</h1>
  <nav class="tabs"><button class="tab on" data-tab="journal">Journal</button><button class="tab" data-tab="projects">Projects</button><button class="tab" data-tab="tokens">Tokens</button></nav>
  <div class="sort" id="sort"><button data-sort="time">Time spent</button><button data-sort="chrono">Chronological</button></div>
  <input id="q" type="search" placeholder="Search projects, journal, files…" autocomplete="off">
  <div class="meter" id="meter"></div>
</header>
<div class="layout">
  <main><div class="col" id="view">Loading…</div></main>
  <aside class="pane"><div class="pane-head"><span class="nm" id="pname"></span><a id="pdl" href="#">download</a><a id="ptab" href="#" target="_blank">open in new tab</a><button class="x" id="pclose" title="Close">×</button></div><div class="pane-body" id="pbody"></div></aside>
</div>
<div class="toast" id="toast"></div>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const hm = s => `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}`;
const fmtDay = d => new Date(d + 'T12:00:00').toLocaleDateString('en-US', {weekday: 'long', month: 'long', day: 'numeric'});
const fmtDate = ts => new Date(ts * 1000).toLocaleDateString('en-US', {month: '2-digit', day: '2-digit', year: 'numeric'}).replaceAll('/', '-');
const clock12 = ts => new Date(ts * 1000).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit', timeZone: D.timezone}).replace(' ', '').toLowerCase();  // 12:10am
const dayDate = d => d.slice(5, 7) + '-' + d.slice(8, 10) + '-' + d.slice(0, 4);  // 2026-10-21 -> 10-21-2026
const size = b => b < 1024 ? b + ' B' : b < 1048576 ? Math.round(b / 1024) + ' KB' : (b / 1048576).toFixed(1) + ' MB';
const enc = p => encodeURIComponent(p);
const PREVIEW = /\.(html?|png|jpe?g|gif|svg|webp|pdf|md|txt|json|csv|php|py|sh|ya?ml|js|css|log)$/i;
const IMG = /\.(png|jpe?g|gif|svg|webp)$/i, TEXT = /\.(txt|json|csv|php|py|sh|ya?ml|js|css|log)$/i;
let D, threads = {}, files = {}, projects = {}, tab = 'journal', Q = '';
let SORT = 'time', TKP = 'all';
try { SORT = localStorage.getItem('archive-sort') || 'time'; } catch {}
// search: lower-case words that must all appear
const words = () => Q.toLowerCase().split(/\s+/).filter(Boolean);
const hits = text => { const w = words(); if (!w.length) return true; const t = String(text).toLowerCase(); return w.every(x => t.includes(x)); };
const hl = s => { s = esc(s); for (const w of words()) s = s.replace(new RegExp('(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/&/g, '&amp;') + ')', 'gi'), '<mark>$1</mark>'); return s; };

/* ---------- data ---------- */
async function load() {
  D = await (await fetch('api.php', {cache: 'no-store'})).json();
  threads = {}; projects = {}; files = {};
  for (const t of D.threads) threads[t.sid] = t;
  for (const p of D.projects) projects[p.folder] = p;
  for (const f of D.files) (files[f.folder] ??= []).push(f);
  meter(); render();
}
const isHandoff = n => /-handoff-.*-documentation\.md$/.test(n);
// newest version of each product+type is "current"; the rest are previous versions
function split(list) {
  const key = n => { const m = n.match(/^(.+?)-\d{2}-\d{2}-\d{4}-ver([\d.]+)-([a-z]+)(\.[a-z0-9]+)?$/i); return m ? [m[1] + '|' + m[3] + '|' + (m[4] || ''), m[2]] : [n, '0']; };
  const best = {};
  for (const f of list) { if (f.older) continue; const [k, v] = key(f.name); if (!best[k] || cmp(v, best[k].v) > 0) best[k] = {f, v}; }
  const keep = new Set(Object.values(best).map(x => x.f));
  return [list.filter(f => keep.has(f)), list.filter(f => !keep.has(f))];
}
const cmp = (a, b) => { const x = a.split('.').map(Number), y = b.split('.').map(Number); for (let i = 0; i < 4; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0); return 0; };
const pretty = n => n.split(/(\s+)/).map(w => D.words[w.toLowerCase()] || w).join('').replace(/^./, c => c.toUpperCase());
const businessOf = folder => projects[folder]?.business || 'Other';
/* thread chains */
const chainTag = (chain, n) => chain ? `${chain}-v${n}` : '';
const chainBadge = (chain, n) => chain ? ` <span class="chainv">${hl(chainTag(chain, n))}</span>` : '';
// highest number in a chain, over every thread and project the viewer knows
const chainMax = chain => Math.max(0, ...D.threads.filter(t => t.chain === chain).map(t => t.chain_n || 0), ...D.projects.filter(p => p.chain === chain).map(p => p.chain_n || 0));
// the text to paste into a new Claude thread: the next link of the chain, or the plain folder
const continueText = (folder, chain) => chain ? `continue ${chainTag(chain, chainMax(chain) + 1)}` : `continue ${folder}`;
const continueTitle = chain => chain ? 'Copy the text to paste into a new Claude thread (continues from the newest thread in this chain)' : 'Copy the text to paste into a new Claude thread';
const chainOfFolder = folder => projects[folder]?.chain || D.threads.find(t => t.folder === folder && t.chain)?.chain || '';

/* ---------- pieces ---------- */
function fileRow(f) {
  return `<button class="file" data-path="${esc(f.path)}" title="${PREVIEW.test(f.name) ? 'Show on the right' : 'Download'}">
    ${f.kind ? `<span class="kind k-${esc(f.kind)}">${esc(f.kind)}</span>` : ''}<span class="fn">${hl(f.name)}</span><span class="sz">${size(f.size)} · ${fmtDate(f.modified)}</span></button>`;
}
function fileList(list, olderLabel = 'previous versions') {
  if (!list.length) return '';
  const [cur, old] = split(list.filter(f => !isHandoff(f.name)));
  let h = `<div class="files">${cur.map(fileRow).join('')}</div>`;
  if (old.length) h += `<details class="older" data-k="o|${esc(old[0].path)}"><summary><span class="ar">▶</span>${old.length} ${old.length > 1 ? olderLabel : olderLabel.replace(/s$/, '')}</summary><div class="files">${old.map(fileRow).join('')}</div></details>`;
  return h;
}
function actions(folder, threadList, chain = '') {
  let h = '<div class="actions">';
  chain = chain || chainOfFolder(folder);
  if (folder) h += `<button class="btn" data-copy="${esc(continueText(folder, chain))}" title="${esc(continueTitle(chain))}">copy handoff</button>`;
  for (const t of threadList) h += `<a class="btn" href="${esc(t.url)}" target="_blank" title="${esc(t.topic)}">claude thread ${dayDate(t.first_day)} ↗</a>`;
  const hand = (files[folder] || []).find(f => isHandoff(f.name) && !f.older);
  if (hand) h += `<button class="btn" data-path="${esc(hand.path)}">read handoff</button>`;
  return h + '</div>';
}
const row = (name, t, inner, open = false, key = '', folder = '', chain = '') =>
  `<details${open ? ' open' : ''}${key ? ` data-k="${esc(key)}"` : ''}><summary><span class="t">${t}</span><span class="ar">▶</span><span class="nm">${name}</span>${folder ? `<button class="btn hand" data-copy="${esc(continueText(folder, chain || chainOfFolder(folder)))}" title="${esc(continueTitle(chain || chainOfFolder(folder)))}">handoff</button>` : ''}</summary><div class="inner">${inner}</div></details>`;

/* ---------- Journal tab ---------- */
function journal() {
  const days = {};
  for (const e of D.entries) (days[e.day] ??= []).push(e);
  const notes = {}; for (const n of D.notes) (notes[n.day] ??= []).push(n.text);
  const month = new Date().toISOString().slice(0, 7);
  const mDays = Object.keys(days).filter(d => d.startsWith(month));
  const mSecs = D.entries.filter(e => e.day.startsWith(month)).reduce((a, e) => a + e.spent, 0);
  let h = `<div class="summary"><div><b>${hm(mSecs)}</b>worked in ${new Date().toLocaleDateString('en-US', {month: 'long'})}</div><div><b>${mDays.length ? hm(mSecs / mDays.length) : '0:00'}</b>per day</div><div><b>${D.projects.length}</b>projects</div></div>`;
  let found = 0;
  for (const day of Object.keys(days).sort().reverse()) {
    const by = {};
    for (const e of days[day]) (by[e.sid] ??= []).push(e);
    const all = Object.entries(by).filter(([sid]) => threads[sid]).map(([sid, list]) => ({t: threads[sid], list, secs: list.reduce((a, e) => a + e.spent, 0), start: Math.min(...list.map(e => e.sort)), clock: list.slice().sort((a, b) => a.sort - b.sort)[0].clock}))
      .sort(SORT === 'chrono' ? (a, b) => b.start - a.start : (a, b) => b.secs - a.secs);  // chronological = newest first, like the days
    const total = all.reduce((a, p) => a + p.secs, 0);
    const ps = Q ? all.filter(p => hits([p.t.topic, p.t.folder, businessOf(p.t.folder), p.t.chain, chainTag(p.t.chain, p.t.chain_n), ...p.list.map(e => e.text + ' ' + e.links.map(l => l.name).join(' '))].join(' '))) : all;
    const dayNotes = (notes[day] || []).filter(n => hits(n));
    if (Q && !ps.length && !dayNotes.length) continue;
    found++;
    // A: by project
    const A = ps.map(p => {
      let inner = actions(p.t.folder, [p.t], p.t.chain);
      for (const e of p.list.slice().sort((a, b) => a.sort - b.sort)) {
        const fl = e.links.filter(l => l.kind === 'file').map(l => (files[l.folder] || []).find(f => f.name === l.name) || D.files.find(f => f.name === l.name)).filter(Boolean);
        const live = e.links.filter(l => l.kind === 'live').map(l => ` <a href="${esc(l.url)}" target="_blank">live page ↗</a>`).join('');
        if (!e.text && !fl.length && !live) continue;
        inner += `<div class="entry"><span class="c">${esc(e.clock)}</span><div><span class="tx">${esc(e.text)}</span>${live}${fileList(fl)}</div></div>`;
      }
      return row(hl(p.t.topic) + chainBadge(p.t.chain, p.t.chain_n) + ` <span class="dt">· ${clock12(p.start)}-${clock12(p.start + p.secs)}</span>`, hm(p.secs), inner, !!Q, `a|${day}|${p.t.sid}`, p.t.folder, p.t.chain);
    }).join('');
    // C: by business
    const biz = {};
    for (const p of ps) (biz[businessOf(p.t.folder)] ??= []).push(p);
    const C = Object.entries(biz).map(([b, list]) => [b, list, list.reduce((a, p) => a + p.secs, 0), Math.min(...list.map(p => p.start))]).sort(SORT === 'chrono' ? (a, b) => b[3] - a[3] : (a, b) => b[2] - a[2])
      .map(([b, list, secs]) => row(esc(b), hm(secs), list.map(p => `<div class="entry"><span class="time">${hm(p.secs)}</span><span class="tx">${hl(p.t.topic)}</span></div>`).join(''), false, `c|${day}|${b}`)).join('');
    h += `<section class="card"><h2>${fmtDay(day)} <span class="sep">-</span> <span class="t">${hm(total)}</span></h2><div class="ac"><div><div class="lbl">A · By project</div>${A}</div><div><div class="lbl">C · By business</div>${C}</div></div>`;
    if (dayNotes.length) h += `<div class="notes"><div class="lbl">Your notes</div>${dayNotes.map(n => { const m = n.match(/^(\d{1,2}:\d{2}(?:am|pm))\s*(.*)$/); return `<div class="note"><span class="c">${esc(m ? m[1] : '')}</span><span>${hl(m ? m[2] : n)}</span></div>`; }).join('')}</div>`;
    h += `</section>`;
  }
  if (Q && !found) h += `<div class="empty">Nothing in the journal matches “${esc(Q)}”.</div>`;
  return h;
}

/* ---------- Projects tab ---------- */
function projectsView() {
  const groups = {};
  for (const p of D.projects) {
    const text = [p.name, p.folder, p.business, p.topic, p.chain, chainTag(p.chain, p.chain_n), ...D.threads.filter(t => t.folder === p.folder).map(t => t.topic), ...(files[p.folder] || []).map(f => f.name)].join(' ');
    if (hits(text)) (groups[p.business] ??= []).push(p);
  }
  // one project row; a chain member gets its <chain>-v<n> badge in front of the name
  const projectRow = p => {
    const th = D.threads.filter(t => t.folder === p.folder);
    const inner = `<div class="sub" style="margin-bottom:8px">${esc(p.folder)} · updated ${fmtDate(p.updated)}</div>${actions(p.folder, th, p.chain)}${fileList(files[p.folder] || [])}`;
    const last = th.map(t => t.last_day).sort().pop();
    const when = last ? dayDate(last) : fmtDate(p.updated);
    return `<div id="p-${esc(p.folder)}">${row(chainBadge(p.chain, p.chain_n).trim() + (p.chain ? ' ' : '') + hl(pretty(p.name)) + ` <span class="dt">· ${when}</span>`, p.secs ? hm(p.secs) : '0:00', inner, !!Q, `p|${p.folder}`, p.folder, p.chain)}</div>`;
  };
  let h = Object.keys(groups).length ? '' : `<div class="empty">No project matches “${esc(Q)}”.</div>`;
  for (const [b, list] of Object.entries(groups).sort((x, y) => y[1][0].updated - x[1][0].updated)) {
    const lastDay = D.threads.filter(t => list.some(p => p.folder === t.folder)).map(t => t.last_day).sort().pop();
    const bizWhen = lastDay ? dayDate(lastDay) : fmtDate(Math.max(...list.map(p => p.updated)));
    h += `<div class="biz-head">${esc(b)} <span class="sep">-</span> <span class="t">${hm(list.reduce((a, p) => a + p.secs, 0))} total</span> <span class="sep">-</span> <span class="dt">last worked ${bizWhen}</span></div><section class="card proj-card">`;
    // projects of the same chain stay together as one group (list is newest first, so a group sits where its newest member is)
    const items = [], chainGroup = {};
    for (const p of list) {
      if (!p.chain) { items.push(p); continue; }
      if (!chainGroup[p.chain]) items.push(chainGroup[p.chain] = {chain: p.chain, members: []});
      chainGroup[p.chain].members.push(p);
    }
    for (const it of items) {
      if (!it.members) { h += projectRow(it); continue; }
      const members = it.members.slice().sort((a, b) => (a.chain_n || 0) - (b.chain_n || 0));
      const secs = members.reduce((a, p) => a + p.secs, 0);
      h += `<div class="chain"><div class="chain-head"><span class="time">${hm(secs)}</span><span class="nm">${hl(it.chain)}</span><span class="dt">· ${members.length} thread${members.length > 1 ? 's' : ''}</span></div>${members.map(projectRow).join('')}</div>`;
    }
    h += `</section>`;
  }
  return h;
}

/* ---------- Tokens tab ---------- */
const tk = n => n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'K' : String(n);
const pct = (a, b) => b ? Math.round(a / b * 100) + '%' : '0%';
function tkBar(r) {
  const w = Math.max(r.total - r.base - r.archive, 0);
  return `<div class="tk-bar"><i class="tk-b" style="width:${r.base / r.total * 100}%"></i><i class="tk-a" style="width:${r.archive / r.total * 100}%"></i><i class="tk-w" style="width:${w / r.total * 100}%"></i></div>`;
}
function tokensView() {
  const today = new Date().toLocaleDateString('en-CA', {timeZone: D.timezone});
  const back = n => { const d = new Date(today + 'T12:00:00'); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
  const from = TKP === '7' ? back(6) : TKP === '30' ? back(29) : '';
  const rows = (D.tokens || []).filter(r => r.day >= from && hits([r.project, threads[r.sid]?.topic].join(' ')));
  const per = `<div class="tk-per">${[['7', 'Last 7 days'], ['30', 'Last 30 days'], ['all', 'All time']].map(([k, l]) => `<button data-tkp="${k}" class="${TKP === k ? 'on' : ''}">${l}</button>`).join('')}</div>`;
  if (!rows.length) return per + `<div class="empty">No token data${from ? ' for this period' : ''} yet. Threads are counted from archive plugin 2.3.1 on.</div>`;
  const sum = list => list.reduce((a, r) => ({total: a.total + r.total, base: a.base + r.base, archive: a.archive + r.archive, calls: a.calls + r.calls}), {total: 0, base: 0, archive: 0, calls: 0});
  const all = sum(rows);
  const work = Math.max(all.total - all.base - all.archive, 0);
  let h = per + `<div class="summary"><div><b>${tk(all.total)}</b>tokens used</div><div><b>${tk(all.base)} · ${pct(all.base, all.total)}</b>starting context</div><div><b>${tk(all.archive)} · ${pct(all.archive, all.total)}</b>archive plugin</div><div><b>${tk(work)} · ${pct(work, all.total)}</b>your work</div></div>`;
  h += `<div class="tk-key"><span style="--c:#9aa1ad">Starting context: system prompt, tools and memory, read again on every Claude call</span><span style="--c:#c2610c">Archive plugin (estimate)</span><span style="--c:var(--accent)">Your work</span></div>`;
  const byP = {};
  for (const r of rows) (byP[r.project || threads[r.sid]?.topic || 'Other'] ??= []).push(r);
  const ranked = Object.entries(byP).map(([p, list]) => [p, list, sum(list)]).sort((a, b) => b[2].total - a[2].total);
  h += `<div class="biz-head">Projects ranked by tokens</div><section class="card">`;
  ranked.forEach(([p, list, s], i) => {
    const bySid = {};
    for (const r of list) (bySid[r.sid] ??= []).push(r);
    const inner = Object.entries(bySid).map(([sid, l]) => [sid, l, sum(l)]).sort((a, b) => b[2].total - a[2].total).map(([sid, l, x]) => {
      const t = threads[sid], days = l.map(r => r.day).sort();
      const when = days.length > 1 ? `${dayDate(days[0])} to ${dayDate(days[days.length - 1])}` : dayDate(days[0]);
      return `<div class="entry"><span class="time">${tk(x.total)}</span><div><span class="tx">${t ? `<a href="${esc(t.url)}" target="_blank">${hl(t.topic)}</a>` : esc(sid)}</span> <span class="dt">· ${when} · ${x.calls} Claude calls · archive ${tk(x.archive)}</span>${tkBar(x)}</div></div>`;
    }).join('');
    h += row(`${i + 1}. ${hl(pretty(p.replace(/-/g, ' ')))} <span class="dt">· ${pct(s.total, all.total)} of all · ${Object.keys(bySid).length} thread${Object.keys(bySid).length > 1 ? 's' : ''}</span>` + tkBar(s), tk(s.total), inner, !!Q, `t|${p}`);
  });
  h += `</section><div class="tk-note">Counted by the archive plugin from each thread's own usage records (no extra Claude calls). Only threads where the plugin runs are counted; plain claude.ai chats are not. "Tokens used" adds up everything Claude read and wrote on every call, so a long thread costs more per message than a short one.</div>`;
  return h;
}

function render() {
  // keep open sections open when the data refreshes
  const openKeys = new Set([...document.querySelectorAll('details[open][data-k]')].map(d => d.dataset.k));
  const scroll = $('main').scrollTop;
  for (const b of document.querySelectorAll('.tab')) b.classList.toggle('on', b.dataset.tab === tab);
  for (const b of document.querySelectorAll('[data-sort]')) b.classList.toggle('on', b.dataset.sort === SORT);
  document.body.classList.toggle('tab-projects', tab === 'projects');
  document.body.classList.toggle('tab-tokens', tab === 'tokens');
  $('#view').innerHTML = (tab === 'journal' ? journal() : tab === 'tokens' ? tokensView() : projectsView()) + `<div class="foot">Updated ${fmtDate(D.imported)} ${new Date(D.imported * 1000).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'})} · new work appears automatically</div>`;
  for (const d of document.querySelectorAll('details[data-k]')) if (openKeys.has(d.dataset.k)) d.open = true;
  const sel = document.querySelector('.pane-open') && $('#pname').textContent;
  if (sel) document.querySelectorAll('.file').forEach(f => f.classList.toggle('sel', f.dataset.path.endsWith('/' + sel)));
  $('main').scrollTop = scroll;
}
function meter() {
  const h = D.hosting; if (!h) return;
  const pct = Math.round(100 * h.used_gb / h.limit_gb);
  $('#meter').innerHTML = `Hosting space <span class="bar"><i class="${pct > 80 ? 'warn' : ''}" style="width:${pct}%"></i></span>${pct}% used · ${(h.limit_gb - h.used_gb).toFixed(1)} GB free`;
}

/* ---------- file pane ---------- */
function openFile(path, btn) {
  const name = path.split('/').pop(), url = 'file.php?f=' + enc(path);
  if (!PREVIEW.test(name)) { location.href = url + '&dl=1'; return; }
  document.querySelectorAll('.file.sel').forEach(x => x.classList.remove('sel'));
  if (btn) btn.classList.add('sel');
  $('#pname').textContent = name; $('#pdl').href = url + '&dl=1';
  const md = /\.md$/i.test(name);
  $('#ptab').href = md ? 'view.php?f=' + enc(path) : url;
  const body = $('#pbody');
  body.innerHTML = '<pre>Loading…</pre>';
  if (IMG.test(name)) { const im = new Image(); im.onload = () => { body.innerHTML = ''; body.append(im); }; im.src = url; }
  else if (md) body.innerHTML = `<iframe src="view.php?embed=1&f=${enc(path)}"></iframe>`;
  else if (TEXT.test(name)) { body.innerHTML = '<pre>Loading…</pre>'; fetch(url).then(r => r.text()).then(t => body.firstChild.textContent = t); }
  else body.innerHTML = `<iframe src="${url}"></iframe>`;
  document.body.classList.add('pane-open');
}
$('#pclose').onclick = () => { document.body.classList.remove('pane-open'); $('#pbody').innerHTML = ''; document.querySelectorAll('.file.sel').forEach(x => x.classList.remove('sel')); };

/* ---------- clicks ---------- */
let toastTimer;
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('on'), 2200); }
async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch { const ta = document.createElement('textarea'); ta.value = text; document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
}
document.addEventListener('click', e => {
  const t = e.target.closest('[data-tab],[data-path],[data-copy],[data-sort],[data-tkp]');
  if (!t) return;
  if (t.dataset.sort) { SORT = t.dataset.sort; try { localStorage.setItem('archive-sort', SORT); } catch {} render(); return; }
  if (t.dataset.tab) { tab = t.dataset.tab; render(); $('main').scrollTop = 0; return; }
  if (t.dataset.tkp) { TKP = t.dataset.tkp; render(); return; }
  if (t.dataset.copy) { e.preventDefault(); e.stopPropagation(); copy(t.dataset.copy); const label = t.dataset.label || (t.dataset.label = t.textContent); t.classList.add('done'); t.textContent = 'copied ✓'; setTimeout(() => { t.classList.remove('done'); t.textContent = label; }, 1800); toast('Copied: ' + t.dataset.copy + ' — paste it into a new Claude thread'); return; }
  if (t.dataset.path) openFile(t.dataset.path, t.classList.contains('file') ? t : null);
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (document.body.classList.contains('pane-open')) $('#pclose').click(); else if (Q) { $('#q').value = ''; Q = ''; render(); } } });
let qTimer;
$('#q').addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(() => { Q = $('#q').value.trim(); render(); }, 150); });
// live updates: every 20 s (only while this tab is visible) read a tiny timestamp; reload the data only when it changed
let stamp = null;
async function poll() {
  if (document.hidden) return;
  try {
    const s = (await (await fetch('stamp.php', {cache: 'no-store'})).text()).trim();
    if (stamp !== null && s !== stamp) await load();
    stamp = s;
  } catch {}
}
setInterval(poll, 20000);
document.addEventListener('visibilitychange', poll);
load().then(poll);
</script></body></html>
