import argparse
import os

from .prefix_scale_data import load_churn_csv, source_label_from_dir
from .prefix_scale_plots import (
    plot_churn_breakdown,
    plot_churn_comparison,
    plot_io_per_variant,
    plot_net_overhead,
    plot_raw_overhead,
    plot_sim_vs_emu,
)


def build_parser():
    parser = argparse.ArgumentParser(description="Prefix-scaling plots")
    parser.add_argument("--data", required=True, help="Directory with churn.csv and packet traces")
    parser.add_argument("--data2", default=None, help="Second data dir for sim-vs-emu comparison")
    parser.add_argument("--out", default=None, help="Output directory for plots")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    csv_path = os.path.join(args.data, "churn.csv")
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found")
        return 1

    rows = load_churn_csv(csv_path)
    source_label = source_label_from_dir(args.data)
    out_dir = args.out or os.path.join(os.path.abspath(args.data), "plots")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Generating prefix-scaling plots from {csv_path}")
    plot_churn_comparison(rows, out_dir, source_label)
    plot_churn_breakdown(rows, out_dir, source_label)
    plot_net_overhead(rows, out_dir, source_label)
    plot_raw_overhead(rows, out_dir, source_label)
    plot_io_per_variant(args.data, out_dir, source_label)

    if args.data2:
        csv_path_2 = os.path.join(args.data2, "churn.csv")
        if not os.path.exists(csv_path_2):
            print(f"WARNING: {csv_path_2} not found, skipping sim-vs-emu comparison")
        else:
            rows_2 = load_churn_csv(csv_path_2)
            if "sim" in os.path.basename(os.path.abspath(args.data)):
                sim_rows, emu_rows = rows, rows_2
            else:
                sim_rows, emu_rows = rows_2, rows
            plot_sim_vs_emu(sim_rows, emu_rows, out_dir)

    print("Done.")
    return 0