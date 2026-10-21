<?php
// One-time setup, run from the command line on the web host:  php setup.php
// Asks for the Nextcloud login and the page password, writes config.php (never the plain page password),
// makes the refresh token the plugin needs, creates data/ and builds the database once.
if (PHP_SAPI !== 'cli') { http_response_code(403); exit("Run this from the command line: php setup.php\n"); }
$dir = __DIR__;
$cfg = file_exists("$dir/config.php") ? require "$dir/config.php" : require "$dir/config.example.php";

function ask(string $label, string $default = '', bool $secret = false): string {
    $d = $default !== '' ? " [$default]" : '';
    echo "$label$d: ";
    if ($secret) { system('stty -echo 2>/dev/null'); $v = trim((string)fgets(STDIN)); system('stty echo 2>/dev/null'); echo "\n"; }
    else $v = trim((string)fgets(STDIN));
    return $v === '' ? $default : $v;
}

echo "Claude Archive viewer setup\n\n";
$cfg['host']     = rtrim(ask('Nextcloud URL', $cfg['host']), '/');
$cfg['user']     = ask('Nextcloud user the plugin logs in as', $cfg['user']);
$pw              = ask('That user\'s app password (leave empty to keep the current one)', '', true);
if ($pw !== '') $cfg['password'] = $pw;
$cfg['root']     = '/' . trim(ask('Archive folder name', trim($cfg['root'], '/')), '/');
$cfg['timezone'] = ask('Timezone (IANA name)', $cfg['timezone']);
$cfg['login_user'] = ask('Sign-in user name for the page', $cfg['login_user']);
$pp = ask('Sign-in password for the page (leave empty to keep the current one)', '', true);
if ($pp !== '' || $cfg['login_hash'] === '') {
    if ($pp === '') { echo "A page password is required.\n"; exit(1); }
    $cfg['login_hash'] = password_hash($pp, PASSWORD_DEFAULT);
}
if (empty($cfg['refresh_token'])) $cfg['refresh_token'] = bin2hex(random_bytes(24));
$cfg['db'] = '__DB__';

$out = "<?php\n// Claude Archive viewer - settings (written by setup.php; config.example.php explains every key)\nreturn " .
    str_replace("'__DB__'", "__DIR__ . '/data/archive.sqlite'", var_export($cfg, true)) . ";\n";
file_put_contents("$dir/config.php", $out);
@chmod("$dir/config.php", 0600);
@mkdir("$dir/data", 0755);
if (!file_exists("$dir/data/.htaccess")) file_put_contents("$dir/data/.htaccess", "Require all denied\n");

echo "\nconfig.php written.\n";
echo "Building the database from Nextcloud for the first time...\n";
passthru(PHP_BINARY . ' ' . escapeshellarg("$dir/import.php"), $rc);
if ($rc !== 0) echo "import.php reported a problem: check host, user, password and the archive folder name.\n";

echo "\nNow put these two lines into the plugin's config.json:\n";
echo '  "viewer_url": "https://<your web host>/<this folder>/refresh.php",' . "\n";
echo '  "viewer_token": "' . $cfg['refresh_token'] . '"' . "\n\n";
echo "Then add an hourly cron job as a safety net, for example:\n";
echo "  7 * * * * " . PHP_BINARY . " $dir/import.php > /dev/null 2>&1\n";
