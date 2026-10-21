<?php
// Rebuilds the database from Nextcloud: .state/journal-days.json, the file tree and (if present) journal/hosting-space.json.
// Run from the command line (php import.php) or by cron. Safe to run any time; it replaces everything.
require_once __DIR__ . '/lib.php';

// Which business or client a project belongs to: business_by_topic / business_by_folder in config.php,
// otherwise the first word of the folder name.
function business_of(string $folder, string $topic = ''): string {
    global $CFG;
    foreach ($CFG['business_by_topic'] ?? [] as $re => $label) if (preg_match($re, $topic)) return $label;
    foreach ($CFG['business_by_folder'] ?? [] as $prefix => $label) if (str_starts_with($folder, $prefix)) return $label;
    return $folder ? ucfirst(explode('-', $folder)[0]) : 'Other';
}

// "recipe-app-desktop-10-17-2026-ver2.6.9-source.zip" -> product, date, version, kind
function parse_name(string $name): array {
    if (preg_match('/^(.+?)-(\d{2}-\d{2}-\d{4})-ver([\d.]+)-([a-z]+)(?:\.[a-z0-9]+)?$/i', $name, $m))
        return ['product' => $m[1], 'date' => $m[2], 'version' => $m[3], 'kind' => $m[4]];
    return ['product' => '', 'date' => '', 'version' => '', 'kind' => ''];
}

function classify_link(string $label, string $url): array {
    global $CFG;
    $root = preg_quote(trim($CFG['root'], '/'), '#');
    $l = ['label' => $label, 'url' => $url, 'kind' => 'live', 'folder' => '', 'name' => ''];
    if (str_contains($url, 'claude.ai/')) { $l['kind'] = 'thread'; return $l; }
    if (preg_match("#dir=/$root/([^&]+)#", $url, $m)) {
        $l['folder'] = urldecode($m[1]);
        if (str_contains($url, 'handoff=1')) $l['kind'] = 'handoff';
        elseif (str_contains($url, 'openfile')) { $l['kind'] = 'file'; $l['name'] = $label; }
        else $l['kind'] = 'files';
        return $l;
    }
    if (preg_match("#/remote.php/webdav/$root/([^/]+)/(.+)$#", $url, $m)) {
        $l['kind'] = 'file'; $l['folder'] = urldecode($m[1]); $l['name'] = urldecode($m[2]);
    }
    return $l;
}

$db = db();
$db->beginTransaction();
foreach (['projects', 'threads', 'entries', 'notes', 'files', 'meta'] as $t) $db->exec("DELETE FROM $t");

// ---- journal days ----
[$code, $body] = dav('GET', '.state/journal-days.json');
if ($code !== 200) die("journal-days.json: HTTP $code\n");
$jd = json_decode($body, true);

$insThread = $db->prepare("INSERT OR REPLACE INTO threads VALUES (?,?,?,?,?,?,?)");
$insEntry  = $db->prepare("INSERT INTO entries (day,sid,clock,spent,text,links,sort) VALUES (?,?,?,?,?,?,?)");
$insNote   = $db->prepare("INSERT INTO notes (day,text) VALUES (?,?)");
$threads = [];
foreach ($jd as $day => $rec) {
    if ($day === '_notes') {
        foreach ($rec as $d => $lines) foreach ($lines as $ln) $insNote->execute([$d, preg_replace('/^- /', '', $ln)]);
        continue;
    }
    if ($day === '_months') { foreach ($rec as $m => $v) $db->prepare("INSERT INTO meta VALUES (?,?)")->execute(["month:$m", $v]); continue; }
    if ($day[0] === '_') continue;
    foreach ($rec as $url => $e) {
        if (!is_array($e) || empty($e['topic'])) continue;
        $sid = preg_replace('#.*/#', '', $url);
        $t = &$threads[$sid];
        if (!$t) $t = ['url' => $url, 'topic' => $e['topic'], 'folder' => $e['folder'] ?? '', 'secs' => 0, 'first' => $day, 'last' => $day];
        $t['secs'] += (int)$e['secs'];
        if (!empty($e['folder'])) $t['folder'] = $e['folder'];
        $t['topic'] = $e['topic'];
        $t['first'] = min($t['first'], $day); $t['last'] = max($t['last'], $day);
        unset($t);
        foreach ($e['lines'] ?? [] as $i => $line) {
            if (!preg_match('/^- (\d{1,2}:\d{2}(?:am|pm)) (?:\((\d+):(\d{2})(?: spent)?\) )?(.*?)(?: - (\[.*\]\(.*\)))?$/', $line, $m)) continue;
            $spent = $m[2] !== '' ? (int)$m[2] * 3600 + (int)$m[3] * 60 : 0;
            $links = [];
            if (!empty($m[5]) && preg_match_all('/\[([^\]]+)\]\(([^)\s]+)\)/', $m[5], $lm, PREG_SET_ORDER))
                foreach ($lm as $x) $links[] = classify_link(str_replace("\u{a0}", ' ', $x[1]), $x[2]);
            $text = $m[4];
            if ($spent && str_starts_with($text, $e['topic'])) $text = trim(substr($text, strlen($e['topic'])), " -");
            $ts = strtotime("$day " . $m[1]);
            $insEntry->execute([$day, $sid, $m[1], $spent, $text, json_encode($links, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), $ts]);
        }
    }
}
// a thread with no folder of its own: use the folder its journal links point at
foreach ($threads as $sid => &$t) if ($t['folder'] === '') {
    foreach ($db->query("SELECT links FROM entries WHERE sid=" . $db->quote($sid)) as $row)
        foreach (json_decode($row['links'], true) as $l) if ($l['folder'] && in_array($l['kind'], ['files', 'handoff'])) { $t['folder'] = $l['folder']; break 2; }
}
unset($t);
foreach ($threads as $sid => $t) $insThread->execute([$sid, $t['url'], $t['topic'], $t['folder'], $t['secs'], $t['first'], $t['last']]);

// ---- file tree ----
[$code, $xml] = dav('PROPFIND', '', ['Depth: infinity']);
if ($code >= 300) die("PROPFIND: HTTP $code\n");
$doc = new DOMDocument(); $doc->loadXML($xml);
$xp = new DOMXPath($doc); $xp->registerNamespace('d', 'DAV:');
$prefix = '/remote.php/dav/files/' . $CFG['user'] . $CFG['root'] . '/';
$insFile = $db->prepare("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?)");
$folders = [];
foreach ($xp->query('//d:response') as $r) {
    $href = urldecode($xp->evaluate('string(d:href)', $r));
    if (!str_starts_with($href, $prefix)) continue;
    $path = substr($href, strlen($prefix));
    if ($path === '') continue;
    $isDir = $xp->query('.//d:collection', $r)->length > 0;
    $top = explode('/', $path)[0];
    if (in_array($top, $CFG['skip'])) continue;
    $mod = strtotime($xp->evaluate('string(.//d:getlastmodified)', $r)) ?: 0;
    if ($isDir) { if (!str_contains($path, '/')) $folders[rtrim($path, '/')] = $mod; continue; }
    $name = basename($path);
    $p = parse_name($name);
    $older = (int)(str_contains($path, '/older-versions/') || str_contains($path, '/old/'));
    $insFile->execute([$path, $top, $name, (int)$xp->evaluate('string(.//d:getcontentlength)', $r), $mod, $older, $p['kind'], $p['product'], $p['version'], $p['date']]);
    $folders[$top] = max($folders[$top] ?? 0, $mod);
}

// ---- projects (one per folder) ----
$insProj = $db->prepare("INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?,?)");
foreach ($folders as $folder => $mod) {
    $th = array_filter($threads, fn($t) => $t['folder'] === $folder);
    $secs = array_sum(array_column($th, 'secs'));
    usort($th, fn($a, $b) => strcmp($b['last'], $a['last']));
    $topic = $th ? $th[0]['topic'] : '';
    $name = preg_replace('/-\d{2}-\d{2}-\d{4}-ver[\d.]+-/', ' · ', $folder);
    $name = ucfirst(str_replace('-', ' ', $name));
    $insProj->execute([$folder, $name, business_of($folder, $topic), $mod, $secs, $topic]);
}

// ---- hosting meter ----
[$code, $body] = dav('GET', 'journal/hosting-space.json');
if ($code === 200) $db->prepare("INSERT OR REPLACE INTO meta VALUES ('hosting',?)")->execute([$body]);
$db->prepare("INSERT OR REPLACE INTO meta VALUES ('imported',?)")->execute([time()]);
$db->commit();
file_put_contents(dirname($CFG['db']) . '/stamp.txt', (string)time());  // the page polls this tiny file
printf("%d projects, %d threads, %d files\n", count($folders), count($threads), $db->query("SELECT COUNT(*) FROM files")->fetchColumn());
