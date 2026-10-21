<?php
// Tiny check the page makes every 20 seconds: returns the time the data was last rebuilt. Does not contact Nextcloud.
require_once __DIR__ . '/lib.php';
require_login();
header('Content-Type: text/plain'); header('Cache-Control: no-store');
echo @file_get_contents(dirname($CFG['db']) . '/stamp.txt') ?: '0';
