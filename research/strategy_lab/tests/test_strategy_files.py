"""Strategy files keep their own layout when a backtest is added (lab.insert_backtest, used by `lab.py backtest` and the
dashboard queue): exactly one line is added after the last backtest, in the style of its neighbours, and the file stays
valid JSON with the same content otherwise. Runs on copies of every file in strategies/.

    python tests/test_strategy_files.py
"""
import glob, json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab  # noqa: E402

fails, tmp = [], tempfile.mkdtemp()
new = {"label": "Test 1Y", "kind": "preset", "preset": "1Y", "underlying": "INDEX"}
for src in sorted(glob.glob(os.path.join(lab.STRATDIR, "*.json"))):
    dst = os.path.join(tmp, os.path.basename(src)); shutil.copy(src, dst)
    before = open(src, encoding="utf-8", newline="").read()
    lab.insert_backtest(dst, new)
    after = open(dst, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in before else "\n"
    a, b = before.split(nl), after.split(nl)
    name = os.path.basename(src)
    k = next((i for i, ln in enumerate(b) if '"Test 1Y"' in ln), None)
    if len(b) != len(a) + 1 or k is None: fails.append(f"{name}: {len(b) - len(a)} lines added, want exactly the new backtest")
    else:
        undone = b[:k] + b[k + 1:]
        undone[k - 1] = undone[k - 1][:-1] if undone[k - 1].endswith(",") else undone[k - 1]   # the comma the insert added
        if undone != a: fails.append(f"{name}: lines other than the new backtest (and one comma) changed")
    ja, jb = json.loads(before), json.loads(after)
    if jb["backtests"][:-1] != ja["backtests"] or jb["backtests"][-1] != new or {k: v for k, v in jb.items() if k != "backtests"} != {k: v for k, v in ja.items() if k != "backtests"}:
        fails.append(f"{name}: content changed beyond the new backtest")
shutil.rmtree(tmp)
print("\n".join(fails) if fails else f"OK - strategy files keep their layout ({len(glob.glob(os.path.join(lab.STRATDIR, '*.json')))} files)")
sys.exit(1 if fails else 0)
