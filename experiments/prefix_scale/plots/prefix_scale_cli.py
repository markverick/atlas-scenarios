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
    plot_core_edge_table_average_by_role,
    plot_core_edge_table_average_by_role_reduced,
    plot_core_edge_table_stack_comparison,
    plot_core_edge_table_stack_comparison_reduced,
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
    write_core_edge_csv,
    write_core_edge_xlsx,
)


def build_parser():
    parser = argparse.ArgumentParser(description="Prefix-scaling plots")
    parser.add_argument("--data", required=True, help="Directory with prefix-scale results")
    parser.add_argument("--data2", default=None, help="Second data dir for sim-vs-emu comparison")
    parser.add_argument("--out", default=None, help="Output directory for plots")
    parser.add_argument("--source-label", dest="source_label", default=None,
                        choices=["sim", "emu", "Simulation", "Emulation"],
                        help="Source label for plot titles (sim or emu)")
    return parser


def _resolve_source_label(args):
    if args.source_label:
        label = args.source_label
        if label == "sim":
            return "Simulation"
        if label == "emu":
            return "Emulation"
        return label
    return source_label_from_dir(args.data)


def main(argv=None):
    args = build_parser().parse_args(argv)
    source_label = _resolve_source_label(args)
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
                raise FileNotFoundError(f"--data2 churn.csv not found: {csv_path_2}")
            rows_2 = load_churn_csv(csv_path_2)
            base1 = os.path.basename(os.path.abspath(args.data))
            base2 = os.path.basename(os.path.abspath(args.data2))
            data1_is_sim = "sim" in base1
            data1_is_emu = "emu" in base1
            data2_is_sim = "sim" in base2
            data2_is_emu = "emu" in base2
            if data1_is_sim and data2_is_emu:
                sim_rows, emu_rows = rows, rows_2
                sim_dir, emu_dir = args.data, args.data2
            elif data1_is_emu and data2_is_sim:
                sim_rows, emu_rows = rows_2, rows
                sim_dir, emu_dir = args.data2, args.data
            else:
                raise ValueError(
                    f"cannot determine sim/emu roles from directory names: "
                    f"{base1!r} vs {base2!r} (expected one to contain 'sim' and the other 'emu')"
                )
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
        # plot_core_edge_prefix_state_by_role(results_by_phase, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_forwarding_delta_by_role(results_by_phase, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_table_average_by_role(results_by_phase, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_table_average_by_role_reduced(results_by_phase, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_table_stack_comparison(results_by_phase, out_dir, source_label, topology_key=topology_key)
        plot_core_edge_table_stack_comparison_reduced(results_by_phase, out_dir, source_label, topology_key=topology_key)
        write_core_edge_summary(results_by_phase, os.path.abspath(args.data), out_dir, topology_key=topology_key)
        write_core_edge_csv(results_by_phase, out_dir)
        write_core_edge_xlsx(results_by_phase, os.path.abspath(args.data), out_dir)
        if args.data2:
            print("WARNING: --data2 is not used for the core/edge table-study layout")
        print("Done.")
        return 0

    print(f"ERROR: {args.data} is not a recognized prefix-scale result directory")
    return 1