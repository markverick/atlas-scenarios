#!/usr/bin/env python3
"""Wireshark-style I/O graph comparing congestion-mitigation experiments."""

import csv
import glob
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


BASE  = 'experiments/prefix_scale/results/rocketfuel_1755_bothphase_3stage/20260503-231930'
P10   = 'experiments/prefix_scale/results/rocketfuel_1755_onephase_pipeline10_3stage/20260504-032110'
BW100 = 'experiments/prefix_scale/results/rocketfuel_1755_onephase_bw100_3stage/20260504-022029'

# Use the most recent completed gap10 run (any timestamp under that dir)
def _latest_gap10_p2000():
    pattern = 'experiments/prefix_scale/results/rocketfuel_1755_onephase_gap10_3stage/*/stage2-p2000-gap10/link-trace-onephase-p2000-t1.csv'
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None

INTERVAL = 0.05  # seconds per bin


def load_link(path):
    times, dv, svs = [], [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            times.append(float(row['Time']))
            dv.append(int(row['DvAdvert_Bytes']))
            svs.append(int(row['PrefixSync_Bytes']))
    t = np.array(times)
    return t, np.array(dv), np.array(svs)


# Build file list; gap10 appended only when result is available
NUM_LINKS = 381  # rocketfuel_1755 link count

# Each entry: (label, path, is_gap, bw_mbps_per_link)
FILES = [
    (
        'Baseline  gap=0, bw=10 Mbps  →  33 anomalous nodes',
        BASE  + '/stage2-p2000-onephase/link-trace-onephase-p2000-t1.csv',
        False,
        10,
    ),
    (
        'SVS pipeline=10  bw=10 Mbps  →  10 anomalous nodes',
        P10   + '/stage2-p2000/link-trace-onephase-p2000-t1.csv',
        False,
        10,
    ),
    (
        'bw=100 Mbps, gap=0  →  0 anomalous nodes ✓',
        BW100 + '/stage2-p2000-onephase/link-trace-onephase-p2000-t1.csv',
        False,
        100,
    ),
]

gap10_path = _latest_gap10_p2000()
if gap10_path:
    FILES.append((
        'announce gap=10 ms, bw=10 Mbps  →  21 anomalous nodes',
        gap10_path,
        True,
        10,
    ))
else:
    print('Note: gap=10ms result not yet available — showing 3 configs only')

DV_COL  = '#1f77b4'
SVS_COL = '#ff7f0e'
XMAX    = 12.0

fig, axes = plt.subplots(len(FILES), 1, figsize=(14, 3.6 * len(FILES)))
if len(FILES) == 1:
    axes = [axes]
fig.suptitle(
    'Network I/O — rocketfuel_1755  onephase  2000 prefixes\n'
    'Aggregate Mbps across all links · 50 ms bins',
    fontsize=12,
)

for i, (label, fpath, is_gap, bw_mbps) in enumerate(FILES):
    ax = axes[i]
    t, dv, svs = load_link(fpath)
    if len(t) == 0:
        ax.set_title(f'{label}  [empty trace]', fontsize=9.5, loc='left')
        continue

    dv_mbps  = dv  * 8 / INTERVAL / 1e6
    svs_mbps = svs * 8 / INTERVAL / 1e6
    total_capacity_mbps = bw_mbps * NUM_LINKS

    ax.stackplot(t, svs_mbps, dv_mbps,
                 labels=['SVS / PrefixSync', 'DV Advert'],
                 colors=[SVS_COL, DV_COL], alpha=0.55)
    ax.plot(t, svs_mbps + dv_mbps, lw=0.8, color='black', alpha=0.55, label='Total')

    # Bandwidth ceiling line
    ax.axhline(total_capacity_mbps, color='red', lw=1.4, ls='-',
               label=f'Link capacity  {bw_mbps} Mbps × {NUM_LINKS} links = {total_capacity_mbps:,} Mbps')

    # DV heartbeat lines every 1 s
    for hb in np.arange(1.0, XMAX, 1.0):
        ax.axvline(hb, color='#999999', lw=0.7, ls='--', alpha=0.45)

    if is_gap:
        ax.axvspan(0.5, 0.5 + 60 * 0.010, alpha=0.20,
                   color='limegreen', label='announce window  0.5–1.1 s')
    else:
        ax.axvline(0.5, color='limegreen', lw=1.6, ls=':', alpha=0.9,
                   label='simultaneous announce  t=0.5 s')

    ax.set_title(label, fontsize=9.5, loc='left', pad=3)
    ax.set_ylabel('Aggregate Mbps', fontsize=8)
    ax.set_xlim(0, min(float(t[-1]), XMAX))
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', lw=0.4, alpha=0.5)
    ax.xaxis.set_minor_locator(ticker.MultipleLocator(0.5))
    ax.legend(loc='upper right', fontsize=7, ncol=4, framealpha=0.85)

axes[-1].set_xlabel('Simulation time (s)', fontsize=9)

plt.tight_layout()
out = 'experiments/prefix_scale/io_graph_announce_gap.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
print(f'Saved: {out}')
