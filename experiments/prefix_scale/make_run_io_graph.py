#!/usr/bin/env python3
"""Generate a per-run I/O graph (aggregate Mbps vs time) from a prefix_scale run root.

Usage:
    python3 experiments/prefix_scale/make_run_io_graph.py --data <run_root> [--bw <Mbps>]

Discovers all link trace CSVs under <run_root>, one subplot per trace,
with a red capacity line at bw * num_links.
"""
import argparse
import csv
import glob
import os
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


INTERVAL = 0.05   # seconds per bin (link trace sampling)
COLORS = {
    'PrefixSync': '#ff7f0e',
    'DvAdvert':   '#1f77b4',
    'Mgmt':       '#2ca02c',
    'Other':      '#9467bd',
}


def load_trace(path):
    times, dv, svs, mgmt, other = [], [], [], [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            times.append(float(row['Time']))
            dv.append(int(row.get('DvAdvert_Bytes') or 0))
            svs.append(int(row.get('PrefixSync_Bytes') or 0))
            mgmt.append(int(row.get('Mgmt_Bytes') or 0))
            other.append(int(row.get('Other_Bytes') or 0))
    t = np.array(times)
    to_mbps = lambda b: np.array(b) * 8 / INTERVAL / 1e6
    return t, to_mbps(dv), to_mbps(svs), to_mbps(mgmt), to_mbps(other)


def find_conv(run_root, tag):
    """Find convergence time for a given run tag (e.g. 'twophase-p2000-t1')."""
    pat = os.path.join(run_root, '**', f'conv-{tag}.txt')
    hits = glob.glob(pat, recursive=True)
    if not hits:
        return None
    try:
        with open(hits[0]) as f:
            v = float(f.read().strip())
            return v if v > 0 else None
    except Exception:
        return None


def count_links(run_root):
    """Try to read num_links from metadata.json in any stage subdir."""
    for meta in glob.glob(os.path.join(run_root, '**/metadata.json'), recursive=True):
        try:
            import json
            with open(meta) as f:
                d = json.load(f)
            if 'num_links' in d:
                return int(d['num_links'])
        except Exception:
            pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True, help='Run root directory')
    parser.add_argument('--bw', type=float, default=None,
                        help='Per-link bandwidth in Mbps (auto-detected from metadata if omitted)')
    args = parser.parse_args()

    run_root = args.data.rstrip('/')

    # Discover all link trace CSVs, sorted
    traces = sorted(glob.glob(os.path.join(run_root, '**/link-trace-*.csv'), recursive=True))
    if not traces:
        print(f'No link trace CSVs found under {run_root}')
        return

    num_links = count_links(run_root)
    if num_links is None:
        num_links = 381  # rocketfuel_1755 default
        print(f'Warning: could not detect num_links, assuming {num_links}')

    # Auto-detect bw from metadata if not given
    bw = args.bw
    if bw is None:
        import json
        for meta in glob.glob(os.path.join(run_root, '**/metadata.json'), recursive=True):
            try:
                with open(meta) as f:
                    d = json.load(f)
                # Not stored in metadata; leave as None
            except Exception:
                pass
        if bw is None:
            bw = 1000  # default for this queue
            print(f'Warning: --bw not specified, assuming {bw} Mbps')

    capacity_mbps = bw * num_links

    fig, axes = plt.subplots(len(traces), 1,
                             figsize=(14, 4 * len(traces)),
                             squeeze=False)

    for i, tpath in enumerate(traces):
        ax = axes[i][0]
        # Derive a label from the filename
        fname = os.path.basename(tpath)                    # link-trace-twophase-p2000-t1.csv
        tag = fname.replace('link-trace-', '').replace('.csv', '')  # twophase-p2000-t1
        # Stage dir name
        stage_dir = os.path.basename(os.path.dirname(tpath))

        t, dv, svs, mgmt, other = load_trace(tpath)
        total = dv + svs + mgmt + other

        ax.stackplot(t, svs, dv, mgmt, other,
                     labels=['PrefixSync (SVS)', 'DV Advert', 'Mgmt', 'Other'],
                     colors=[COLORS['PrefixSync'], COLORS['DvAdvert'],
                             COLORS['Mgmt'], COLORS['Other']],
                     alpha=0.6)
        ax.plot(t, total, lw=0.9, color='black', alpha=0.65, label='Total')
        ax.axhline(capacity_mbps, color='red', lw=1.5, ls='--',
                   label=f'Capacity  {bw:.0f} Mbps × {num_links} links = {capacity_mbps:,.0f} Mbps')

        conv_s = find_conv(run_root, tag)
        if conv_s:
            ax.axvline(conv_s, color='purple', lw=1.4, ls=':',
                       label=f'Converged  t={conv_s:.3f}s')

        ax.set_title(f'{stage_dir}  /  {tag}', fontsize=9.5, loc='left', pad=3)
        ax.set_ylabel('Aggregate Mbps', fontsize=8)
        ax.set_xlim(0, float(t[-1]))
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))
        ax.grid(axis='y', lw=0.4, alpha=0.5)
        duration = float(t[-1])
        minor_step = 0.5 if duration <= 30 else (5 if duration <= 300 else 30)
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(minor_step))
        ax.legend(loc='upper right', fontsize=7.5, ncol=6, framealpha=0.9)

    axes[-1][0].set_xlabel('Simulation time (s)', fontsize=9)

    topo = os.path.basename(os.path.dirname(run_root))
    ts   = os.path.basename(run_root)
    fig.suptitle(
        f'Network I/O — {topo}  bw={bw:.0f} Mbps  queue=1000\n'
        f'{num_links} links · 50 ms bins · {ts}',
        fontsize=11)

    plt.tight_layout()
    out = os.path.join(run_root, 'io_graph.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f'Saved: {out}')


if __name__ == '__main__':
    main()
