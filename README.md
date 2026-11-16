# AAN Watchlist · ARA 2026

Online: **https://ardianyuka-hash.github.io/aan-watchlist/**

Update data + kirim ke GitHub: klik dua kali `Update dan Publikasikan.bat` (atau `py watchlist_ara.py --publish`).
Mesin membutuhkan folder proyek trading lokal (`../HASIL ANALISA/script/backtest.py`, `../screener-cangkang/idx_codes.txt`).

Dashboard kandidat ARA saham BEI, memakai indikator proyek trading
(`HASIL ANALISA/script/backtest.py` — `indicators()` + `signals()` diimpor apa adanya — plus Aturan A/B dari
`Pengembangan_Edge_RSI_Breakout.xlsx`).

## Pakai
- Klik dua kali **`Buka Watchlist ARA.bat`** → unduh data terbaru (±2 menit) → dashboard terbuka di browser.
- Tanpa unduh: `py watchlist_ara.py --no-fetch`. Filter likuiditas lain: `--minval 5e8` (default Rp1 M), `--minpx 50`.

## Isi dashboard (`watchlist_ara_2026.html`, arsip harian di `hasil/`)
- **Kandidat hari ini** — skor ARA, peluang ARA 5 hari, harga ARA besok, indikator yang menyala, filter & sortir.
- **Watchlist saya** — bintangi saham, catatan, unduh CSV (tersimpan di localStorage browser).
- **Riwayat ARA 2026** — semua kejadian ARA, ARA beruntun, indikator H-1, return 5 hari sesudahnya.
- **Statistik indikator** — lift tiap indikator 2026 + validasi out-of-sample (bobot Jan–Jun, uji Jul–Nov).

## Metode singkat
- ARA: batas 35% (≤Rp200) / 25% (Rp200–5.000) / 20% (>Rp5.000) dari close kemarin, dibulatkan ke fraksi harga.
- Skor = Σ log2(lift ARA ≤5 hari) indikator yang menyala (lift > 1, n ≥ 30).
- Risiko: saham yang sudah close ARA praktis tidak bisa dibeli; peluang ARA ≠ profit (lihat tab Metodologi).

File: `watchlist_ara.py` (mesin), `template.html` (tampilan), `data/prices.parquet` (cache, boleh ditimpa).
