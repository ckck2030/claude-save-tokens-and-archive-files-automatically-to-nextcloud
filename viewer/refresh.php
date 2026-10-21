<?php
// Called by the Claude Archive plugin right after it saves files or journal lines: rebuilds the data once.
// POST with header "X-Archive-Token: <refresh_token from config.php>". Answers at once, then works in the background.
require_once __DIR__ . '/lib.php';
$token = $_SERVER['HTTP_X_ARCHIVE_TOKEN'] ?? '';
if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !hash_equals($CFG['refresh_token'], $token)) { http_response_code(403); exit('forbidden'); }
ignore_user_abort(true);
set_time_limit(180);
echo "ok\n";
if (function_exists('fastcgi_finish_request')) fastcgi_finish_request();
else { header('Connection: close'); header('Content-Length: 3'); @ob_end_flush(); flush(); }
// one rebuild at a time; a second call while one runs waits, then rebuilds again so nothing is missed
$lock = fopen(dirname($CFG['db']) . '/refresh.lock', 'c');
flock($lock, LOCK_EX);
ob_start(); require __DIR__ . '/import.php'; ob_end_clean();
flock($lock, LOCK_UN);
