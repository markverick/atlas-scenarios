NODE_FIELDNAMES = [
    "phase",
    "trial",
    "prefix_count",
    "node",
    "role",
    "table_category",
    "table_name",
    "entry_count",
]

ROLE_FIELDNAMES = [
    "phase",
    "trial",
    "prefix_count",
    "role",
    "table_category",
    "table_name",
    "node_count",
    "total_entries",
    "avg_entries",
    "max_entries",
]


def parse_table_trace(path):
    rows = []
    with open(path, newline="") as handle:
        import csv

        reader = csv.DictReader(handle)
        for row in reader:
            rows.append({
                "node": row["node"],
                "role": row["role"],
                "table_category": row["table_category"],
                "table_name": row["table_name"],
                "entry_count": int(row["entry_count"]),
            })
    return rows


def summarize_role_table_metrics(rows):
    grouped = {}
    for row in rows:
        key = (row["role"], row["table_category"], row["table_name"])
        agg = grouped.setdefault(key, {
            "node_count": 0,
            "total_entries": 0,
            "max_entries": 0,
        })
        agg["node_count"] += 1
        agg["total_entries"] += row["entry_count"]
        agg["max_entries"] = max(agg["max_entries"], row["entry_count"])

    summaries = []
    for (role, table_category, table_name), agg in sorted(grouped.items()):
        node_count = agg["node_count"]
        summaries.append({
            "role": role,
            "table_category": table_category,
            "table_name": table_name,
            "node_count": node_count,
            "total_entries": agg["total_entries"],
            "avg_entries": agg["total_entries"] / node_count,
            "max_entries": agg["max_entries"],
        })
    return summaries


EMU_TABLE_SPECS = (
    {
        "table_category": "common",
        "table_name": "forwarder_fib",
        "subcommand": "fib-list",
        "header": "FIB:",
    },
    {
        "table_category": "twophase",
        "table_name": "forwarder_pet",
        "subcommand": "pet-list",
        "header": "PET:",
        "phases": {"twophase"},
    },
)


def parse_nfdc_status_listing(output, header):
    started = False
    count = 0

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Error "):
            return None
        if stripped == header:
            started = True
            continue
        if started:
            count += 1

    if not started:
        return None
    return count


def collect_emu_table_metrics(hosts, role_by_node, phase, *, ndnd_bin, warn=None):
    rows = []
    for host in hosts:
        role = role_by_node.get(host.name)
        if role is None:
            continue

        home_dir = host.params["params"]["homeDir"]
        for spec in EMU_TABLE_SPECS:
            phases = spec.get("phases")
            if phases is not None and phase not in phases:
                continue

            output = host.cmd(
                f'HOME="{home_dir}" {ndnd_bin} fw {spec["subcommand"]} 2>&1 || true'
            )
            entry_count = parse_nfdc_status_listing(output, spec["header"])
            if entry_count is None:
                if warn is not None:
                    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "unexpected output")
                    warn(
                        f"WARNING: failed to collect {spec['table_name']} on {host.name}: {first_line}"
                    )
                continue

            rows.append({
                "node": host.name,
                "role": role,
                "table_category": spec["table_category"],
                "table_name": spec["table_name"],
                "entry_count": entry_count,
            })

    return rows
