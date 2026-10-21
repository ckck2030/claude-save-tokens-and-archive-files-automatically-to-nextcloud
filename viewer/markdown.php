<?php
// Small Markdown-to-HTML renderer (headings, lists, bold/italic, links, code, tables, quotes). No dependencies.
function md_inline(string $s): string {
    $s = htmlspecialchars($s, ENT_QUOTES);
    $s = preg_replace('/`([^`]+)`/', '<code>$1</code>', $s);
    $s = preg_replace('/\*\*(.+?)\*\*/s', '<strong>$1</strong>', $s);
    $s = preg_replace('/(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/s', '<em>$1</em>', $s);
    $s = preg_replace('/\[([^\]]+)\]\(([^)\s]+)\)/', '<a href="$2" target="_blank">$1</a>', $s);
    $s = preg_replace('~(?<!["\'>=])\bhttps?://[^\s<)]+~', '<a href="$0" target="_blank">$0</a>', $s);
    return $s;
}
function md_html(string $md): string {
    $lines = preg_split('/\r?\n/', $md);
    $out = []; $i = 0; $n = count($lines);
    while ($i < $n) {
        $l = $lines[$i];
        if (preg_match('/^```/', $l)) { $buf = []; $i++;
            while ($i < $n && !preg_match('/^```/', $lines[$i])) $buf[] = $lines[$i++];
            $i++; $out[] = '<pre><code>' . htmlspecialchars(implode("\n", $buf)) . '</code></pre>'; continue; }
        if (preg_match('/^(#{1,6})\s+(.*)$/', $l, $m)) { $h = strlen($m[1]); $out[] = "<h$h>" . md_inline($m[2]) . "</h$h>"; $i++; continue; }
        if (preg_match('/^\s*[-*_]{3,}\s*$/', $l)) { $out[] = '<hr>'; $i++; continue; }
        if (preg_match('/^\|/', $l) && $i + 1 < $n && preg_match('/^\|?\s*:?-+/', $lines[$i + 1])) {
            $cells = fn($r) => array_map('trim', explode('|', trim(trim($r), '|')));
            $t = '<table><tr>' . implode('', array_map(fn($c) => '<th>' . md_inline($c) . '</th>', $cells($l))) . '</tr>'; $i += 2;
            while ($i < $n && preg_match('/^\|/', $lines[$i])) $t .= '<tr>' . implode('', array_map(fn($c) => '<td>' . md_inline($c) . '</td>', $cells($lines[$i++]))) . '</tr>';
            $out[] = $t . '</table>'; continue; }
        if (preg_match('/^(\s*)([-*+]|\d+\.)\s+/', $l, $m)) {
            $tag = ctype_digit($m[2][0]) ? 'ol' : 'ul'; $items = []; $base = strlen($m[1]);
            while ($i < $n && preg_match('/^(\s*)([-*+]|\d+\.)\s+(.*)$/', $lines[$i], $mm)) {
                $depth = intdiv(max(0, strlen($mm[1]) - $base), 2); $items[] = [$depth, $mm[3]]; $i++;
                while ($i < $n && preg_match('/^\s{2,}(?![-*+]|\d+\.)(\S.*)$/', $lines[$i], $c)) { $items[count($items) - 1][1] .= ' ' . $c[1]; $i++; }
            }
            $h = "<$tag>"; $cur = 0;
            foreach ($items as [$d, $txt]) {
                if ($d > $cur) { $h .= str_repeat('<ul>', $d - $cur); } elseif ($d < $cur) { $h .= str_repeat('</li></ul>', $cur - $d) . '</li>'; } elseif ($h !== "<$tag>") $h .= '</li>';
                $h .= '<li>' . md_inline($txt); $cur = $d;
            }
            $out[] = $h . str_repeat('</li></ul>', $cur) . "</li></$tag>"; continue; }
        if (preg_match('/^>\s?(.*)$/', $l)) { $buf = [];
            while ($i < $n && preg_match('/^>\s?(.*)$/', $lines[$i], $q)) { $buf[] = $q[1]; $i++; }
            $out[] = '<blockquote>' . md_html(implode("\n", $buf)) . '</blockquote>'; continue; }
        if (trim($l) === '') { $i++; continue; }
        $buf = [];
        while ($i < $n && trim($lines[$i]) !== '' && !preg_match('/^(#{1,6}\s|```|\||\s*([-*+]|\d+\.)\s|>)/', $lines[$i])) $buf[] = $lines[$i++];
        $out[] = '<p>' . md_inline(implode("\n", $buf)) . '</p>';
    }
    return implode("\n", $out);
}
