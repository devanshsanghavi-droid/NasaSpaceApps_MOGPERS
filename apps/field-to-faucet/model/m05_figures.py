"""m05: documentation figures -> model/out/fig_*.png   (after m02-m04)

Run: python3 model/m05_figures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import featlib as F  # noqa: E402

INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
BAND = "#2a78d6"
MCLC = "#e34948"
DPI = 110
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "legend.frameon": False})


def shade(ax, start, end):
    ax.axvspan(pd.Timestamp(F.TEST[0]), pd.Timestamp(F.TEST[1]), color="#f1efe8", zorder=0, lw=0)
    ax.axvspan(pd.Timestamp(F.LIVE_START), end, color="#e8f0fa", zorder=0, lw=0)
    y = ax.get_ylim()[1]
    for x, lab in ((start, "train 2016-2022"), (pd.Timestamp(F.TEST[0]), "test 2023-2025"),
                   (pd.Timestamp(F.LIVE_START), "live 2026")):
        ax.text(x + pd.Timedelta(days=20), y * 0.97, lab, va="top", fontsize=8, color=INK2)


def series_panel(ax, g, title, start, end, show_res=True, show_clim=False):
    g = g[(g.date >= start) & (g.date <= end)]
    ax.fill_between(g.date, g.p10, g.p90, color=BAND, alpha=0.18, lw=0, label="GBM 80% band")
    if show_clim:
        ax.plot(g.date, g.clim_p50, color=INK2, lw=1, ls=":", label="climatology")
    if show_res:
        ax.plot(g.date, g.reservoir_p50, color=ORANGE, lw=1, alpha=0.9, label="two-reservoir model")
    ax.plot(g.date, g.p50, color=BLUE, lw=1.4, label="GBM p50 (drivers only)")
    ax.plot(g.date, g.obs, color=INK, lw=1.0, label="observed (USGS)")
    ax.axhline(10, color=MCLC, lw=1, ls="--")
    ax.text(g.date.iloc[0], 10.2, "10 mg/L limit", color=MCLC, fontsize=8, va="bottom")
    ax.set_ylabel("nitrate-N (mg/L)")
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    ax.set_ylim(0, max(20, np.nanmax(g[["obs", "p90"]].values) * 1.05))


def main():
    rd = pd.read_parquet(F.OUT / "river_daily.parquet")
    met = json.load(open(F.OUT / "metrics.json"))
    end = rd.date.max()
    # 1. full series
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.6), sharex=True)
    for ax, site in zip(axes, ["05484500", "05482000"]):
        g = rd[rd.site == site]
        t = met["sites"][site]["splits"]["test"]["gbm"]
        series_panel(ax, g, f"{F.SITE_NAMES[site]}  -  test 2023-2025 GBM NSE {t['NSE']:.2f}, KGE {t['KGE']:.2f}",
                     pd.Timestamp("2016-01-01"), end)
        shade(ax, pd.Timestamp("2016-01-01"), end)
    axes[0].legend(loc="upper center", ncol=5, fontsize=8, bbox_to_anchor=(0.5, 1.22))
    axes[1].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(F.OUT / "fig_river_2016_2026.png", dpi=DPI)
    plt.close(fig)

    # 2. 2025 crisis zoom (+ 2026)
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.2), sharex=True)
    for ax, site in zip(axes, ["05484500", "05482000"]):
        g = rd[rd.site == site]
        c = met["sites"][site]["crisis_2025"]
        series_panel(ax, g, f"{F.SITE_NAMES[site]}  -  2025 days > 10 mg/L: observed {c['gbm']['obs_days_over10']}, "
                     f"GBM {c['gbm']['pred_days_over10_on_obs_days']}, reservoir "
                     f"{c['reservoir']['pred_days_over10_on_obs_days']}, climatology "
                     f"{c['climatology']['pred_days_over10_on_obs_days']} (on observed days)",
                     pd.Timestamp("2024-10-01"), end, show_clim=True)
        ax.axvspan(pd.Timestamp(F.LIVE_START), end, color="#e8f0fa", zorder=0, lw=0)
    axes[0].legend(loc="upper center", ncol=5, fontsize=8, bbox_to_anchor=(0.5, 1.22))
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.tight_layout()
    fig.savefig(F.OUT / "fig_2025_zoom.png", dpi=DPI)
    plt.close(fig)

    # 3. scatter obs vs p50 by split
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    for ax, site in zip(axes, ["05484500", "05482000"]):
        g = rd[(rd.site == site) & rd.obs.notna() & rd.p50.notna()]
        for sp, col, lab in (("train", "#b5b3ab", "train"), ("test", BLUE, "test 2023-25"), ("live", ORANGE, "live 2026")):
            s = g[g.split == sp]
            ax.scatter(s.obs, s.p50, s=5, color=col, alpha=0.45, lw=0, label=lab)
        ax.plot([0.3, 25], [0.3, 25], color=INK2, lw=1)
        ax.axhline(10, color=MCLC, lw=0.8, ls="--"); ax.axvline(10, color=MCLC, lw=0.8, ls="--")
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(0.3, 25); ax.set_ylim(0.3, 25)
        ax.set_xlabel("observed nitrate-N (mg/L)"); ax.set_ylabel("GBM p50 (mg/L)")
        ax.set_title(F.SITE_NAMES[site], loc="left", fontsize=10)
        ax.legend(loc="upper left", fontsize=8, markerscale=3)
    fig.tight_layout()
    fig.savefig(F.OUT / "fig_scatter.png", dpi=DPI)
    plt.close(fig)

    # 4. outlook
    op = F.OUT / "outlook.json"
    if op.exists():
        ol = json.load(open(op))
        fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
        for ax, (site, s) in zip(axes, ol["sites"].items()):
            g = rd[(rd.site == site) & (rd.date > pd.Timestamp(s["last_obs"]["date"]) - pd.Timedelta(days=60))]
            dts = pd.to_datetime(s["dates"])
            ax.fill_between(dts, s["p10"], s["p90"], color=BAND, alpha=0.2, lw=0, label="80% range")
            ax.plot(dts, s["p50"], color=BLUE, lw=1.6, label="outlook median")
            ax.plot(g.date, g.obs, color=INK, lw=1.2, label="observed")
            ax.axhline(10, color=MCLC, lw=1, ls="--")
            ax.set_title(f"{s['name']}: 14-day outlook from {s['last_obs']['date']}", loc="left", fontsize=9.5)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
            ax.set_ylabel("nitrate-N (mg/L)")
            ax.legend(loc="lower left", fontsize=8)
        fig.tight_layout()
        fig.savefig(F.OUT / "fig_outlook.png", dpi=DPI)
        plt.close(fig)

    # 5. sensitivity
    sp = F.OUT / "sensitivity.json"
    if sp.exists():
        se = json.load(open(sp))
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
        for ax, (site, s) in zip(axes, se["sites"].items()):
            fr = list(s["gbm"].keys())
            x = np.arange(len(fr))
            b = [s["gbm"][f]["bootstrap"]["days_avoided_per_year_mean_2016_2025"] for f in fr]
            ax.bar(x - 0.18, [v["p50"] for v in b], 0.34, color=BLUE, label="GBM (bootstrap median, 5-95%)",
                   yerr=[[v["p50"] - v["lo"] for v in b], [v["hi"] - v["p50"] for v in b]], ecolor=INK2, capsize=3)
            ax.bar(x + 0.18, [s["reservoir"][f]["days_avoided_per_year_mean_2016_2025"] for f in fr], 0.34,
                   color=ORANGE, label="two-reservoir model")
            ax.set_xticks(x, [f"-{int(float(f) * 100)}% bare" for f in fr])
            ax.set_title(F.SITE_NAMES[site], loc="left", fontsize=9.5)
            ax.set_ylabel("days > 10 mg/L avoided per year\n(obs-anchored, 2016-2025 mean)")
            ax.legend(loc="upper left", fontsize=8)
        fig.suptitle("Learned sensitivity to less bare soil Oct 15-May 31 (weakly identified; blend with trial priors)",
                     fontsize=9.5, x=0.01, ha="left")
        fig.tight_layout()
        fig.savefig(F.OUT / "fig_sensitivity.png", dpi=DPI)
        plt.close(fig)
    # 6. v1 vs v2 (legacy-N) vs level-corrected, 2023-2026
    v2p = F.OUT / "v2" / "river_daily_v2.parquet"
    if v2p.exists() and "v2" in met:
        r2 = pd.read_parquet(v2p)
        fig, axes = plt.subplots(2, 1, figsize=(11, 6.2), sharex=True)
        for ax, site in zip(axes, ["05484500", "05482000"]):
            g = r2[(r2.site == site) & (r2.date >= "2023-01-01")]
            c2 = met["v2"]["sites"][site]["crisis_2025"]
            lc = met["v2"]["sites"][site]["level_corrected"]["v2"]["crisis_2025"]
            ax.plot(g.date, g.v1_p50, color=BLUE, lw=1.1, label="v1 p50 (pre-registered)")
            ax.plot(g.date, g.p50, color=AQUA, lw=1.3, label="v2 legacy-N p50 (post-hoc)")
            ax.plot(g.date, g.lc_v2_p50, color=ORANGE, lw=1.0, ls="--", label="v2 level-corrected (uses obs)")
            ax.plot(g.date, g.obs, color=INK, lw=1.0, label="observed (USGS)")
            ax.axhline(10, color=MCLC, lw=1, ls="--")
            ax.axvspan(pd.Timestamp(F.LIVE_START), g.date.max(), color="#e8f0fa", zorder=0, lw=0)
            ax.set_title(f"{F.SITE_NAMES[site]}  -  2025 days > 10: observed {c2['gbm_v2']['obs_days_over10']}, "
                         f"v1 {c2['gbm_v1']['pred_days_over10_on_obs_days']}, v2 "
                         f"{c2['gbm_v2']['pred_days_over10_on_obs_days']}, level-corrected "
                         f"{lc['pred_days_over10_on_obs_days']}", loc="left", fontsize=9.5)
            ax.set_ylabel("nitrate-N (mg/L)")
            ax.set_ylim(0, 20)
        axes[0].legend(loc="upper center", ncol=4, fontsize=8, bbox_to_anchor=(0.5, 1.25))
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        fig.tight_layout()
        fig.savefig(F.OUT / "fig_v1_v2_2023_2026.png", dpi=DPI)
        plt.close(fig)
    print("figures:", sorted(p.name for p in F.OUT.glob("fig_*.png")))


if __name__ == "__main__":
    main()
