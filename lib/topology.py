"""
Shared topology builder for both emulation and simulation.

Supports:
  - NxN grid topologies (build_grid_topo, generate_ndnsim_topo)
  - Linear chain topologies (generate_ndnsim_linear_topo)
  - Mini-NDN .conf file topologies (parse_minindn_conf, generate_ndnsim_topo_from_conf)
    - Rocketfuel sample topologies converted into ndnSIM topology files

Mininet is imported lazily so the simulation side can use grid_stats()
and generate_ndnsim_topo() without having Mininet installed.
"""

from collections import defaultdict as _defaultdict
import math as _math
import os as _os
import re as _re


def build_grid_topo(n, delay="10ms", bw=10):
    """Create an NxN Mininet grid topology for emulation.

    Returns (topo, nodes_dict) where nodes_dict maps (row, col) to host name.
    """
    from mininet.topo import Topo

    topo = Topo()
    nodes = {}
    for r in range(n):
        for c in range(n):
            name = f"n{r}_{c}"
            nodes[(r, c)] = topo.addHost(name)
    for r in range(n):
        for c in range(n):
            if c + 1 < n:
                topo.addLink(nodes[(r, c)], nodes[(r, c + 1)],
                             delay=delay, bw=bw)
            if r + 1 < n:
                topo.addLink(nodes[(r, c)], nodes[(r + 1, c)],
                             delay=delay, bw=bw)
    return topo, nodes


def grid_stats(n):
    """Return (num_nodes, num_links) for an NxN grid."""
    return n * n, 2 * n * (n - 1)


def grid_links(n):
    """Return list of (src, dst) link pairs for an NxN grid."""
    links = []
    for r in range(n):
        for c in range(n):
            if c + 1 < n:
                links.append((f"n{r}_{c}", f"n{r}_{c+1}"))
            if r + 1 < n:
                links.append((f"n{r}_{c}", f"n{r+1}_{c}"))
    return links


def grid_nodes(n):
    """Return list of node names for an NxN grid."""
    return [f"n{r}_{c}" for r in range(n) for c in range(n)]


def linear_stats(n):
    """Return (num_nodes, num_links) for an N-node linear chain."""
    return n, n - 1


def core_edge_roles():
    """Return node-role lists for the fixed 10-node core/edge topology."""
    return {
        "core": [f"c{i}" for i in range(6)],
        "edge": [f"e{i}" for i in range(4)],
    }


def core_edge_nodes():
    """Return the ordered node list for the fixed 10-node core/edge topology."""
    roles = core_edge_roles()
    return roles["core"] + roles["edge"]


def core_edge_links():
    """Return link pairs for the fixed 10-node core/edge topology."""
    return [
        ("c0", "c1"),
        ("c1", "c2"),
        ("c2", "c3"),
        ("c3", "c4"),
        ("c4", "c5"),
        ("c5", "c0"),
        ("c0", "c3"),
        ("c1", "c4"),
        ("e0", "c0"),
        ("e1", "c2"),
        ("e2", "c3"),
        ("e3", "c5"),
    ]


def core_edge_positions():
    """Return drawing positions for the fixed 10-node core/edge topology."""
    return {
        "c0": (1, 0),
        "c1": (3, 0),
        "c2": (4, 1),
        "c3": (3, 3),
        "c4": (1, 3),
        "c5": (0, 1),
        "e0": (1, -1.1),
        "e1": (5.1, 1),
        "e2": (3, 4.1),
        "e3": (-1.1, 1),
    }


def core_edge_stats():
    """Return (num_nodes, num_links) for the fixed 10-node core/edge topology."""
    return len(core_edge_nodes()), len(core_edge_links())


def generate_ndnsim_core_edge_topo(bw="10Mbps", delay_ms=10, path=None, queue_size=100):
    """Write an ndnSIM topology file for the fixed 10-node core/edge topology."""
    positions = core_edge_positions()

    lines = [
        "# Auto-generated 10-node core/edge topology",
        "router",
        "# node  comment  yPos  xPos",
    ]
    for name in core_edge_nodes():
        x_pos, y_pos = positions[name]
        lines.append(f"{name}  NA  {y_pos}  {x_pos}")

    lines.append("")
    lines.append("link")
    lines.append("# srcNode  dstNode  bandwidth  metric  delay  queue")
    for src, dst in core_edge_links():
        lines.append(f"{src}  {dst}  {bw}  1  {delay_ms}ms  {queue_size}")

    return _write_topo(lines, path)


_ROCKETFUEL_CCH_LINE_RE = _re.compile(
    r"^(?P<uid>\S+)\s+@(?P<loc>\S+)\s+"
    r"(?P<dns>\+)?\s*"
    r"(?P<bb>bb)?\s*"
    r"\((?P<num_neigh>-?\d+)\)\s*"
    r"(?P<extern>&\d+)?\s*->\s*"
    r"(?P<neighbors>(?:<[^>]+>\s*)*)"
    r"(?:\{[^}]+\}\s*)*"
    r"=(?P<name>\S+)\s+"
    r"r(?P<radius>\d+)$"
)

_ROCKETFUEL_CCH_ALIAS_RE = _re.compile(r"^-\d+\s+=\S+\s+r\d+$")


def _rocketfuel_sort_key(uid):
    return (0, int(uid)) if uid.isdigit() else (1, uid)


def _rocketfuel_node_name(uid):
    return f"rf{uid}"


_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))


def _rocketfuel_repo_path(*parts):
    return _os.path.join(_REPO_ROOT, *parts)


def rocketfuel_sample_4755_path(ns3_dir=None):
    """Return the path to the checked-in Rocketfuel sample 4755 maps file."""
    if ns3_dir:
        return _os.path.join(
            ns3_dir,
            "src",
            "topology-read",
            "examples",
            "RocketFuel_sample_4755.r0.cch_maps.txt",
        )

    return _rocketfuel_repo_path(
        "deps",
        "ns-3",
        "src",
        "topology-read",
        "examples",
        "RocketFuel_sample_4755.r0.cch_maps.txt",
    )


def rocketfuel_2914_path():
    """Return the path to the checked-in large Rocketfuel AS 2914 maps file."""
    return _rocketfuel_repo_path(
        "experiments",
        "prefix_scale",
        "topologies",
        "rocketfuel_2914.cch",
    )


def _rocketfuel_links(entries, keep_uids):
    links = set()
    for uid in keep_uids:
        for neighbor in entries[uid]["neighbors"]:
            if neighbor not in keep_uids or neighbor == uid:
                continue
            links.add(tuple(sorted((uid, neighbor), key=_rocketfuel_sort_key)))
    return sorted(links, key=lambda pair: (_rocketfuel_sort_key(pair[0]),
                                           _rocketfuel_sort_key(pair[1])))


def _rocketfuel_connected_components(keep_uids, links):
    adjacency = {uid: set() for uid in keep_uids}
    for src, dst in links:
        adjacency[src].add(dst)
        adjacency[dst].add(src)

    components = []
    unseen = set(keep_uids)
    while unseen:
        start = next(iter(unseen))
        stack = [start]
        component = set()
        while stack:
            uid = stack.pop()
            if uid in component:
                continue
            component.add(uid)
            unseen.discard(uid)
            stack.extend(adjacency[uid] - component)
        components.append(component)
    return components


def parse_rocketfuel_cch_maps(maps_path, drop_isolated=True, component_mode="all"):
    """Parse a Rocketfuel cch maps file and keep only connected r0 nodes.

    The ns-3 Rocketfuel reader keeps only `r0` nodes. For the prefix-scale
    study we also drop isolated r0 nodes because they cannot participate in
    routing convergence or table measurements.
    """
    if component_mode not in {"all", "largest"}:
        raise ValueError(f"unsupported component_mode: {component_mode}")

    entries = {}

    with open(maps_path) as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if _ROCKETFUEL_CCH_ALIAS_RE.match(line):
                continue

            match = _ROCKETFUEL_CCH_LINE_RE.match(line)
            if not match:
                raise ValueError(f"Malformed Rocketfuel maps line {line_no}: {raw.rstrip()}")

            radius = int(match.group("radius"))
            if radius != 0:
                continue

            uid = match.group("uid")
            entries[uid] = {
                "uid": uid,
                "loc": match.group("loc"),
                "dns": bool(match.group("dns")),
                "bb": bool(match.group("bb")),
                "name": match.group("name"),
                "neighbors": sorted(_re.findall(r"<([^>]+)>", match.group("neighbors")),
                                    key=_rocketfuel_sort_key),
            }

    keep_uids = set(entries)
    links = _rocketfuel_links(entries, keep_uids)

    if drop_isolated:
        while True:
            linked_uids = {uid for link in links for uid in link}
            isolated_uids = keep_uids - linked_uids
            if not isolated_uids:
                break
            keep_uids -= isolated_uids
            links = _rocketfuel_links(entries, keep_uids)

    if component_mode == "largest" and keep_uids:
        components = _rocketfuel_connected_components(keep_uids, links)
        largest = sorted(
            components,
            key=lambda component: (
                -len(component),
                [_rocketfuel_sort_key(uid) for uid in sorted(component, key=_rocketfuel_sort_key)],
            ),
        )[0]
        keep_uids = set(largest)
        links = _rocketfuel_links(entries, keep_uids)

    nodes = []
    for uid in sorted(keep_uids, key=_rocketfuel_sort_key):
        entry = entries[uid]
        nodes.append({
            **entry,
            "neighbors": [neighbor for neighbor in entry["neighbors"] if neighbor in keep_uids],
        })

    return {
        "nodes": nodes,
        "links": links,
    }


def _rocketfuel_roles_from_graph(graph):
    roles = {"core": [], "edge": []}
    for node in graph["nodes"]:
        role = "core" if node["bb"] else "edge"
        roles[role].append(_rocketfuel_node_name(node["uid"]))
    return roles


def _rocketfuel_links_from_graph(graph):
    return [
        (_rocketfuel_node_name(src), _rocketfuel_node_name(dst))
        for src, dst in graph["links"]
    ]


def _rocketfuel_positions_from_graph(graph):
    """Return deterministic drawing positions for a parsed Rocketfuel graph."""
    roles = _rocketfuel_roles_from_graph(graph)
    core_nodes = roles["core"]
    edge_nodes = roles["edge"]

    positions = {}
    angle_by_name = {}
    core_radius = max(4.0, len(core_nodes) / 20.0)
    edge_radius = max(7.0, core_radius * 1.65)

    if core_nodes:
        for index, name in enumerate(core_nodes):
            angle = 2.0 * _math.pi * index / len(core_nodes)
            angle_by_name[name] = angle
            positions[name] = (
                round(core_radius * _math.cos(angle), 3),
                round(core_radius * _math.sin(angle), 3),
            )

    name_by_uid = {node["uid"]: _rocketfuel_node_name(node["uid"]) for node in graph["nodes"]}
    neighbors_by_name = {
        name_by_uid[node["uid"]]: [name_by_uid[neighbor] for neighbor in node["neighbors"]]
        for node in graph["nodes"]
    }

    anchored_edges = _defaultdict(list)
    unanchored_edges = []
    core_order = {name: index for index, name in enumerate(core_nodes)}

    for edge_name in edge_nodes:
        core_neighbors = [name for name in neighbors_by_name.get(edge_name, []) if name in core_order]
        if not core_neighbors:
            unanchored_edges.append(edge_name)
            continue

        anchor = min(core_neighbors, key=lambda name: core_order[name])
        anchored_edges[anchor].append(edge_name)

    for anchor in core_nodes:
        edge_names = anchored_edges.get(anchor, [])
        count = len(edge_names)
        if count == 0:
            continue

        if count == 1:
            offsets = [0.0]
        else:
            span = min(0.9, 0.03 * (count - 1))
            offsets = [(-span / 2.0) + span * index / (count - 1) for index in range(count)]

        for edge_name, offset in zip(edge_names, offsets):
            angle = angle_by_name[anchor] + offset
            positions[edge_name] = (
                round(edge_radius * _math.cos(angle), 3),
                round(edge_radius * _math.sin(angle), 3),
            )

    for index, edge_name in enumerate(unanchored_edges):
        angle = 2.0 * _math.pi * index / max(1, len(unanchored_edges))
        positions[edge_name] = (
            round(edge_radius * _math.cos(angle), 3),
            round(edge_radius * _math.sin(angle), 3),
        )

    return positions


def _rocketfuel_stats_from_graph(graph):
    return len(graph["nodes"]), len(graph["links"])


def _generate_ndnsim_rocketfuel_topo(graph, *, label, bw="10Mbps",
                                     delay_ms=10, path=None,
                                     queue_size=100):
    positions = _rocketfuel_positions_from_graph(graph)
    roles = _rocketfuel_roles_from_graph(graph)
    ordered_nodes = roles["core"] + roles["edge"]

    lines = [
        f"# Auto-generated {label} topology (r0 nodes only)",
        "router",
        "# node  comment  yPos  xPos",
    ]
    for name in ordered_nodes:
        x_pos, y_pos = positions[name]
        lines.append(f"{name}  NA  {y_pos}  {x_pos}")

    lines.append("")
    lines.append("link")
    lines.append("# srcNode  dstNode  bandwidth  metric  delay  queue")
    for src, dst in _rocketfuel_links_from_graph(graph):
        lines.append(f"{src}  {dst}  {bw}  1  {delay_ms}ms  {queue_size}")

    return _write_topo(lines, path)


def _rocketfuel_sample_4755_graph(maps_path=None):
    return parse_rocketfuel_cch_maps(maps_path or rocketfuel_sample_4755_path())


def rocketfuel_sample_4755_roles(maps_path=None):
    """Return core/edge node-role lists for the checked-in Rocketfuel sample."""
    return _rocketfuel_roles_from_graph(_rocketfuel_sample_4755_graph(maps_path))


def rocketfuel_sample_4755_links(maps_path=None):
    """Return ndnSIM link pairs for the checked-in Rocketfuel sample."""
    return _rocketfuel_links_from_graph(_rocketfuel_sample_4755_graph(maps_path))


def rocketfuel_sample_4755_positions(maps_path=None):
    """Return deterministic drawing positions for the checked-in Rocketfuel sample."""
    return _rocketfuel_positions_from_graph(_rocketfuel_sample_4755_graph(maps_path))


def rocketfuel_sample_4755_stats(maps_path=None):
    """Return (num_nodes, num_links) for the checked-in Rocketfuel sample."""
    return _rocketfuel_stats_from_graph(_rocketfuel_sample_4755_graph(maps_path))


def generate_ndnsim_rocketfuel_sample_4755_topo(maps_path=None, bw="10Mbps",
                                                delay_ms=10, path=None,
                                                queue_size=100):
    """Write an ndnSIM topology file for the checked-in Rocketfuel sample 4755."""
    return _generate_ndnsim_rocketfuel_topo(
        _rocketfuel_sample_4755_graph(maps_path),
        label="Rocketfuel sample 4755",
        bw=bw,
        delay_ms=delay_ms,
        path=path,
        queue_size=queue_size,
    )


def _rocketfuel_2914_graph(maps_path=None):
    return parse_rocketfuel_cch_maps(
        maps_path or rocketfuel_2914_path(),
        component_mode="largest",
    )


def rocketfuel_2914_roles(maps_path=None):
    """Return core/edge node-role lists for the large Rocketfuel AS 2914 map."""
    return _rocketfuel_roles_from_graph(_rocketfuel_2914_graph(maps_path))


def rocketfuel_2914_links(maps_path=None):
    """Return ndnSIM link pairs for the large Rocketfuel AS 2914 map."""
    return _rocketfuel_links_from_graph(_rocketfuel_2914_graph(maps_path))


def rocketfuel_2914_positions(maps_path=None):
    """Return deterministic drawing positions for the large Rocketfuel AS 2914 map."""
    return _rocketfuel_positions_from_graph(_rocketfuel_2914_graph(maps_path))


def rocketfuel_2914_stats(maps_path=None):
    """Return (num_nodes, num_links) for the large Rocketfuel AS 2914 map."""
    return _rocketfuel_stats_from_graph(_rocketfuel_2914_graph(maps_path))


def generate_ndnsim_rocketfuel_2914_topo(maps_path=None, bw="10Mbps",
                                         delay_ms=10, path=None,
                                         queue_size=100):
    """Write an ndnSIM topology file for the large Rocketfuel AS 2914 map."""
    return _generate_ndnsim_rocketfuel_topo(
        _rocketfuel_2914_graph(maps_path),
        label="Rocketfuel AS 2914 largest connected component",
        bw=bw,
        delay_ms=delay_ms,
        path=path,
        queue_size=queue_size,
    )


def _write_topo(lines, path=None):
    """Join lines into topology content and optionally write to disk."""
    content = "\n".join(lines) + "\n"
    if path:
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    return content


def generate_ndnsim_linear_topo(names, bw="10Mbps", delay_ms=10, path=None):
    """Write an ndnSIM topology file for a linear chain of named nodes.

    names: list of node names, e.g. ["a", "b", "c"]
    Returns the file content as a string. If path is given, also writes to disk.
    """
    lines = [
        "# Auto-generated linear topology",
        "router",
        "# node  comment  yPos  xPos",
    ]
    for i, name in enumerate(names):
        lines.append(f"{name}  NA  0  {i}")

    lines.append("")
    lines.append("link")
    lines.append("# srcNode  dstNode  bandwidth  metric  delay  queue")
    for i in range(len(names) - 1):
        lines.append(f"{names[i]}  {names[i+1]}  {bw}  1  {delay_ms}ms  100")

    return _write_topo(lines, path)


def generate_ndnsim_topo(n, bw="10Mbps", delay_ms=10, path=None, queue_size=100):
    """Write an ndnSIM topology file for an NxN grid.

    Returns the file content as a string. If path is given, also writes to disk.
    """
    lines = [
        "# Auto-generated NxN grid topology",
        "router",
        "# node  comment  yPos  xPos",
    ]
    for r in range(n):
        for c in range(n):
            lines.append(f"n{r}_{c}  NA  {r}  {c}")

    lines.append("")
    lines.append("link")
    lines.append("# srcNode  dstNode  bandwidth  metric  delay  queue")
    for r in range(n):
        for c in range(n):
            if c + 1 < n:
                lines.append(f"n{r}_{c}  n{r}_{c+1}  {bw}  1  {delay_ms}ms  {queue_size}")
            if r + 1 < n:
                lines.append(f"n{r}_{c}  n{r+1}_{c}  {bw}  1  {delay_ms}ms  {queue_size}")

    return _write_topo(lines, path)


# ---------------------------------------------------------------------------
# Mini-NDN .conf topology support
# ---------------------------------------------------------------------------


def parse_minindn_conf(conf_path):
    """Parse a Mini-NDN .conf topology file.

    Returns (nodes, links) where:
      nodes: list of node name strings
      links: list of (src, dst, params_dict) tuples
    """
    nodes = []
    links = []
    section = None

    with open(conf_path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].lower()
                continue
            if section == "nodes":
                name = line.split(":")[0].strip()
                nodes.append(name)
            elif section == "links":
                parts = line.split()
                src_dst = parts[0]
                src, dst = src_dst.split(":")
                params = {}
                for p in parts[1:]:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        params[k] = v
                links.append((src.strip(), dst.strip(), params))

    return nodes, links


def conf_stats(conf_path):
    """Return (num_nodes, num_links) for a Mini-NDN .conf topology."""
    nodes, links = parse_minindn_conf(conf_path)
    return len(nodes), len(links)


def generate_ndnsim_topo_from_conf(conf_path, bw="10Mbps", delay_ms=None,
                                   path=None, queue_size=100):
    """Convert a Mini-NDN .conf topology to ndnSIM topology file format.

    If delay_ms is None, uses the delay from the .conf file (or 10ms default).
    Returns the file content as a string. If path is given, also writes to disk.
    """
    nodes, links = parse_minindn_conf(conf_path)

    lines = [
        f"# Auto-generated from {_os.path.basename(conf_path)}",
        "router",
        "# node  comment  yPos  xPos",
    ]
    for i, name in enumerate(nodes):
        lines.append(f"{name}  NA  0  {i}")

    lines.append("")
    lines.append("link")
    lines.append("# srcNode  dstNode  bandwidth  metric  delay  queue")
    for src, dst, params in links:
        delay = f"{delay_ms}ms" if delay_ms is not None else params.get("delay", "10ms")
        lines.append(f"{src}  {dst}  {bw}  1  {delay}  {queue_size}")

    return _write_topo(lines, path)


def build_conf_topo(conf_path, delay="10ms", bw=10):
    """Create a Mininet topology from a Mini-NDN .conf file for emulation.

    Returns (topo, nodes_list) where nodes_list is the list of node names.
    """
    from mininet.topo import Topo

    nodes, links = parse_minindn_conf(conf_path)

    topo = Topo()
    host_map = {}
    for name in nodes:
        host_map[name] = topo.addHost(name)

    for src, dst, params in links:
        link_delay = params.get("delay", delay)
        link_bw = int(params.get("bw", bw)) if "bw" in params else bw
        topo.addLink(host_map[src], host_map[dst],
                     delay=link_delay, bw=link_bw)

    return topo, nodes
