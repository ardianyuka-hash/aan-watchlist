"""Watchlist ARA 2026 — memakai indikator proyek trading (HASIL ANALISA/script/backtest.py + aturan A/B engine.py).

Alur:
1. Unduh OHLCV harian seluruh emiten BEI (Yahoo `.JK`, yfinance) + IHSG (^JKSE) -> cache data/prices.parquet.
2. Hitung indikator & sinyal PERSIS dari backtest.indicators()/signals() + aturan A & B (engine.py).
3. Tandai hari ARA (batas 35%/25%/20% sesuai harga kemarin, dibulatkan ke fraksi harga BEI).
4. Statistik 2026: untuk tiap indikator, peluang saham ARA dalam 1 dan 5 hari bursa berikutnya vs baseline (lift).
5. Skor ARA hari ini = jumlah log2(lift) indikator yang menyala (hanya lift > 1).
   Validasi jujur: lift dihitung Jan–Jun 2026, skor diuji Jul 2026 – sekarang (out-of-sample).
6. Tulis dashboard HTML (hasil/Watchlist_ARA_2026_<tanggal>.html + watchlist_ara_2026.html).

Pakai:
  py watchlist_ara.py              # unduh data terbaru lalu buat dashboard
  py watchlist_ara.py --no-fetch   # pakai cache
  py watchlist_ara.py --minval 5e8 # filter nilai transaksi 20h (default Rp1 M)
"""
import argparse, importlib.util, json, sys, time, webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
TRADING = BASE.parent
SCRIPT = TRADING / "HASIL ANALISA" / "script"
VENDOR = BASE / "vendor"   # salinan untuk GitHub Actions (di PC dipakai file asli proyek bila ada)
WIB = timezone(timedelta(hours=7))
MIN_SAHAM = 600            # pengaman: unduhan Yahoo yang gagal sebagian tidak boleh menimpa dashboard


def src(*cands):
    for c in cands:
        if c.exists():
            return c
    raise FileNotFoundError(cands[-1])


DATA = BASE / "data"
HASIL = BASE / "hasil"
PRICES = DATA / "prices.parquet"
START = "2024-10-01"          # warm-up MA200/Ichimoku sebelum 2026
YEAR0 = pd.Timestamp("2026-01-01")
SPLIT = pd.Timestamp("2026-07-01")  # IS: Jan–Jun 2026, OOS: Jul 2026 – sekarang

# --- impor indikator proyek apa adanya
_spec = importlib.util.spec_from_file_location("bt", src(SCRIPT / "backtest.py", VENDOR / "backtest.py"))
bt = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bt)

# Indikator yang dipakai (nama di backtest.py -> kode singkat)
SIG = {
    "Breakout 20h + volume >=1.5x avg5 (Mega Profit)": "BO20V",
    "Channel breakout 40 hari (close > high 40h)": "CH40",
    "Volatility breakout (C-Cprev > 0.8 ATR)": "VOLBO",
    "Ichimoku ideal (4 syarat)": "ICHI",
    "KOMBO: Ichimoku ideal + breakout 20h + volume 1.5x": "KOMBO",
    "KOMBO: tren naik + vol breakout 0.8ATR + volume 1.5x": "TRVB",
    "ADX naik ke high 10 hari, ADX>15, +DI>-DI": "ADX",
    "Close di 10% teratas range harian": "CTOP",
    "RSI14 < 30 (oversold)": "RSI30",
    "Ichimoku: Tenkan cross Kijun di atas kumo": "TKX",
}
LABEL = {
    "BO20V": "Breakout 20h + volume ≥1,5x avg5 (Mega Profit)",
    "CH40": "Channel breakout 40 hari",
    "VOLBO": "Volatility breakout (C−Cprev > 0,8 ATR)",
    "ICHI": "Ichimoku ideal (4 syarat)",
    "KOMBO": "KOMBO Ichimoku ideal + breakout 20h + volume",
    "TRVB": "KOMBO tren naik (MA stack) + vol breakout + volume",
    "ADX": "ADX naik ke high 10h, ADX>15, +DI>−DI",
    "CTOP": "Close di 10% teratas range harian",
    "RSI30": "RSI14 tembus < 30",
    "TKX": "Ichimoku Tenkan cross Kijun di atas kumo",
    "ATRB": "Aturan B: close > high 55h + volume ≥3x avg20 + IHSG > MA50",
    "ATRA": "Aturan A: RSI(5) < 20 + close > MA200 (pullback)",
    "ARA0": "ARA hari ini (potensi ARA beruntun)",
    "ARA20": "Pernah ARA dalam 20 hari terakhir",
    "UP10": "Naik ≥10% hari ini (belum ARA)",
    "VOL3": "Volume ≥3x rata-rata 20 hari",
}
GROUP = {k: "Indikator proyek" for k in list(SIG.values()) + ["ATRB", "ATRA"]}
GROUP.update({k: "Perilaku harga" for k in ["ARA0", "ARA20", "UP10", "VOL3"]})
FEATS = list(LABEL)


# ---------------------------------------------------------------- data
def load_codes():
    t = src(TRADING / "screener-cangkang" / "idx_codes.txt", VENDOR / "idx_codes.txt").read_text().split()
    codes = t[0::2]
    pp = set(src(SCRIPT / "pp_codes.txt", VENDOR / "pp_codes.txt").read_text().split())
    names = {}
    nf = Path.home() / "idx_downloader" / "emiten_cache.csv"
    nf = nf if nf.exists() else VENDOR / "emiten.csv"
    if nf.exists():
        n = pd.read_csv(nf, encoding="utf-8-sig")
        names = dict(zip(n.kode, n.nama))
    return codes, pp, set(bt.TICKERS), names


def fetch(codes, log=print):
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # emiten delisting/suspend -> diam saja
    frames = []
    allc = [c + ".JK" for c in codes] + ["^JKSE"]
    for i in range(0, len(allc), 100):
        tk = allc[i:i + 100]
        for attempt in range(3):
            try:
                d = yf.download(tk, start=START, group_by="ticker", auto_adjust=False, progress=False, threads=True)
                break
            except Exception as e:  # jaringan
                log(f"  ulang batch {i}: {e}"); time.sleep(5)
        else:
            continue
        lv = d.columns.get_level_values(0)
        for c in tk:
            if c in lv:
                x = d[c].dropna(how="all").copy()
                if len(x):
                    x["code"] = "IHSG" if c == "^JKSE" else c[:-3]
                    frames.append(x.reset_index())
        log(f"  unduh {min(i + 100, len(allc))}/{len(allc)}")
        time.sleep(1.5)
    p = pd.concat(frames)
    p.columns = [str(c).lower().replace(" ", "_") for c in p.columns]
    p = p[["date", "open", "high", "low", "close", "volume", "code"]]
    DATA.mkdir(exist_ok=True)
    p.to_parquet(PRICES)
    return p


# ---------------------------------------------------------------- aturan harga BEI
def ara_limit(pc):
    return np.where(pc <= 200, 0.35, np.where(pc <= 5000, 0.25, 0.20))


def tick(p):
    return np.select([p < 200, p < 500, p < 2000, p < 5000], [1, 2, 5, 10], 25)


def ara_price(pc):
    raw = pc * (1 + ara_limit(pc))
    t = tick(raw)
    return np.floor(raw / t + 1e-9) * t


# ---------------------------------------------------------------- fitur per saham
def features(d, ix):
    d = d.sort_index()
    d = d[(d.volume > 0) & (d.high >= d.low) & (d.close > 0)]
    d = d[~d.index.duplicated(keep="last")]
    if len(d) < 80:
        return None
    d = bt.indicators(d.copy())
    S = bt.signals(d)
    o, h, l, c, v = d.open, d.high, d.low, d.close, d.volume
    pc = c.shift()
    f = pd.DataFrame(index=d.index)
    f["o"], f["h"], f["l"], f["c"], f["v"] = o, h, l, c, v
    f["chg"] = c / pc - 1
    f["arapx"] = ara_price(pc.fillna(c).values)
    lim = ara_limit(pc.fillna(c).values)
    f["ara"] = ((c >= f.arapx) | (f.chg >= lim - 0.01)) & pc.notna()
    f["val20"] = (c * v).rolling(20).mean()
    f["volx"] = v / d.vavg20
    f["rsi14"] = d.rsi
    f["rsi5"] = bt_rsi(c, 5)
    f["atrp"] = d.atr / c
    f["dist_hh20"] = c / h.rolling(20).max().shift() - 1
    for name, k in SIG.items():
        f[k] = S[name]
    # Aturan A & B (Pengembangan_Edge_RSI_Breakout / engine.py)
    f["ATRA"] = (f.rsi5 < 20) & (c > d.ma200)
    f["ATRB"] = (c > h.rolling(55).max().shift()) & (v >= 3 * d.vavg20) & ix.reindex(f.index).ffill().fillna(False).astype(bool)
    f["ARA0"] = f.ara
    f["ARA20"] = f.ara.astype(int).rolling(20, min_periods=1).max().astype(bool)
    f["UP10"] = (f.chg >= 0.10) & ~f.ara
    f["VOL3"] = f.volx >= 3
    for k in FEATS:
        f[k] = f[k].fillna(False).astype(bool)
    a = f.ara.astype(float)
    f["y1"] = a.shift(-1)
    f["y5"] = a[::-1].rolling(5, min_periods=5).max()[::-1].shift(-1)
    f["mx5"] = h[::-1].rolling(5, min_periods=5).max()[::-1].shift(-1) / c - 1
    # streak ARA
    g = (~f.ara).cumsum()
    f["streak"] = f.ara.astype(int).groupby(g).cumsum()
    f["i"] = np.arange(len(f))
    return f


def bt_rsi(c, n):
    dl = c.diff()
    up = dl.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-dl.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


# ---------------------------------------------------------------- statistik
def lift_table(P, mask):
    x = P[mask & P.y5.notna()]
    b1, b5 = x.y1.mean(), x.y5.mean()
    rows = []
    for k in FEATS:
        s = x[x[k]]
        n = len(s)
        p1 = s.y1.mean() if n else np.nan
        p5 = s.y5.mean() if n else np.nan
        rows.append(dict(kode=k, label=LABEL[k], grup=GROUP[k], n=n, saham=int(s.code.nunique()) if n else 0,
                         p1=p1, p5=p5, lift1=p1 / b1 if n else np.nan, lift5=p5 / b5 if n else np.nan,
                         mx5=s.mx5.median() if n else np.nan))
    return pd.DataFrame(rows), b1, b5, len(x)


def score_frame(P, lt):
    w = {r.kode: max(0.0, np.log2(r.lift5)) if r.n >= 30 and np.isfinite(r.lift5) else 0.0 for r in lt.itertuples()}
    s = np.zeros(len(P))
    for k, wk in w.items():
        if wk > 0:
            s += P[k].values * wk
    return s, w


def validate(P, ok):
    """Lift dari IS (Jan–Jun 2026), uji top-N harian di OOS (Jul 2026 – sekarang)."""
    lt, *_ = lift_table(P, ok & (P.date >= YEAR0) & (P.date < SPLIT))
    s, _ = score_frame(P, lt)
    Q = P.assign(score=s)[ok & (P.date >= SPLIT) & P.y5.notna()]
    base5, base1 = Q.y5.mean(), Q.y1.mean()
    out = []
    for N in (5, 10, 20, 50):
        top = Q[Q.score > 0].sort_values("score", ascending=False).groupby("date").head(N)
        out.append(dict(top=N, n=len(top), hari=int(top.date.nunique()), p1=top.y1.mean(), p5=top.y5.mean(),
                        lift5=top.y5.mean() / base5, mx5=top.mx5.median()))
    return dict(rows=out, base1=base1, base5=base5, n=len(Q),
                dari=str(Q.date.min().date()) if len(Q) else "", sampai=str(Q.date.max().date()) if len(Q) else "")


def publish(last_day):
    """Kirim dashboard terbaru ke GitHub Pages: https://ardianyuka-hash.github.io/aan-watchlist/"""
    import subprocess
    run = lambda *c: subprocess.run(["git", *c], cwd=BASE, capture_output=True, text=True)
    run("add", "-A")
    r = run("commit", "-m", f"Update data {last_day.date()}")
    if "nothing to commit" in r.stdout:
        print("GitHub: tidak ada perubahan.")
        return
    run("pull", "--rebase", "-X", "theirs")  # GitHub Actions mungkin sudah update duluan; versi PC menang
    r = run("push")
    print("GitHub: terkirim ✔ (halaman online ±1 menit lagi)" if r.returncode == 0 else "GitHub GAGAL: " + r.stderr[-300:])


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--minval", type=float, default=1e9)
    ap.add_argument("--minpx", type=float, default=50)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--publish", action="store_true", help="commit & push index.html ke GitHub (aan-watchlist)")
    a = ap.parse_args()
    t0 = time.time()
    codes, pp, lq45, names = load_codes()
    if a.no_fetch and PRICES.exists():
        print("Pakai cache", PRICES)
        p = pd.read_parquet(PRICES)
    else:
        print(f"Unduh {len(codes)} emiten + IHSG dari Yahoo ...")
        p = fetch(codes)
    p["date"] = pd.to_datetime(p.date).dt.tz_localize(None).dt.normalize()
    ihsg = p[p.code == "IHSG"].set_index("date").close.sort_index()
    ix_ok = ihsg > ihsg.rolling(50).mean()
    last_day = p[p.code != "IHSG"].date.max()
    print("Data sampai", last_day.date())

    F, spark = [], {}
    for code, g in p[p.code != "IHSG"].groupby("code"):
        f = features(g.set_index("date")[["open", "high", "low", "close", "volume"]].astype(float), ix_ok)
        if f is None:
            continue
        f["code"] = code
        F.append(f.reset_index(names="date"))
        tail = f.tail(60)
        spark[code] = [tail.index.strftime("%Y-%m-%d").tolist(), tail.c.round(2).tolist(), tail.ara.astype(int).tolist()]
    P = pd.concat(F, ignore_index=True)
    n_now = P[P.date == last_day].code.nunique()
    if n_now < MIN_SAHAM:
        sys.exit(f"GAGAL: hanya {n_now} saham punya data {last_day.date()} (< {MIN_SAHAM}). Dashboard tidak ditimpa — coba lagi nanti.")
    print(f"{P.code.nunique()} saham, {len(P):,} baris — {time.time() - t0:.0f} dtk")

    ok = (P.val20 >= a.minval) & (P.c > a.minpx) & (P.i >= 60)
    # --- statistik 2026 (seluruh 2026, dipakai untuk skor hari ini)
    lt, b1, b5, nobs = lift_table(P, ok & (P.date >= YEAR0))
    P["score"], W = score_frame(P, lt)
    val = validate(P, ok)
    # peluang empiris per kelompok skor (2026)
    Z = P[ok & (P.date >= YEAR0) & P.y5.notna()]
    bins = [-0.01, 0.0, 1, 2, 3, 4, 100]
    labs = ["0", "0–1", "1–2", "2–3", "3–4", ">4"]
    Z = Z.assign(b=pd.cut(Z.score, bins, labels=labs))
    sb = Z.groupby("b", observed=False).agg(n=("y5", "size"), p1=("y1", "mean"), p5=("y5", "mean"), mx5=("mx5", "median")).reset_index()
    pmap = dict(zip(sb.b.astype(str), sb.p5))

    # --- kandidat hari ini (bar terakhir per saham = hari bursa terakhir)
    L = P[P.date == last_day].copy()
    prev = P[P.date < last_day].groupby("code").tail(1).set_index("code")
    cand = []
    for r in L.itertuples():
        on = [k for k in FEATS if getattr(r, k)]
        hist = P[(P.code == r.code) & (P.date >= YEAR0) & P.ara]
        b = labs[np.searchsorted(bins, r.score, side="left") - 1] if r.score > 0 else "0"
        cand.append(dict(
            kode=r.code, nama=names.get(r.code, ""), papan="LQ45" if r.code in lq45 else ("Pengembangan" if r.code in pp else "Lainnya"),
            harga=r.c, chg=r.chg, ara=bool(r.ara), streak=int(r.streak), arapx_hari_ini=float(r.arapx),
            arapx_besok=float(ara_price(np.array([r.c]))[0]), ke_ara=float(ara_price(np.array([r.c]))[0] / r.c - 1),
            volx=None if not np.isfinite(r.volx) else round(float(r.volx), 2), val20=r.val20, rsi14=r.rsi14, rsi5=r.rsi5,
            atrp=r.atrp, dhh20=r.dist_hh20, skor=round(float(r.score), 3), p5=pmap.get(b), sinyal=on,
            likuid=bool(r.val20 >= a.minval and r.c > a.minpx),
            ara2026=int(len(hist)), ara_terakhir=str(hist.date.max().date()) if len(hist) else "",
        ))
    cand = sorted(cand, key=lambda x: -x["skor"])

    # --- riwayat ARA 2026
    E = P[(P.date >= YEAR0) & P.ara].copy()
    events = []
    by_code = {c: g.reset_index(drop=True) for c, g in P[P.date >= pd.Timestamp("2025-12-01")].groupby("code")}
    for r in E.itertuples():
        g = by_code[r.code]
        j = g.index[g.date == r.date][0]
        pre = g.iloc[j - 1] if j > 0 else None
        nxt = g.iloc[j + 1:j + 6]
        events.append(dict(kode=r.code, tgl=str(r.date.date()), harga=r.c, chg=r.chg, streak=int(r.streak),
                           val20=r.val20, volx=None if not np.isfinite(r.volx) else round(float(r.volx), 2),
                           papan="LQ45" if r.code in lq45 else ("Pengembangan" if r.code in pp else "Lainnya"),
                           pre=[k for k in FEATS if pre is not None and k not in ("ARA0",) and bool(pre[k])],
                           pre_skor=round(float(pre.score), 2) if pre is not None else None,
                           ret5=float(nxt.c.iloc[-1] / r.c - 1) if len(nxt) == 5 else None,
                           likuid=bool(pre is not None and pre.val20 >= a.minval)))
    events.sort(key=lambda x: (x["tgl"], x["kode"]), reverse=True)
    monthly = E.groupby(E.date.dt.to_period("M")).agg(n=("code", "size"), saham=("code", "nunique"))
    monthly = [dict(bulan=str(k), n=int(v.n), saham=int(v.saham)) for k, v in monthly.iterrows()]
    # % ARA yang didahului tiap indikator (H-1)
    pre_share = {k: float(np.mean([k in e["pre"] for e in events])) if events else 0 for k in FEATS}

    out = dict(
        dibuat=datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), data_sampai=str(last_day.date()),
        minval=a.minval, minpx=a.minpx, n_saham=int(P.code.nunique()),
        ihsg=dict(close=float(ihsg.iloc[-1]), chg=float(ihsg.iloc[-1] / ihsg.iloc[-2] - 1), atas_ma50=bool(ix_ok.iloc[-1])),
        label=LABEL, grup=GROUP, bobot=W,
        lift=lt.replace({np.nan: None}).to_dict("records"), base1=b1, base5=b5, nobs=nobs,
        skor_bin=sb.assign(b=sb.b.astype(str)).replace({np.nan: None}).to_dict("records"),
        validasi=val, kandidat=cand, events=events, bulanan=monthly, pre_share=pre_share, spark=spark,
    )
    js = json.dumps(out, ensure_ascii=False, default=lambda o: None if o is None else (float(o) if isinstance(o, (np.floating, np.integer)) else str(o)))
    js = js.replace("NaN", "null")
    html = (BASE / "template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", js)
    HASIL.mkdir(exist_ok=True)
    f1 = HASIL / f"Watchlist_ARA_2026_{last_day.date()}.html"
    f1.write_text(html, encoding="utf-8")
    f2 = BASE / "watchlist_ara_2026.html"
    f2.write_text(html, encoding="utf-8")
    (BASE / "index.html").write_text(html, encoding="utf-8")  # halaman GitHub Pages
    (BASE / "status.json").write_text(json.dumps(dict(data_sampai=out["data_sampai"], dibuat=out["dibuat"])), encoding="utf-8")
    if a.publish:
        publish(last_day)
    nk = sum(1 for c in cand if c["skor"] > 0 and c["likuid"])
    print(f"Selesai {time.time() - t0:.0f} dtk. ARA 2026: {len(events)} kejadian. Kandidat likuid skor>0: {nk}")
    print("Dashboard:", f2)
    if not a.no_open:
        webbrowser.open(f2.as_uri())


if __name__ == "__main__":
    main()
