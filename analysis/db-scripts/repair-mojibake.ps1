# One-time repair: reverses cp1252->UTF-8 double encoding introduced by
# Get-Content (ANSI read) + UTF-8 rewrite passes on 2026-08-31.
# Only multi-char runs of cp1252-representable non-ASCII chars are re-decoded;
# a run whose reversal is invalid UTF-8 is left untouched, so cleanly written
# single characters cannot be damaged.
$cp1252 = [System.Text.Encoding]::GetEncoding(1252)
$utf8 = New-Object System.Text.UTF8Encoding($false)
$extras = @(0x0152,0x0153,0x0160,0x0161,0x0178,0x017D,0x017E,0x0192,0x02C6,0x02DC,
            0x2013,0x2014,0x2018,0x2019,0x201A,0x201C,0x201D,0x201E,0x2020,0x2021,
            0x2022,0x2026,0x2030,0x2039,0x203A,0x20AC,0x2122) |
           ForEach-Object { [string]::Format('\u{0:X4}', $_) }
$runPattern = '[\u0080-\u00FF' + ($extras -join '') + ']{2,}'
$lead = [regex] '\u00E2|\u00C3\u2014|\u00C2\u00B7'
foreach ($f in $args) {
    $t = [System.IO.File]::ReadAllText($f)
    $before = $lead.Matches($t).Count
    $repaired = [regex]::Replace($t, $runPattern, {
        param($m)
        $bytes = $cp1252.GetBytes($m.Value)
        $cand = [System.Text.Encoding]::UTF8.GetString($bytes)
        if ($cand.Contains([char]0xFFFD)) { return $m.Value } else { return $cand }
    })
    [System.IO.File]::WriteAllText($f, $repaired, $utf8)
    $after = $lead.Matches([System.IO.File]::ReadAllText($f)).Count
    Write-Output ("{0} : {1} -> {2}" -f $f, $before, $after)
}
