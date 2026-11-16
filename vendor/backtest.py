"""Backtest winrate sinyal kenaikan harga jangka pendek - LQ45 (data Yahoo Finance).
Entry = harga OPEN hari berikutnya setelah sinyal (realistis, tanpa look-ahead).
Metode 1 (LeBeau & Lucas / Van Tharp): winrate = % close hari ke-h > entry, h = 1,3,5,10.
Metode 2 (realistis): SL 1xATR, TP 2xATR (R:R 1:2), maks 10 hari, fee beli 0.15% jual 0.25%.
"""
import json, os, sys, time, urllib.request
import numpy as np, pandas as pd

TICKERS = ("AADI ADMR ADRO AKRA AMMN AMRT ANTM ASII BBCA BBNI BBRI BBTN BMRI BRPT BUMI CPIN CUAN "
           "DEWA EMTK ESSA EXCL GOTO HRTA ICBP INCO INDF INDY INKP ISAT ITMG JPFA KLBF MAPI MBMA "
           "MDKA MEDC PGAS PGEO PTBA SCMA TLKM UNTR UNVR WIFI").split()
DATA = os.path.join(os.path.dirname(__file__), "data")
HORIZONS = [1, 3, 5, 10]
FEE_BUY, FEE_SELL = 0.0015, 0.0025


def fetch(t, rng="10y"):
    os.makedirs(DATA, exist_ok=True)
    path = f"{DATA}/{t}.csv"
    if os.path.exists(path):
        return pd.read_csv(path, index_col=0, parse_dates=True)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}.JK?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    j = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    df = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close", "volume"]},
                      index=pd.to_datetime(j["timestamp"], unit="s").normalize())
    df = df.dropna()
    df = df[(df.volume > 0) & (df.high >= df.low)]
    df = df[~df.index.duplicated(keep="last")]
    df.to_csv(path)
    return df


def indicators(d):
    o, h, l, c, v = d.open, d.high, d.low, d.close, d.volume
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_w = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, d.index).ewm(alpha=1 / 14, adjust=False).mean() / atr_w
    mdi = 100 * pd.Series(mdm, d.index).ewm(alpha=1 / 14, adjust=False).mean() / atr_w
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    d["adx"], d["pdi"], d["mdi"] = dx.ewm(alpha=1 / 14, adjust=False).mean(), pdi, mdi
    for n in (10, 20, 50, 60, 200):
        d[f"ma{n}"] = c.rolling(n).mean()
    d["ema30"] = c.ewm(span=30, adjust=False).mean()
    delta = c.diff()
    rs = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean() / (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + rs)
    d["vavg5"] = v.rolling(5).mean().shift()
    d["vavg20"] = v.rolling(20).mean().shift()
    # Ichimoku
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    spanA_raw = (tenkan + kijun) / 2
    spanB_raw = (h.rolling(52).max() + l.rolling(52).min()) / 2
    d["tenkan"], d["kijun"] = tenkan, kijun
    d["kumo_top"] = pd.concat([spanA_raw.shift(26), spanB_raw.shift(26)], axis=1).max(axis=1)
    d["kumo_top_26ago"] = d["kumo_top"].shift(26)
    d["future_bull"] = spanA_raw > spanB_raw  # awan 26 bar ke depan
    return d


def signals(d):
    o, h, l, c, v = d.open, d.high, d.low, d.close, d.volume
    body = (c - o)
    rng = (h - l).replace(0, np.nan)
    bull, bear = c > o, c < o
    o1, h1, l1, c1 = o.shift(1), h.shift(1), l.shift(1), c.shift(1)
    o2, h2, l2, c2 = o.shift(2), h.shift(2), l.shift(2), c.shift(2)
    o3, c3 = o.shift(3), c.shift(3)
    down5 = c.shift(1) < c.shift(6)  # turun sebelumnya (konteks reversal)
    longbody = body.abs() > 0.6 * (h - l).rolling(10).mean()
    small1 = (c1 - o1).abs() < 0.3 * rng.shift(1)
    trend_up = (d.ma10 > d.ema30) & (d.ema30 > d.ma60) & (d.ma60 > d.ma200)
    vol15 = v > 1.5 * d.vavg5
    S = {}
    S["BASELINE (semua hari / acak)"] = pd.Series(True, d.index)
    # --- Van Tharp / LeBeau & Lucas
    S["Volatility breakout (C-Cprev > 0.8 ATR)"] = (c - c1) > 0.8 * d.atr.shift()
    S["ADX naik ke high 10 hari, ADX>15, +DI>-DI"] = (d.adx >= d.adx.rolling(10).max()) & (d.adx > 15) & (d.adx > d.adx.shift()) & (d.pdi > d.mdi)
    S["Channel breakout 40 hari (close > high 40h)"] = c > h.rolling(40).max().shift()
    S["Close di 10% teratas range harian"] = ((c - l) / rng >= 0.9)
    S["RSI14 < 30 (oversold)"] = (d.rsi < 30) & (d.rsi.shift() >= 30)
    S["Golden cross EMA30 x MA60"] = (d.ema30 > d.ma60) & (d.ema30.shift() <= d.ma60.shift())
    # --- Candlestick Bulkowski (bullish)
    S["CDL Three White Soldiers"] = bull & bull.shift(1) & bull.shift(2) & (c > c1) & (c1 > c2) & (o > o1) & (o < c1) & (o1 > o2) & (o1 < c2) & down5.shift(2)
    S["CDL Morning Star"] = bear.shift(2) & longbody.shift(2) & small1 & (np.maximum(o1, c1) < c2) & bull & (c > (o2 + c2) / 2) & down5.shift(2)
    S["CDL Morning Doji Star"] = bear.shift(2) & longbody.shift(2) & ((c1 - o1).abs() <= 0.1 * rng.shift(1)) & bull & (c > (o2 + c2) / 2) & down5.shift(2)
    S["CDL Three Outside Up"] = bear.shift(2) & bull.shift(1) & (o1 <= c2) & (c1 >= o2) & (c > c1) & down5.shift(2)
    S["CDL Bullish Engulfing"] = bear.shift(1) & bull & (o <= c1) & (c >= o1) & down5
    S["CDL Three Line Strike (bearish->naik)"] = bear.shift(3) & bear.shift(2) & bear.shift(1) & (c2 < c3) & (c1 < c2) & bull & (o <= c1) & (c >= o3)
    S["CDL Hammer"] = (np.minimum(o, c) - l >= 2 * body.abs()) & (h - np.maximum(o, c) <= 0.25 * rng) & down5
    S["CDL Rising Three Methods"] = bull.shift(4) & longbody.shift(4) & (h.shift(1).rolling(3).max() < h.shift(4)) & (l.shift(1).rolling(3).min() > l.shift(4)) & bull & (c > c.shift(4))
    # --- Ryan Filbert / Mega Profit / Ichimoku / S&D
    S["MA stack (10>30>60>200) + pullback ke EMA30"] = trend_up & (l <= d.ema30) & (c > d.ema30)
    S["Ichimoku ideal (4 syarat)"] = (c > d.kumo_top) & (d.tenkan > d.kijun) & (c > c.shift(26)) & (c > d.kumo_top_26ago) & d.future_bull
    S["Ichimoku: Tenkan cross Kijun di atas kumo"] = (d.tenkan > d.kijun) & (d.tenkan.shift() <= d.kijun.shift()) & (c > d.kumo_top)
    S["Breakout 20h + volume >=1.5x avg5 (Mega Profit)"] = (c > h.rolling(20).max().shift()) & vol15
    bull_cdl = S["CDL Three White Soldiers"] | S["CDL Morning Star"] | S["CDL Three Outside Up"] | S["CDL Bullish Engulfing"] | S["CDL Hammer"] | S["CDL Morning Doji Star"]
    S["KOMBO: tren naik + candle bullish"] = trend_up & (bull_cdl | (bull & (l <= d.ema30) & (c > d.ema30)))
    S["KOMBO: tren naik + vol breakout 0.8ATR + volume 1.5x"] = trend_up & S["Volatility breakout (C-Cprev > 0.8 ATR)"] & vol15
    S["KOMBO: Ichimoku ideal + breakout 20h + volume 1.5x"] = S["Ichimoku ideal (4 syarat)"] & S["Breakout 20h + volume >=1.5x avg5 (Mega Profit)"]
    return {k: s.fillna(False).astype(bool) for k, s in S.items()}


def evaluate(d, sig):
    """Kembalikan list dict per trade."""
    o, h, l, c = d.open.values, d.high.values, d.low.values, d.close.values
    atr = d.atr.values
    n = len(d)
    idx = np.where(sig.values)[0]
    out = []
    for i in idx:
        e = i + 1
        if e + 10 >= n or i < 200 or not np.isfinite(atr[i]):
            continue
        entry = o[e]
        if entry <= 0:
            continue
        r = {f"ret{hh}": c[e + hh - 1] / entry - 1 for hh in HORIZONS}  # close hari ke-h (h=1 -> close hari entry)
        sl, tp = entry - atr[i], entry + 2 * atr[i]
        res, exitp = None, c[min(e + 9, n - 1)]
        for k in range(e, e + 10):
            if l[k] <= sl:  # konservatif: SL dulu bila keduanya tersentuh
                res, exitp = "SL", min(sl, o[k]) if k > e else sl
                break
            if h[k] >= tp:
                res, exitp = "TP", max(tp, o[k]) if k > e else tp
                break
        net = exitp * (1 - FEE_SELL) / (entry * (1 + FEE_BUY)) - 1
        r.update(rr_net=net, rr_win=net > 0, rr_R=(exitp - entry) / atr[i], date=d.index[i])
        out.append(r)
    return out


def main():
    allres = {}
    failed = []
    for t in TICKERS:
        try:
            d = fetch(t)
        except Exception as ex:
            failed.append((t, str(ex)[:80])); continue
        if len(d) < 300:
            failed.append((t, f"data hanya {len(d)} hari")); continue
        d = indicators(d.copy())
        for name, s in signals(d).items():
            for tr in evaluate(d, s):
                tr["ticker"] = t
                allres.setdefault(name, []).append(tr)
        time.sleep(0.3)
    rows = []
    for name, trs in allres.items():
        df = pd.DataFrame(trs)
        row = {"Sinyal": name, "Jumlah sinyal": len(df), "Jumlah saham": df.ticker.nunique()}
        for hh in HORIZONS:
            row[f"Winrate {hh}h"] = (df[f"ret{hh}"] > 0).mean()
            row[f"Avg ret {hh}h"] = df[f"ret{hh}"].mean()
        row["Winrate SL1ATR/TP2ATR (net fee)"] = df.rr_win.mean()
        row["Expectancy per trade (net)"] = df.rr_net.mean()
        row["Expectancy (R)"] = df.rr_R.mean()
        rows.append(row)
    summ = pd.DataFrame(rows)
    base = summ[summ.Sinyal.str.startswith("BASELINE")].iloc[0]
    for hh in HORIZONS:
        summ[f"Edge {hh}h vs acak"] = summ[f"Winrate {hh}h"] - base[f"Winrate {hh}h"]
    summ = summ.sort_values("Winrate 5h", ascending=False)
    pd.to_pickle((summ, allres, failed), os.path.join(os.path.dirname(__file__), "result.pkl"))
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(summ[["Sinyal", "Jumlah sinyal", "Winrate 1h", "Winrate 3h", "Winrate 5h", "Winrate 10h", "Winrate SL1ATR/TP2ATR (net fee)", "Expectancy per trade (net)"]].round(3).to_string(index=False))
    print("Gagal:", failed)


if __name__ == "__main__":
    main()
