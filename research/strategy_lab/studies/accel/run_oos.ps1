Set-Location 'D:\office\stocks\workspace\money-maker\research\strategy_lab\studies\accel'
$log = "results\log_oos.txt"
"start" | Out-File $log -Encoding ascii
"== primary 5 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py primary 5 2025 >> $log 2>&1"
"== primary 5 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py primary 5 2026 >> $log 2>&1"
"== primary 1 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py primary 1 2025 >> $log 2>&1"
"== primary 1 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py primary 1 2026 >> $log 2>&1"
"== options 5 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py options 5 2025 >> $log 2>&1"
"== options 5 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py options 5 2026 >> $log 2>&1"
"== null 5 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py null 5 2025 >> $log 2>&1"
"== null 5 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py null 5 2026 >> $log 2>&1"
"== grid 5 2025" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py grid 5 2025 >> $log 2>&1"
"== grid 5 2026" | Out-File $log -Append -Encoding ascii
cmd /c "python accel.py grid 5 2026 >> $log 2>&1"
"OOS_END" | Out-File $log -Append -Encoding ascii
