<?php
// Shows a Markdown file (handoff docs, reports) as a readable page.
require_once __DIR__ . '/lib.php';
require_login();
require_once __DIR__ . '/markdown.php';
$f = $_GET['f'] ?? '';
if ($f === '' || str_contains($f, '..') || $f[0] === '/') { http_response_code(400); exit('bad path'); }
[$code, $body] = dav('GET', $f);
if ($code !== 200) { http_response_code(404); exit('not found'); }
$name = basename($f);
?>
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title><?= htmlspecialchars($name) ?></title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d23;--muted:#6b7280;--line:#e5e7eb;--accent:#2563eb;--code:#f1f3f6}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--ink:#e6e8ec;--muted:#9aa1ad;--line:#2a2f3a;--accent:#7aa2ff;--code:#1f232c}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 Inter,system-ui,sans-serif}
.top{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:12px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.top a{color:var(--accent);text-decoration:none;font-weight:500}.top .name{font-size:16px;color:var(--muted);overflow-wrap:anywhere}
main{max-width:860px;margin:32px auto;padding:0 24px 80px}
h1,h2,h3{line-height:1.25}h1{font-size:30px}h2{font-size:22px;margin-top:40px;border-bottom:1px solid var(--line);padding-bottom:6px}
a{color:var(--accent)}code{font-size:16px;background:var(--code);padding:2px 5px;border-radius:4px}
pre{background:var(--code);padding:14px 16px;border-radius:8px;overflow:auto}pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%}th,td{border:1px solid var(--line);padding:6px 10px;text-align:left}
blockquote{border-left:3px solid var(--line);margin:0;padding:0 16px;color:var(--muted)}li{margin:3px 0}
<?php if (!empty($_GET['embed'])) echo 'body{font-size:16px}main{margin:8px auto;padding:0 20px 60px}h1{font-size:21px}h2{font-size:17px;margin-top:28px}'; ?>
</style></head><body>
<?php if (empty($_GET['embed'])): ?><div class="top"><a href="./">← Claude Archive</a><span class="name"><?= htmlspecialchars($name) ?></span><a href="file.php?f=<?= rawurlencode($f) ?>&dl=1">download .md</a></div><?php endif; ?>
<main><?= md_html($body) ?></main>
</body></html>
