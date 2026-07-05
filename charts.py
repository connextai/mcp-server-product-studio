"""Inline-SVG chart builders for the ``chart`` MCP App.

Two small, self-contained, theme-aware charts derived from the product data:

  * ``roadmap_bar``     — a single-series magnitude chart: feature count per NPD
                          stage (idea → ga), one hue.
  * ``adoption_line``   — a two-series time chart: adoption + retention over the
                          weeks, with a legend and direct end-labels.

Design follows the dataviz method: thin marks, recessive grid/axes, a legend for
the 2-series chart plus direct labels (which also satisfies the light-surface
relief rule for the aqua series), and a **validated** 2-colour palette
(blue #2a78d6 / aqua #1baf7a on light, #3987e5 / #199e70 on dark — CVD ΔE 73.6).
Everything is inline SVG + CSS (no scripts, no external assets) so it renders
under the MCP App iframe's strict Content-Security-Policy, and it uses the host's
``--mcp-color-*`` theme variables so it matches light/dark automatically.
"""

from __future__ import annotations

STAGE_ORDER = ["idea", "discovery", "design", "build", "beta", "ga"]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- 1. Roadmap: feature count per stage (single series) --------------------
def roadmap_bar(counts: dict[str, int]) -> str:
    """SVG bar chart of feature counts per stage (stages in NPD order)."""
    W, H = 560, 280
    pad_l, pad_r, pad_t, pad_b = 34, 14, 26, 46
    pw, ph = W - pad_l - pad_r, H - pad_t - pad_b
    data = [(s, counts.get(s, 0)) for s in STAGE_ORDER]
    vmax = max([c for _, c in data] + [1])
    n = len(data)
    slot = pw / n
    bw = slot * 0.56
    bars, labels = [], []
    for i, (stage, c) in enumerate(data):
        x = pad_l + i * slot + (slot - bw) / 2
        bh = (c / vmax) * ph
        y = pad_t + ph - bh
        # 4px rounded top, anchored to the baseline.
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(bh,0.5):.1f}" '
            f'rx="4" fill="var(--c-blue)"/>'
        )
        if c:
            labels.append(
                f'<text x="{x + bw / 2:.1f}" y="{y - 6:.1f}" class="val">{c}</text>'
            )
        labels.append(
            f'<text x="{x + bw / 2:.1f}" y="{pad_t + ph + 16:.1f}" class="cat">'
            f"{_esc(stage)}</text>"
        )
    baseline = (
        f'<line x1="{pad_l}" y1="{pad_t + ph:.1f}" x2="{W - pad_r}" '
        f'y2="{pad_t + ph:.1f}" class="axis"/>'
    )
    return (
        f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
        f'aria-label="Features by stage">{baseline}{"".join(bars)}'
        f'{"".join(labels)}</svg>'
    )


# --- 2. Adoption + retention over time (two series) -------------------------
def adoption_line(weeks: list[str], adoption: list[float], retention: list[float]) -> str:
    """SVG line chart of adoption + retention (fractions) over the weeks."""
    W, H = 560, 280
    pad_l, pad_r, pad_t, pad_b = 36, 74, 22, 34
    pw, ph = W - pad_l - pad_r, H - pad_t - pad_b
    n = max(len(weeks), 1)
    xs = [pad_l + (pw * i / max(n - 1, 1)) for i in range(n)]

    def y(v: float) -> float:
        return pad_t + ph - v * ph  # 0..1 maps to full height

    grid = []
    for g in (0.0, 0.25, 0.5, 0.75, 1.0):
        gy = y(g)
        grid.append(
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l + pw:.1f}" y2="{gy:.1f}" '
            f'class="grid"/>'
            f'<text x="{pad_l - 6}" y="{gy + 3:.1f}" class="tick">{int(g * 100)}%</text>'
        )

    def polyline(vals: list[float], var: str) -> str:
        pts = " ".join(f"{xs[i]:.1f},{y(v):.1f}" for i, v in enumerate(vals))
        dots = "".join(
            f'<circle cx="{xs[i]:.1f}" cy="{y(v):.1f}" r="2.5" fill="var({var})"/>'
            for i, v in enumerate(vals)
        )
        return (
            f'<polyline points="{pts}" fill="none" stroke="var({var})" '
            f'stroke-width="2"/>{dots}'
        )

    # Direct end-labels (also the light-surface relief for the aqua series).
    end_labels = ""
    if n:
        end_labels = (
            f'<text x="{xs[-1] + 8:.1f}" y="{y(adoption[-1]) + 3:.1f}" '
            f'class="end" style="fill:var(--c-blue)">Adoption</text>'
            f'<text x="{xs[-1] + 8:.1f}" y="{y(retention[-1]) + 3:.1f}" '
            f'class="end" style="fill:var(--c-aqua)">Retention</text>'
        )
    return (
        f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
        f'aria-label="Adoption and retention over time">'
        f'{"".join(grid)}{polyline(adoption, "--c-blue")}'
        f'{polyline(retention, "--c-aqua")}{end_labels}</svg>'
    )


# --- MCP App HTML wrapper (self-contained, theme-aware) ---------------------
def app_html(title: str, subtitle: str, svg: str, legend: list[tuple[str, str]] | None = None) -> str:
    """Wrap an SVG in the self-contained HTML the MCP App iframe renders."""
    legend_html = ""
    if legend:
        items = "".join(
            f'<span class="lg"><i style="background:var({var})"></i>{_esc(name)}</span>'
            for name, var in legend
        )
        legend_html = f'<div class="legend">{items}</div>'
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      /* Validated categorical hues, themed for light/dark. */
      :root {{ --c-blue: #2a78d6; --c-aqua: #1baf7a; }}
      @media (prefers-color-scheme: dark) {{ :root {{ --c-blue:#3987e5; --c-aqua:#199e70; }} }}
      :root[data-theme="dark"] {{ --c-blue:#3987e5; --c-aqua:#199e70; }}
      :root[data-theme="light"] {{ --c-blue:#2a78d6; --c-aqua:#1baf7a; }}
      body {{ font-family: system-ui, sans-serif; margin: 0;
              color: var(--mcp-color-text, #1a1a1a); }}
      .card {{ margin: 1rem; padding: 1rem 1.25rem; border-radius: 12px;
               border: 1px solid var(--mcp-color-border, #e3e3e8);
               background: var(--mcp-color-surface, #ffffff); }}
      h2 {{ font-size: 1.05rem; margin: 0; }}
      .sub {{ font-size: .8rem; opacity: .6; margin: .15rem 0 .5rem; }}
      .legend {{ display: flex; gap: 1rem; font-size: .78rem; opacity: .85; margin-top: .25rem; }}
      .lg {{ display: inline-flex; align-items: center; gap: .35rem; }}
      .lg i {{ width: 10px; height: 10px; border-radius: 3px; display: inline-block; }}
      svg text {{ fill: var(--mcp-color-text, #1a1a1a); }}
      .val {{ font-size: 11px; font-weight: 600; text-anchor: middle; }}
      .cat {{ font-size: 10px; text-anchor: middle; opacity: .6; }}
      .tick {{ font-size: 9px; text-anchor: end; opacity: .5; }}
      .end {{ font-size: 10px; font-weight: 600; }}
      .axis {{ stroke: var(--mcp-color-border, #d8d8de); stroke-width: 1; }}
      .grid {{ stroke: var(--mcp-color-border, #ececf0); stroke-width: 1; opacity: .6; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h2>{_esc(title)}</h2>
      <div class="sub">{_esc(subtitle)}</div>
      {svg}
      {legend_html}
    </div>
  </body>
</html>"""
