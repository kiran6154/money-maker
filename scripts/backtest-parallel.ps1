<#
.SYNOPSIS
  Phase 10/12 parallel backtest driver (see docs/BACKTEST_PERFORMANCE.md).

  Splits [From..To] into contiguous chunks balanced by CONFIG-DAYS (only days
  with active trade_config rows cost anything), provisions one isolated MySQL
  schema per worker (historical candle tables shared read-only via views),
  launches K workers of the same jar, waits, and merges each worker's
  trade_order rows back into the source schema.

  Isolation is the point: OrderService's parallel/side caps, the strike
  pinning, and the S9 force-close sweep all read OPEN rows globally, so
  concurrent workers MUST NOT share a trade_order table. See the premortem in
  docs/BACKTEST_PERFORMANCE.md, Phase 10.

.EXAMPLE
  # Cold run, 3 workers, full-year, strategy 1 on its own configs:
  .\scripts\backtest-parallel.ps1 -From 2024-01-01 -To 2024-12-31 -StrategyIds 1 -ConfigStrategyId 1

.EXAMPLE
  # Warm mode (Phase 12): workers stay resident between runs and keep their
  # candle/SMA caches; later runs are driven over HTTP and skip JVM startup.
  .\scripts\backtest-parallel.ps1 -From 2024-01-01 -To 2024-12-31 -StrategyIds 1 -ConfigStrategyId 1 -Warm

.NOTES
  - Run AFTER config generation: the replay consumes configs, workers clone
    them at provision time. After regenerating configs, run once without
    -Warm (or with -Reprovision) so worker schemas pick up the new set.
  - Verification: replay the same window serially (the normal single app),
    then with this script, and byte-diff the ledgers per the parity checklist.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$From,
    [Parameter(Mandatory = $true)][string]$To,
    [int]$Workers = 3,
    [string]$StrategyIds = "",
    [string]$ConfigIds = "",
    [string]$ConfigStrategyId = "",
    [string]$Jar = "target\money-maker-1.0.0.jar",
    [string]$MySqlBin = "C:\Program Files\MySQL\MySQL Server 8.0\bin",
    [string]$DbHost = "localhost",
    [int]$DbPort = 3306,
    [string]$DbUser = "root",
    [string]$DbPassword = "root",
    [string]$SourceSchema = "moneymath",
    [int]$BasePort = 9101,
    [string]$JavaHeap = "512m",
    [switch]$Warm,
    [switch]$Reprovision,
    [switch]$KeepSchemas,
    [switch]$SkipMerge
)

$ErrorActionPreference = 'Stop'
$mysql = Join-Path $MySqlBin 'mysql.exe'
$mysqldump = Join-Path $MySqlBin 'mysqldump.exe'
if (-not (Test-Path $mysql)) { throw "mysql.exe not found at $mysql (set -MySqlBin)" }
if (-not (Test-Path $Jar)) { throw "jar not found at $Jar - build with: mvn -DskipTests package" }

$logDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

# Tables NOT copied into worker schemas: the two historical candle tables are
# replaced by views onto the source schema (read-only data, copied zero
# times); the rest must start EMPTY in a worker (its own ledger/journal).
$viewTables = @('historical_option_candles', 'historical_spot_candles')
$emptyTables = @('trade_order', 'journal_observation', 'market_data')

function Invoke-Sql {
    param([string]$Sql, [string]$Schema = '')
    $args = @("-h$DbHost", "-P$DbPort", "-u$DbUser", "-p$DbPassword", '-N', '-B', '-e', $Sql)
    if ($Schema) { $args += $Schema }
    $out = & $mysql @args
    if ($LASTEXITCODE -ne 0) { throw "mysql failed (exit $LASTEXITCODE): $Sql" }
    return $out
}

function Get-WorkerSchema { param([int]$i) return "${SourceSchema}_w$i" }
function Get-WorkerPort { param([int]$i) return $BasePort + $i }
function Get-JdbcUrl { param([string]$Schema)
    return "jdbc:mysql://${DbHost}:${DbPort}/${Schema}?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Kolkata&rewriteBatchedStatements=true"
}

function New-WorkerSchema {
    param([int]$i)
    $schema = Get-WorkerSchema $i
    Write-Host "[driver] provisioning schema $schema"
    Invoke-Sql "DROP DATABASE IF EXISTS $schema; CREATE DATABASE $schema"

    # Structure clone (no data). cmd.exe redirection keeps the byte stream
    # intact - PowerShell 5.1 pipes re-encode text.
    $dump = Join-Path $logDir "structure_$i.sql"
    cmd /c "`"$mysqldump`" -h$DbHost -P$DbPort -u$DbUser -p$DbPassword --no-data --skip-triggers $SourceSchema > `"$dump`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "mysqldump failed for $schema" }
    cmd /c "`"$mysql`" -h$DbHost -P$DbPort -u$DbUser -p$DbPassword $schema < `"$dump`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "structure import failed for $schema" }

    # Historical candles: view onto the source schema, never a copy.
    foreach ($t in $viewTables) {
        Invoke-Sql "DROP TABLE IF EXISTS $schema.$t; CREATE VIEW $schema.$t AS SELECT * FROM $SourceSchema.$t"
    }

    # Copy input data for everything else that has rows in the source.
    $exclude = ($viewTables + $emptyTables | ForEach-Object { "'$_'" }) -join ','
    $tables = @(Invoke-Sql "SELECT table_name FROM information_schema.tables WHERE table_schema='$SourceSchema' AND table_type='BASE TABLE' AND table_name NOT IN ($exclude)")
    foreach ($t in $tables) {
        if (-not $t) { continue }
        Invoke-Sql "SET FOREIGN_KEY_CHECKS=0; INSERT INTO $schema.$t SELECT * FROM $SourceSchema.$t; SET FOREIGN_KEY_CHECKS=1"
    }
    Write-Host "[driver] $schema ready ($($tables.Count) tables copied, $($viewTables.Count) views)"
}

function Start-Worker {
    param([int]$i, [string]$ChunkFrom, [string]$ChunkTo, [bool]$Resident)
    $schema = Get-WorkerSchema $i
    $port = Get-WorkerPort $i
    $javaArgs = @(
        "-Xmx$JavaHeap", '-jar', $Jar,
        "--server.port=$port",
        "--spring.datasource.url=$(Get-JdbcUrl $schema)",
        "--spring.datasource.username=$DbUser",
        "--spring.datasource.password=$DbPassword",
        '--spring.liquibase.enabled=false',
        '--spring.jpa.hibernate.ddl-auto=none',
        '--app.mode=backtest',
        '--logging.level.com.moneymaker=INFO'
    )
    if (-not $Resident) {
        $javaArgs += @(
            '--backtest.autorun.enabled=true',
            "--backtest.autorun.from=$ChunkFrom",
            "--backtest.autorun.to=$ChunkTo"
        )
        if ($StrategyIds) { $javaArgs += "--backtest.autorun.strategy-ids=$StrategyIds" }
        if ($ConfigIds) { $javaArgs += "--backtest.autorun.config-ids=$ConfigIds" }
        if ($ConfigStrategyId) { $javaArgs += "--backtest.autorun.config-strategy-id=$ConfigStrategyId" }
    }
    $out = Join-Path $logDir "worker_$i.log"
    $err = Join-Path $logDir "worker_$i.err.log"
    Write-Host "[driver] worker $i -> schema=$schema port=$port range=$ChunkFrom..$ChunkTo resident=$Resident"
    return Start-Process -FilePath 'java' -ArgumentList $javaArgs `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
}

function Test-WorkerUp {
    param([int]$i)
    try {
        Invoke-RestMethod -Uri "http://localhost:$(Get-WorkerPort $i)/api/session" -TimeoutSec 3 | Out-Null
        return $true
    } catch { return $false }
}

function Merge-Worker {
    param([int]$i)
    $schema = Get-WorkerSchema $i
    $cols = (Invoke-Sql "SELECT GROUP_CONCAT(column_name ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='$schema' AND table_name='trade_order' AND column_name <> 'id'")
    $n = (Invoke-Sql "SELECT COUNT(*) FROM $schema.trade_order")
    if ([int]$n -gt 0) {
        Invoke-Sql "INSERT INTO $SourceSchema.trade_order ($cols) SELECT $cols FROM $schema.trade_order"
    }
    $j = (Invoke-Sql "SELECT COUNT(*) FROM $schema.journal_observation")
    if ([int]$j -gt 0) {
        $jcols = (Invoke-Sql "SELECT GROUP_CONCAT(column_name ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='$schema' AND table_name='journal_observation' AND column_name <> 'id'")
        Invoke-Sql "INSERT INTO $SourceSchema.journal_observation ($jcols) SELECT $jcols FROM $schema.journal_observation"
    }
    Write-Host "[driver] merged worker ${i}: trade_order=$n journal=$j"
    return [int]$n
}

# ---------------------------------------------------------------------------
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# 1. Chunk by config-days.
$dates = @(Invoke-Sql "SELECT DISTINCT trading_date FROM trade_config WHERE is_active=1 AND trading_date BETWEEN '$From' AND '$To' ORDER BY trading_date")
if ($dates.Count -eq 0) { throw "no active trade_config rows in [$From..$To] - generate configs first" }
if ($Workers -gt $dates.Count) { $Workers = $dates.Count }
$per = [Math]::Ceiling($dates.Count / $Workers)
$chunks = @()
for ($i = 0; $i -lt $Workers; $i++) {
    $s = $i * $per
    $e = [Math]::Min(($i + 1) * $per, $dates.Count) - 1
    if ($s -le $e) { $chunks += , @($dates[$s], $dates[$e]) }
}
$Workers = $chunks.Count
Write-Host "[driver] $($dates.Count) config-days in [$From..$To] -> $Workers chunk(s): $(($chunks | ForEach-Object { ""$($_[0])..$($_[1])"" }) -join ' | ')"

if ($Warm) {
    # Phase 12: resident workers, HTTP-driven, caches kept across runs.
    $started = @()
    for ($i = 0; $i -lt $Workers; $i++) {
        if ((Test-WorkerUp $i) -and (-not $Reprovision)) {
            Write-Host "[driver] worker $i already resident - reusing (schema NOT reprovisioned; use -Reprovision after config changes)"
        } else {
            New-WorkerSchema $i
            $started += Start-Worker $i '' '' $true
        }
    }
    foreach ($i in 0..($Workers - 1)) {
        $tries = 0
        while (-not (Test-WorkerUp $i)) {
            Start-Sleep -Seconds 2
            $tries++
            if ($tries -gt 90) { throw "worker $i did not come up on port $(Get-WorkerPort $i) - see scripts\logs\worker_$i.log" }
        }
    }
    # Reset each worker's ledger so re-runs start clean (worker schemas are
    # ephemeral driver artifacts; the source schema is never touched here).
    for ($i = 0; $i -lt $Workers; $i++) {
        Invoke-Sql "DELETE FROM $(Get-WorkerSchema $i).trade_order; DELETE FROM $(Get-WorkerSchema $i).journal_observation"
    }
    $jobs = @()
    for ($i = 0; $i -lt $Workers; $i++) {
        $chunk = $chunks[$i]
        $url = "http://localhost:$(Get-WorkerPort $i)/api/backtest/analysis?fromDate=$($chunk[0])&toDate=$($chunk[1])"
        if ($StrategyIds) { $url += "&strategyIds=$StrategyIds" }
        if ($ConfigIds) { $url += "&configIds=$ConfigIds" }
        if ($ConfigStrategyId) { $url += "&configStrategyId=$ConfigStrategyId" }
        Write-Host "[driver] worker $i <- POST $url"
        $jobs += Start-Job -ScriptBlock {
            param($u)
            Invoke-RestMethod -Method Post -Uri $u -TimeoutSec 86400
        } -ArgumentList $url
    }
    $jobs | Wait-Job | Out-Null
    $failed = 0
    foreach ($job in $jobs) {
        if ($job.State -ne 'Completed') { $failed++; Receive-Job $job -ErrorAction SilentlyContinue | Out-Host }
    }
    $jobs | Remove-Job -Force
    if ($failed -gt 0) { Write-Warning "$failed worker request(s) failed - check scripts\logs" }
} else {
    # Cold mode: provision fresh, autorun, exit.
    for ($i = 0; $i -lt $Workers; $i++) { New-WorkerSchema $i }
    $procs = @()
    for ($i = 0; $i -lt $Workers; $i++) {
        $chunk = $chunks[$i]
        $procs += Start-Worker $i $chunk[0] $chunk[1] $false
        Start-Sleep -Seconds 3   # stagger startup - 2C/4T box, shared MySQL
    }
    $procs | Wait-Process
    for ($i = 0; $i -lt $Workers; $i++) {
        $code = $procs[$i].ExitCode
        if ($code -ne 0) { Write-Warning "worker $i exited with code $code - see scripts\logs\worker_$i.log" }
        else { Write-Host "[driver] worker $i finished ok" }
    }
}

# 3. Merge ledgers back (chunks are entry-time disjoint by construction).
$total = 0
if (-not $SkipMerge) {
    for ($i = 0; $i -lt $Workers; $i++) { $total += Merge-Worker $i }
}

# 4. Cleanup.
if ((-not $KeepSchemas) -and (-not $Warm)) {
    for ($i = 0; $i -lt $Workers; $i++) { Invoke-Sql "DROP DATABASE IF EXISTS $(Get-WorkerSchema $i)" }
    Write-Host "[driver] worker schemas dropped (use -KeepSchemas to keep for inspection)"
}

$sw.Stop()
Write-Host ("[driver] DONE in {0:n1}s - {1} trade_order row(s) merged into {2}" -f $sw.Elapsed.TotalSeconds, $total, $SourceSchema)
