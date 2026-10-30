$ErrorActionPreference = "Continue"
Set-Location 'D:\office\stocks\workspace\money-maker\research\strategy_lab\studies\waves'
$log = "results\log_oos2.txt"
"start" | Out-File $log -Encoding ascii
"== study.py primary 5 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 5 2026 >> $log 2>&1"
"== study.py primary 1 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 1 2025 >> $log 2>&1"
"== study.py primary 3 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 3 2025 >> $log 2>&1"
"== study.py primary 10 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 10 2025 >> $log 2>&1"
"== study.py primary 15 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 15 2025 >> $log 2>&1"
"== study.py primary 1 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 1 2026 >> $log 2>&1"
"== study.py primary 3 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 3 2026 >> $log 2>&1"
"== study.py primary 10 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 10 2026 >> $log 2>&1"
"== study.py primary 15 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python study.py primary 15 2026 >> $log 2>&1"
"== stages.py geometry 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py geometry 2025 >> $log 2>&1"
"== stages.py decomp 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py decomp 2025 >> $log 2>&1"
"== stages.py dte 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py dte 2025 >> $log 2>&1"
"== stages.py splits 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py splits 2025 >> $log 2>&1"
"== stages.py volume 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py volume 2025 >> $log 2>&1"
"== stages.py dataset 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py dataset 2025 >> $log 2>&1"
"== stages.py geometry 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py geometry 2026 >> $log 2>&1"
"== stages.py decomp 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py decomp 2026 >> $log 2>&1"
"== stages.py dte 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py dte 2026 >> $log 2>&1"
"== stages.py splits 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py splits 2026 >> $log 2>&1"
"== stages.py volume 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py volume 2026 >> $log 2>&1"
"== stages.py dataset 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py dataset 2026 >> $log 2>&1"
"== stages.py null 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py null 2025 >> $log 2>&1"
"== stages.py null 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py null 2026 >> $log 2>&1"
"== stages.py grid 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py grid 2025 >> $log 2>&1"
"== stages.py grid 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python stages.py grid 2026 >> $log 2>&1"
"OOS_END" | Out-File $log -Append -Encoding ascii
