"""CHoCH to CHoCH put retest on the download store's option data (family module for ST147 - ST150).

Built 2026-10-26: the user sent "Nifty CHoCH to CHoCH in Plain English" again ("build this, check if this exists"). It does:
Strategies 25 - 28 (c2c.py) are that spec, but their option prices and open interest come from the lab's full-chain files,
which cover 2026-06-23 - 09-14 only (the "All data" runs skip 500+ signals). These four run c2c.run unchanged with the
option side read from the download store (D:/nifty_data, read only):
  expiries  every expiry folder of the store; "monthly" = the last of its calendar month
  candles   the contract's 1-minute rows (the regular strike files - within 250 pts of the index day range; the .wide files are
            left out to keep memory down), 09:15 - 15:29, de-duplicated,
            -> 5-minute candles 09:15-aligned (store_reader._candles)
  OI        the same rows' open_interest: the last print at or before the candle, the same session (c2c.OI.at)
  coverage  an expiry counts as covered when the store holds it (the regular files hold strikes within 250 pts of the
            index day range, so the PCR window of 300 pts is usually a little short of 13 strikes; min_strikes 9 as ST25)
Signals, entry and exits are c2c.py's (ST25 - ST28's settings: PCR on / off x stops on the close / touch).
"""
import glob
import os
import numpy as np
import pandas as pd
import core
import store_reader

C2C = core.family("c2c")
ENTRY_RULES, TYPES, TIMEFRAMES, OWN_COVERAGE, REFUSED_WHY, TF_WHY = C2C.ENTRY_RULES, C2C.TYPES, C2C.TIMEFRAMES, C2C.OWN_COVERAGE, C2C.REFUSED_WHY, C2C.TF_WHY
DAY = core.DAY


class StoreChain:
    """The c2c.run chain interface (expiry_for / name / get) on the download store."""
    _rows = {}

    def __init__(self):
        ex = store_reader.expiries()
        self.all = sorted(e["expiry"] for e in ex)
        self.monthly = sorted(e["expiry"] for e in ex if e["monthly"])
        self.d_all = np.array([core.dnum(e) for e in self.all]); self.d_mon = np.array([core.dnum(e) for e in self.monthly])
        self._bars = {}

    def expiry_for(self, day, min_days, kind="WEEKLY"):
        cal, cd = (self.monthly, self.d_mon) if kind == "MONTHLY" else (self.all, self.d_all)
        j = int(np.searchsorted(cd, day + min_days))
        return cal[j] if j < len(cal) else None

    name = staticmethod(core.OptionChain.name)

    @classmethod
    def rows(cls, exp):
        """Every 1-minute row of an expiry (datetime, strike, right, OHLCV, OI), regular + wide, cached (a few expiries)."""
        if exp in cls._rows: return cls._rows[exp]
        fs = [f for f in store_reader._exp_files(exp) if ".wide" not in f]       # regular strike files only (memory; see the module text)
        cls._rows.clear()
        parts = []
        for f in fs:
            x = pd.read_parquet(f, columns=["datetime", "strike", "right", "open", "high", "low", "close", "volume", "open_interest"])
            m = x.datetime.dt.hour * 60 + x.datetime.dt.minute
            x = x[(m >= 555) & (m <= 929)]
            parts.append(pd.DataFrame(dict(datetime=x.datetime.values, strike=x.strike.values.astype(np.int32), right=x.right.astype(str).values,
                                           open=x.open.values.astype(np.float32), high=x.high.values.astype(np.float32), low=x.low.values.astype(np.float32),
                                           close=x.close.values.astype(np.float32), volume=x.volume.values.astype(np.float32),
                                           open_interest=x.open_interest.values.astype(np.float32))))
        d = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if len(d):
            d["right"] = d.right.astype("category")
            d = d.sort_values("datetime").drop_duplicates(["datetime", "strike", "right"], keep="last")
        cls._rows[exp] = d
        return d

    def get(self, exp, k, right):
        key = (exp, int(k), right)
        if key not in self._bars:
            d = self.rows(exp)
            g = d[(d.strike == int(k)) & (d.right == right)] if len(d) else d
            c = store_reader._candles(g, "5minute", oi=False) if len(g) else []
            self._bars[key] = core.Bars(*(np.array([x[j] for x in c]) for j in range(6))) if c else None
        return self._bars[key]


class StoreOI(C2C.OI):
    """c2c.OI with series() read from the store's open_interest (1-minute prints)."""
    _ser = {}

    def series(self, e, right, k):
        key = (e, right, int(k))
        if key not in self._ser:
            d = StoreChain.rows(e)
            g = d[(d.strike == int(k)) & (d.right == right) & d.open_interest.notna()] if len(d) else d
            self._ser[key] = (g.datetime.values.astype("datetime64[s]").astype(np.int64), g.open_interest.values.astype(float)) if len(g) else None
        return self._ser[key]


def run(ctx):
    ch = StoreChain()
    have = set(ch.all)
    return C2C.run(ctx, data=(ch, StoreOI(), lambda e: e in have))


def signals(bars, spec):
    return C2C.signals(bars, spec)
