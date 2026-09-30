for y in 2025 2026; do for t in 1 3 5 10 15; do python -c "import pipeline as P; b=P.build_bars($y,$t); print($y,$t,len(b),flush=True)" 2>&1 | grep -E "^20|Error|Traceback"; done; done
echo BUILD_END
