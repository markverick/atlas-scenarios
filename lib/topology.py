"""
Shared topology builder for both emulation and simulation.

Supports:
  - NxN grid topologies (build_grid_topo, generate_ndnsim_topo)
  - Linear chain topologies (generate_ndnsim_linear_topo)
  - Mini-NDN .conf file topologies (parse_minindn_conf, generate_ndnsim_topo_from_conf)

Mininet is imported lazily so the simulation side can use grid_stats()
and generate_ndnsim_topo() without having Mininet installed.
"""


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


def linear_stats(n):
    """Return (num_nodes, num_links) for an N-node linear chain."""
    return n, n - 1


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

    content = "\n".join(lines) + "\n"
    if path:
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    return content


def generate_ndnsim_topo(n, bw="10Mbps", delay_ms=10, path=None):
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
                lines.append(f"n{r}_{c}  n{r}_{c+1}  {bw}  1  {delay_ms}ms  100")
            if r + 1 < n:
                lines.append(f"n{r}_{c}  n{r+1}_{c}  {bw}  1  {delay_ms}ms  100")

    content = "\n".join(lines) + "\n"
    if path:
        with open(path, "w") as f:
            f.write(content)
    return content


# ---------------------------------------------------------------------------
# Mini-NDN .conf topology support
# ---------------------------------------------------------------------------

import os as _os


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
                                   path=None):
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
        lines.append(f"{src}  {dst}  {bw}  1  {delay}  100")

    content = "\n".join(lines) + "\n"
    if path:
        _os.makedirs(_os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    return content


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
