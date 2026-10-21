<?php
// Shared helpers: config, database, Nextcloud WebDAV access
if (!file_exists(__DIR__ . '/config.php')) { http_response_code(500); exit('config.php is missing: run php setup.php on the server (see README).'); }
$CFG = require __DIR__ . '/config.php';
date_default_timezone_set($CFG['timezone']);

function db(): PDO {
    global $CFG;
    static $pdo = null;
    if ($pdo) return $pdo;
    @mkdir(dirname($CFG['db']), 0755, true);
    $pdo = new PDO('sqlite:' . $CFG['db']);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec("
        CREATE TABLE IF NOT EXISTS projects (folder TEXT PRIMARY KEY, name TEXT, business TEXT, updated INTEGER, secs INTEGER DEFAULT 0, topic TEXT);
        CREATE TABLE IF NOT EXISTS threads  (sid TEXT PRIMARY KEY, url TEXT, topic TEXT, folder TEXT, secs INTEGER, first_day TEXT, last_day TEXT);
        CREATE TABLE IF NOT EXISTS entries  (id INTEGER PRIMARY KEY, day TEXT, sid TEXT, clock TEXT, spent INTEGER, text TEXT, links TEXT, sort INTEGER);
        CREATE TABLE IF NOT EXISTS notes    (id INTEGER PRIMARY KEY, day TEXT, text TEXT);
        CREATE TABLE IF NOT EXISTS files    (path TEXT PRIMARY KEY, folder TEXT, name TEXT, size INTEGER, modified INTEGER, older INTEGER, kind TEXT, product TEXT, version TEXT, date TEXT);
        CREATE TABLE IF NOT EXISTS meta     (key TEXT PRIMARY KEY, value TEXT);
    ");
    return $pdo;
}

function dav_url(string $path): string {
    global $CFG;
    $parts = array_map('rawurlencode', explode('/', ltrim($path, '/')));
    return $CFG['host'] . '/remote.php/dav/files/' . $CFG['user'] . $CFG['root'] . '/' . implode('/', $parts);
}

// Raw WebDAV request. Returns [status, body, content-type].
function dav(string $method, string $path, array $headers = [], $sink = null): array {
    global $CFG;
    $ch = curl_init(dav_url($path));
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_USERPWD => $CFG['user'] . ':' . $CFG['password'],
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => $sink === null,
        CURLOPT_FOLLOWLOCATION => true,
    ]);
    if ($sink !== null) curl_setopt($ch, CURLOPT_WRITEFUNCTION, $sink);
    $body = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $type = curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
    curl_close($ch);
    return [$code, $body, $type];
}

function hm(int $secs): string {
    return sprintf('%d:%02d', intdiv($secs, 3600), intdiv($secs % 3600, 60));
}

// ---- sign-in: one user, password hash in config, long-lived cookie so the browser remembers it ----
function auth_token(): string { global $CFG; return hash_hmac('sha256', $CFG['login_user'] . '|' . $CFG['login_hash'], $CFG['password']); }
function signed_in(): bool { return isset($_COOKIE['archive_auth']) && hash_equals(auth_token(), $_COOKIE['archive_auth']); }
function require_login(): void {
    global $CFG;
    if (signed_in()) return;
    $error = '';
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['password'])) {
        if (($_POST['username'] ?? '') === $CFG['login_user'] && password_verify($_POST['password'], $CFG['login_hash'])) {
            setcookie('archive_auth', auth_token(), ['expires' => time() + 86400 * $CFG['cookie_days'], 'path' => '/', 'secure' => !empty($_SERVER['HTTPS']), 'httponly' => true, 'samesite' => 'Lax']);
            header('Location: ' . $_SERVER['REQUEST_URI']); exit;
        }
        $error = 'Wrong user name or password.';
    }
    http_response_code(401);
    ?><!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claude Archive - sign in</title>
<style>:root{--bg:#f3f4f7;--card:#fff;--ink:#171a21;--muted:#6b7280;--line:#e4e6eb;--accent:#2457d6}@media(prefers-color-scheme:dark){:root{--bg:#0e1014;--card:#161920;--ink:#e7e9ee;--muted:#9aa1ad;--line:#262b36;--accent:#86a8ff}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:16px/1.5 Inter,system-ui,sans-serif}
form{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:28px 30px;width:320px;display:flex;flex-direction:column;gap:12px}
h1{font-size:18px;margin:0 0 6px}label{font-size:16px;color:var(--muted)}input{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
button{padding:10px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer}.err{color:#b91c1c;font-size:16px}</style></head>
<body><form method="post" autocomplete="on"><h1>Claude Archive</h1>
<label>User name<input name="username" autocomplete="username" value="<?= htmlspecialchars($CFG['login_user']) ?>" required></label>
<label>Password<input type="password" name="password" autocomplete="current-password" required autofocus></label>
<?php if ($error) echo '<div class="err">' . $error . '</div>'; ?><button>Sign in</button></form></body></html><?php
    exit;
}
