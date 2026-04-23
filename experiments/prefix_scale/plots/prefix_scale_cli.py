import argparse
import os

from .prefix_scale_data import (
    detect_role_table_topology,
    has_core_edge_result_layout,
    load_churn_csv,
    load_core_edge_results,
    source_label_from_dir,
)
from .prefix_scale_plots import (
    plot_core_edge_control_breakdown,
    plot_core_edge_forwarding_delta_by_role,
    plot_core_edge_prefix_state_by_role,
    plot_core_edge_run_comparison,
    plot_core_edge_table_stack_comparison,
    plot_core_edge_topology,
    plot_churn_breakdown,
    plot_churn_comparison,
    plot_io_cdf_compare,
    plot_io_per_variant,
    plot_net_overhead,
    plot_raw_overhead,
    plot_sim_vs_emu,
    plot_svs_suppression_compare,
    write_core_edge_summary,
)


def build_parser():
    parser = argparse.ArgumentParser(description="Prefix-scaling plots")
    parser.add_argument("--data", required=True, help="Directory with prefix-scale results")
    parser.add_argument("--data2", default=None, help="Second data dir for sim-vs-emu comparison")
    parser.add_argument("--out", default=None, help="Output directory for plots")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    source_label = source_label_from_dir(args.data)
    out_dir = args.out or os.path.join(os.path.abspath(args.data), "plots")
    os.makedirs(out_dir, exist_ok=True)

    csv_path = os.path.join(args.data, "churn.csv")
    if os.path.exists(csv_path):
        rows = load_churn_csv(csv_path)

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
                    sim_dir, emu_dir = args.data, args.data2
                else:
                    sim_rows, emu_rows = rows_2, rows
                    sim_dir, emu_dir = args.data2, args.data
                plot_sim_vs_emu(sim_rows, emu_rows, out_dir)
                plot_io_cdf_compare(sim_dir, emu_dir, out_dir)
                plot_svs_suppression_compare(sim_dir, emu_dir, out_dir)

        print("Done.")
        return 0

    if has_core_edge_result_layout(args.data):
        topology_key = detect_role_table_topology(args.data)
        results_by_phase = load_core_edge_results(args.data)
        print(f"Generating role-based prefix-scale plots from {args.data} ({topology_key})")
        plot_core_edge_topology(out_dir, topology_key=topology_key)
        plot_core_edge_run_comparison(results_by_phase, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_control_breakdown(args.data, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_prefix_state_by_role(results_by_phase, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_forwarding_delta_by_role(results_by_phase, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_table_stack_comparison(results_by_phase, out_dir, source_label, topology_key=topology_key)
        write_core_edge_summary(results_by_phase, os.path.abspath(args.data), out_dir, topology_key=topology_key)
        if args.data2:
            print("WARNING: --data2 is not used for the core/edge table-study layout")
        print("Done.")
        return 0

    print(f"ERROR: {args.data} is not a recognized prefix-scale result directory")
    return 1