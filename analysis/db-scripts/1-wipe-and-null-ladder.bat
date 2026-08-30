@echo off
REM Run 2 prep: wipe ledger+journal, and NULL the ladder columns on the Jan-2024 window configs.
"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -proot moneymath -e "DELETE FROM journal_observation; DELETE FROM trade_order; UPDATE trade_config SET trail_ladder=NULL, max_sl_points=NULL WHERE id BETWEEN 1070 AND 1087; SELECT COUNT(*) AS trade_order_rows FROM trade_order; SELECT COUNT(*) AS nulled_configs FROM trade_config WHERE id BETWEEN 1070 AND 1087 AND trail_ladder IS NULL;"
echo.
echo Done. Tables wiped and ladder columns nulled on configs 1070-1087.
pause
