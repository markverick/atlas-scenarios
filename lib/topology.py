"""
Shared grid topology builder for both emulation and simulation.

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
