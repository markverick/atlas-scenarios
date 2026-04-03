#!/usr/bin/env python3
"""Build a static HTML gallery from experiment result plot directories for GitHub Pages.

Scans nested ``experiments/*/results/**/plots`` directories and legacy
``results/**/plots`` directories for .png images and .md summaries, then writes
a self-contained _site/ directory with an index and per-experiment pages.

Run locally:  python3 .github/scripts/build_pages.py
Output:       _site/index.html, _site/<experiment>/...
"""
import glob
import html
import os
import shutil

LEGACY_RESULTS_DIR = "results"
EXPERIMENTS_DIR = "experiments"
OUT_DIR = "_site"

STYLE = """
body { font-family: system-ui, sans-serif; max-width: 1200px; margin: 2em auto; padding: 0 1em; }
h1 { border-bottom: 2px solid #333; padding-bottom: 0.3em; }
h2 { color: #555; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 1em; }
.gallery img { width: 100%; border: 1px solid #ddd; border-radius: 4px; }
.gallery figure { margin: 0; }
figcaption { font-size: 0.85em; color: #666; text-align: center; }
a { color: #0969da; }
nav { margin-bottom: 2em; }
pre { background: #f6f8fa; padding: 1em; border-radius: 6px; overflow-x: auto; }
"""


def find_plot_dirs():
    """Return sorted list of result plot directories that contain PNGs."""
    dirs = set()
    patterns = [
        os.path.join(EXPERIMENTS_DIR, "*", "results", "**", "plots"),
        os.path.join(LEGACY_RESULTS_DIR, "plots*"),
        os.path.join(LEGACY_RESULTS_DIR, "**", "plots"),
    ]
    for pattern in patterns:
        for d in sorted(glob.glob(pattern, recursive=True)):
            if os.path.isdir(d) and glob.glob(os.path.join(d, "*.png")):
                dirs.add(os.path.normpath(d))
    return sorted(dirs)


def read_summary(plot_dir):
    """Read a .md summary file if present."""
    for name in ("churn_summary.md", "summary.md"):
        p = os.path.join(plot_dir, name)
        if os.path.isfile(p):
            with open(p) as f:
                return f.read()
    return ""


def md_to_html_simple(md):
    """Minimal Markdown → HTML (headings, tables, paragraphs)."""
    lines = md.split("\n")
    out = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            out.append(f"<h2>{html.escape(stripped[2:])}</h2>")
        elif stripped.startswith("## "):
            out.append(f"<h3>{html.escape(stripped[3:])}</h3>")
        elif stripped.startswith("### "):
            out.append(f"<h4>{html.escape(stripped[4:])}</h4>")
        elif "|" in stripped and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if all(set(c) <= set("- :") for c in cells):
                continue  # separator row
            if not in_table:
                out.append("<table><tr>")
                in_table = True
            else:
                out.append("<tr>")
            for c in cells:
                out.append(f"<td>{html.escape(c)}</td>")
            out.append("</tr>")
        else:
            if in_table:
                out.append("</table>")
                in_table = False
            if stripped:
                out.append(f"<p>{html.escape(stripped)}</p>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def build_experiment_page(plot_dir, rel_name):
    """Build an HTML page for one experiment directory."""
    pngs = sorted(glob.glob(os.path.join(plot_dir, "*.png")))
    summary = read_summary(plot_dir)

    exp_out = os.path.join(OUT_DIR, rel_name)
    os.makedirs(exp_out, exist_ok=True)

    # Copy PNGs
    for png in pngs:
        shutil.copy2(png, exp_out)

    # Build HTML
    img_html = []
    for png in pngs:
        fname = os.path.basename(png)
        label = fname.replace(".png", "").replace("_", " ")
        img_html.append(
            f'<figure><a href="{fname}"><img src="{fname}" alt="{html.escape(label)}"></a>'
            f'<figcaption>{html.escape(label)}</figcaption></figure>'
        )

    summary_html = md_to_html_simple(summary) if summary else ""

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html.escape(rel_name)}</title>
<style>{STYLE}</style></head><body>
<nav><a href="../index.html">← All experiments</a></nav>
<h1>{html.escape(rel_name)}</h1>
{summary_html}
<h2>Plots</h2>
<div class="gallery">
{"".join(img_html)}
</div>
</body></html>"""

    with open(os.path.join(exp_out, "index.html"), "w") as f:
        f.write(page)

    return rel_name, len(pngs)


def build_index(experiments):
    """Build the top-level index page."""
    items = []
    for name, count in experiments:
        items.append(f'<li><a href="{name}/index.html">{html.escape(name)}</a> ({count} plots)</li>')

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ATLAS Scenarios — Results</title>
<style>{STYLE}</style></head><body>
<h1>ATLAS Scenarios — Results</h1>
<p>Auto-generated gallery of experiment plots.</p>
<ul>
{"".join(items) if items else "<li><em>No results found. Run experiments first, then re-deploy.</em></li>"}
</ul>
</body></html>"""

    with open(os.path.join(OUT_DIR, "index.html"), "w") as f:
        f.write(page)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    plot_dirs = find_plot_dirs()
    if not plot_dirs:
        print("No plot directories found in experiment results. Building empty index.")
        build_index([])
        return

    experiments = []
    for d in plot_dirs:
        rel = os.path.basename(d)
        name, count = build_experiment_page(d, rel)
        experiments.append((name, count))
        print(f"  {name}: {count} plots")

    build_index(experiments)
    print(f"\nSite built in {OUT_DIR}/ ({len(experiments)} experiments)")


if __name__ == "__main__":
    main()
