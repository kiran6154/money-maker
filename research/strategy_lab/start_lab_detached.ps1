# Strategy lab dashboard, started in the background so it keeps running after the terminal or Claude session closes.
#   powershell -ExecutionPolicy Bypass -File start_lab_detached.ps1            # this PC only, port 8770
#   powershell -ExecutionPolicy Bypass -File start_lab_detached.ps1 8770 --lan # also from a phone on the same Wi-Fi
# The same options as serve.py (see its header). Output goes to cache\serve.log; stop it from Task Manager (python.exe
# running serve.py) or with:  Stop-Process -Id (Get-Content cache\serve.pid)
param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $ServeArgs)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
if (-not $ServeArgs -or $ServeArgs.Count -eq 0) { $ServeArgs = @('8770') }
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force (Join-Path $here 'cache') | Out-Null
$log = Join-Path $here 'cache\serve.log'
$p = Start-Process -FilePath python -ArgumentList (@('-u', 'serve.py') + $ServeArgs) -WorkingDirectory $here `
     -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError (Join-Path $here 'cache\serve.err.log') -PassThru
$p.Id | Out-File -Encoding ascii (Join-Path $here 'cache\serve.pid')
"started serve.py (pid $($p.Id)); log: $log"
