<?php
// Claude Archive viewer - settings.
// Copy this file to config.php, or run `php setup.php`, which asks for everything and writes config.php for you.
return [
    // Nextcloud: the same login the plugin uses (the "claude" user and its app password)
    'host'     => 'https://nextcloud.example.com',
    'user'     => 'claude',
    'password' => 'YOUR-NEXTCLOUD-APP-PASSWORD',
    'root'     => '/claude',                     // the archive folder, as the plugin user sees it (root_folder in the plugin's config.json)
    'timezone' => 'UTC',                         // IANA name, e.g. Europe/Berlin

    // Sign-in to the page (one user). login_hash = password_hash() of the page password; setup.php makes it.
    'login_user'  => 'admin',
    'login_hash'  => '',
    'cookie_days' => 365,                        // stay signed in this long

    // The plugin sends this token to refresh.php after every save (viewer_token in the plugin's config.json). setup.php makes it.
    'refresh_token' => '',

    // Where the data goes (keep it under data/, which .htaccess blocks from the web)
    'db'   => __DIR__ . '/data/archive.sqlite',

    // Top-level folders in the archive that are not projects
    'skip' => ['journal', '.state'],

    // Optional: group projects under a business or client name.
    // business_by_topic: regular expression on the thread topic => name. business_by_folder: folder-name prefix => name.
    // A folder that matches nothing is grouped under its first word.
    'business_by_topic'  => [
        // '/\bshop\b/i' => 'Web shop',
    ],
    'business_by_folder' => [
        // 'shop'       => 'Web shop',
        // 'recipe-app' => 'Recipe app',
    ],

    // Optional: how to show short words in project names (lowercase word => display form)
    'words' => ['ai' => 'AI', 'seo' => 'SEO', 'stl' => 'STL', 'step' => 'STEP'],
];
