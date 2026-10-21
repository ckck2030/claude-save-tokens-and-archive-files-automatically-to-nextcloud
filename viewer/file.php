<?php
// Opens or downloads one archived file straight from Nextcloud storage.
// file.php?f=<folder>/<name>            html, images, pdf, text open in the browser; everything else downloads
// file.php?f=<folder>/<name>&dl=1       force download
require_once __DIR__ . '/lib.php';
require_login();
$f = $_GET['f'] ?? '';
if ($f === '' || str_contains($f, '..') || $f[0] === '/') { http_response_code(400); exit('bad path'); }
$name = basename($f);
$ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
$inline = ['html' => 'text/html', 'htm' => 'text/html', 'png' => 'image/png', 'jpg' => 'image/jpeg', 'jpeg' => 'image/jpeg',
           'gif' => 'image/gif', 'svg' => 'image/svg+xml', 'pdf' => 'application/pdf', 'txt' => 'text/plain', 'json' => 'application/json',
           'csv' => 'text/plain', 'php' => 'text/plain', 'py' => 'text/plain', 'sh' => 'text/plain', 'yml' => 'text/plain', 'js' => 'text/plain', 'css' => 'text/plain'];
if ($ext === 'md' && empty($_GET['dl'])) { header('Location: view.php?f=' . rawurlencode($f)); exit; }

// one GET request (no HEAD first): headers are sent when the first chunk arrives and Nextcloud said 200
$started = false;
[$code] = dav('GET', $f, [], function ($ch, $chunk) use (&$started, $name, $ext, $inline) {
    if (!$started) {
        $started = true;
        if (curl_getinfo($ch, CURLINFO_RESPONSE_CODE) !== 200) { http_response_code(404); echo "not found: $name"; return -1; }
        if (isset($inline[$ext]) && empty($_GET['dl'])) {
            header('Content-Type: ' . $inline[$ext] . (str_starts_with($inline[$ext], 'text/') ? '; charset=utf-8' : ''));
            header('Content-Disposition: inline; filename="' . $name . '"');
        } else {
            header('Content-Type: application/octet-stream');
            header('Content-Disposition: attachment; filename="' . $name . '"');
        }
        header('Cache-Control: private, max-age=3600');
    }
    echo $chunk; flush(); return strlen($chunk);
});
if (!$started) { http_response_code(404); echo "not found: $name"; }
