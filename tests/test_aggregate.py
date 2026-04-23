import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import aggregate


def write_scalability_csv(directory, rows):
    path = os.path.join(directory, "scalability.csv")
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "grid_size",
            "num_nodes",
            "num_links",
            "trial",
            "convergence_s",
            "transfer_ok",
            "avg_mem_kb",
            "total_packets",
            "total_bytes",
            "dv_packets",
            "dv_bytes",
            "user_packets",
            "user_bytes",
        ])
        writer.writerows(rows)


def write_link_trace(directory, trial, dv_pkts, dv_bytes, user_interest_pkts, user_interest_bytes):
    path = os.path.join(directory, f"link-trace-3x3-t{trial}.csv")
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "Time",
            "Node",
            "FaceId",
            "Peer",
            "DvAdvert_Pkts",
            "DvAdvert_Bytes",
            "PrefixSync_Pkts",
            "PrefixSync_Bytes",
            "Mgmt_Pkts",
            "Mgmt_Bytes",
            "UserInterest_Pkts",
            "UserInterest_Bytes",
            "UserData_Pkts",
            "UserData_Bytes",
            "Other_Pkts",
            "Other_Bytes",
        ])
        writer.writerow([
            "0.0",
            "n0",
            "1",
            "n1",
            dv_pkts,
            dv_bytes,
            0,
            0,
            0,
            0,
            user_interest_pkts,
            user_interest_bytes,
            user_interest_pkts,
            user_interest_bytes * 10,
            0,
            0,
        ])


def test_aggregate_dir_sums_categories(tmp_path):
    out_dir = tmp_path / "twophase"
    out_dir.mkdir()
    write_scalability_csv(out_dir, [
        [3, 9, 12, 2, "0.1234", True, 0, 0, 0, 0, 0, 0, 0],
        [3, 9, 12, 1, "0.1200", True, 0, 0, 0, 0, 0, 0, 0],
    ])
    write_link_trace(out_dir, 1, 10, 1000, 20, 200)
    write_link_trace(out_dir, 2, 11, 1100, 21, 210)

    rows = aggregate.aggregate_dir(str(out_dir), grid_size=3)

    assert [row["trial"] for row in rows] == [1, 2]
    assert rows[0]["convergence_s"] == "0.1200"
    assert rows[0]["DvAdvert_pkts"] == 10
    assert rows[0]["UserInterest_pkts"] == 20
    assert rows[0]["UserData_pkts"] == 20
    assert rows[0]["total_pkts"] == 50
    assert rows[0]["total_bytes"] == 3200


def test_render_report_outputs_markdown_sections(tmp_path):
    tw_dir = tmp_path / "twophase"
    op_dir = tmp_path / "onephase"
    tw_dir.mkdir()
    op_dir.mkdir()
    write_scalability_csv(tw_dir, [[3, 9, 12, 1, "0.1000", True, 0, 0, 0, 0, 0, 0, 0]])
    write_scalability_csv(op_dir, [[3, 9, 12, 1, "0.2000", True, 0, 0, 0, 0, 0, 0, 0]])
    write_link_trace(tw_dir, 1, 1, 100, 2, 20)
    write_link_trace(op_dir, 1, 3, 300, 4, 40)

    report = aggregate.render_report([
        ("twophase", str(tw_dir)),
        ("onephase", str(op_dir)),
    ], grid_size=3)

    assert "## twophase" in report
    assert "## onephase" in report
    assert "| trial | convergence_s |" in report
    assert "| 1 | 0.1000 | 1 | 100 |" in report
    assert "| 1 | 0.2000 | 3 | 300 |" in report