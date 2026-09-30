set -e
for tf in 5 10 15; do python study.py primary $tf 2024; done
for s in geometry decomp dte splits volume dataset null grid; do echo "== $s"; python stages.py $s 2024; done
