@echo off
REM Plain wipe: clears trade_order and journal_observation before a fresh backtest of the same window.
"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -proot moneymath -e "DELETE FROM journal_observation; DELETE FROM trade_order; SELECT COUNT(*) AS trade_order_rows FROM trade_order;"
echo.
echo Done. Ledger and journal cleared.
pause
