<?php
// Everything the page needs, as one JSON document.
require_once __DIR__ . '/lib.php';
require_login();
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
$db = db();
$all = fn($sql) => $db->query($sql)->fetchAll(PDO::FETCH_ASSOC);

$meta = [];
foreach ($all("SELECT * FROM meta") as $r) $meta[$r['key']] = $r['value'];
$hosting = null;
if (!empty($meta['hosting'])) {
    $h = json_decode($meta['hosting'], true);
    if ($h) $hosting = ['used_gb' => round($h['mb_used'] / 1024, 2), 'limit_gb' => round($h['mb_limit'] / 1024, 2), 'checked' => $h['checked']];
}
$entries = $all("SELECT * FROM entries ORDER BY sort DESC");
foreach ($entries as &$e) $e['links'] = json_decode($e['links'], true);
unset($e);
echo json_encode([
    'imported' => (int)($meta['imported'] ?? 0),
    'timezone' => $CFG['timezone'],
    'words'    => (object)($CFG['words'] ?? []),
    'hosting'  => $hosting,
    'projects' => $all("SELECT * FROM projects ORDER BY updated DESC"),
    'threads'  => $all("SELECT * FROM threads ORDER BY last_day DESC"),
    'entries'  => $entries,
    'notes'    => $all("SELECT * FROM notes ORDER BY day DESC, id"),
    'files'    => $all("SELECT * FROM files ORDER BY older, modified DESC"),
    'tokens'   => $all("SELECT * FROM tokens ORDER BY day DESC"),
], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
