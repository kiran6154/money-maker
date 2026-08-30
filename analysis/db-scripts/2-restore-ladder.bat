@echo off
REM Run 2 cleanup: restore the seeded ladder + ceiling on the Jan-2024 window configs.
"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -proot moneymath -e "UPDATE trade_config SET trail_ladder='25:2,50:25,75:50,100:75', max_sl_points=60 WHERE id BETWEEN 1070 AND 1087; SELECT COUNT(*) AS restored FROM trade_config WHERE id BETWEEN 1070 AND 1087 AND trail_ladder='25:2,50:25,75:50,100:75' AND max_sl_points=60;"
echo.
echo Done. Ladder and ceiling restored on configs 1070-1087.
pause
