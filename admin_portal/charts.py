"""
Small server-rendered SVG chart helpers for the Insights page.

Follows the house dataviz method: sequential single-hue blue for magnitude
(the safe default — these are all single-series charts, no categorical
palette needed), thin marks with rounded bar ends, hairline gridlines,
sparing direct labels, and a native <title> per mark as a lightweight hover
affordance. Every chart ships next to a plain HTML table with the same
numbers, so nothing is chart-only.
"""

import html


def _nice_max(value):
    if value <= 0:
        return 1
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        candidate = step * magnitude
        if candidate >= value:
            return candidate
    return value * 1.1


def _fmt(v):
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.1f}"
    return f"{int(v):,}"


def _esc(s):
    return html.escape(str(s))


def data_table_html(headers, rows, summary_id):
    thead = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    trs = "".join(
        "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>" for row in rows
    )
    return (
        f'<details class="chart-table" id="{summary_id}">'
        f"<summary>View as table</summary>"
        f'<table><tr>{thead}</tr>{trs}</table>'
        f"</details>"
    )


def heatmap_svg(row_labels, col_labels, matrix, *, aria_label, width=680, col_label_every=3):
    """matrix[row][col] = value. Sequential blue, 5-bucket, one hue low->high.
    Rows = e.g. day of week, cols = e.g. hour of day."""
    if not matrix or not matrix[0]:
        return '<p class="muted">No data yet.</p>'

    left = 44
    top = 20
    cell_w = (width - left) / len(col_labels)
    cell_h = min(26, cell_w)
    height = top + cell_h * len(row_labels) + 22
    vmax = max((v for row in matrix for v in row), default=0) or 1

    def bucket(v):
        if v <= 0:
            return 0
        frac = v / vmax
        return min(4, max(1, round(frac * 4)))

    parts = [f'<svg viewBox="0 0 {width} {height:.0f}" width="100%" role="img" aria-label="{_esc(aria_label)}" class="chart-svg">']

    for r, row_label in enumerate(row_labels):
        y = top + cell_h * r
        parts.append(f'<text x="{left - 8}" y="{(y + cell_h / 2 + 4):.1f}" class="chart-axis-label" text-anchor="end">{_esc(row_label)}</text>')
        for c, col_label in enumerate(col_labels):
            x = left + cell_w * c
            v = matrix[r][c]
            b = bucket(v)
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="{cell_h:.1f}" '
                f'class="heat-cell heat-{b}"><title>{_esc(row_label)} {_esc(col_label)}: {_fmt(v)}</title></rect>'
            )

    label_y = top + cell_h * len(row_labels) + 14
    for c, col_label in enumerate(col_labels):
        if c % col_label_every == 0:
            x = left + cell_w * c + cell_w / 2
            parts.append(f'<text x="{x:.1f}" y="{label_y:.1f}" class="chart-axis-label" text-anchor="middle">{_esc(col_label)}</text>')

    parts.append("</svg>")
    return "".join(parts)


def heatmap_legend_html():
    swatches = "".join(f'<span class="swatch heat-{i}"></span>' for i in range(5))
    return f'<div class="heat-legend"><span>Less</span>{swatches}<span>More</span></div>'


def heatmap_table_html(row_labels, col_labels, matrix, summary_id):
    thead = "<th>&nbsp;</th>" + "".join(f"<th>{_esc(c)}</th>" for c in col_labels)
    trs = "".join(
        "<tr><th>" + _esc(row_labels[r]) + "</th>" +
        "".join(f"<td>{_fmt(v)}</td>" for v in matrix[r]) + "</tr>"
        for r in range(len(row_labels))
    )
    return (
        f'<details class="chart-table" id="{summary_id}">'
        f"<summary>View as table</summary>"
        f'<table class="heatmap-table"><tr>{thead}</tr>{trs}</table>'
        f"</details>"
    )


def bar_chart_svg(
    data, *, aria_label, width=640, height=260, label_every=1,
    show_value_labels=True, horizontal=False,
):
    """data: list of (label, value). Single-hue sequential blue, magnitude comparison."""
    if not data:
        return '<p class="muted">No data yet.</p>'

    values = [v for _, v in data]
    vmax = _nice_max(max(values) if values else 1)

    if horizontal:
        return _bar_chart_horizontal(data, vmax, aria_label, width, height, show_value_labels)
    return _bar_chart_vertical(data, vmax, aria_label, width, height, label_every, show_value_labels)


def _bar_chart_vertical(data, vmax, aria_label, width, height, label_every, show_value_labels):
    left, right, top, bottom = 44, 12, 16, 34
    plot_w = width - left - right
    plot_h = height - top - bottom
    n = len(data)
    slot = plot_w / n
    bar_w = min(24, slot * 0.6)

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(aria_label)}" class="chart-svg">']

    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        y = top + plot_h * (1 - frac)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" class="chart-grid" />')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" class="chart-axis-label" text-anchor="end">{_fmt(vmax * frac)}</text>')

    baseline = top + plot_h
    for i, (label, value) in enumerate(data):
        cx = left + slot * i + slot / 2
        bh = plot_h * (value / vmax) if vmax else 0
        by = baseline - bh
        x = cx - bar_w / 2
        r = min(4, bh) if bh > 0 else 0
        parts.append(
            f'<path d="M{x:.1f},{baseline:.1f} L{x:.1f},{(by + r):.1f} '
            f'Q{x:.1f},{by:.1f} {(x + r):.1f},{by:.1f} L{(x + bar_w - r):.1f},{by:.1f} '
            f'Q{(x + bar_w):.1f},{by:.1f} {(x + bar_w):.1f},{(by + r):.1f} '
            f'L{(x + bar_w):.1f},{baseline:.1f} Z" class="chart-bar">'
            f"<title>{_esc(label)}: {_fmt(value)}</title></path>"
        )
        if show_value_labels and value > 0:
            parts.append(f'<text x="{cx:.1f}" y="{(by - 5):.1f}" class="chart-value-label" text-anchor="middle">{_fmt(value)}</text>')
        if i % label_every == 0:
            parts.append(f'<text x="{cx:.1f}" y="{height - 12}" class="chart-axis-label" text-anchor="middle">{_esc(label)}</text>')

    parts.append(f'<line x1="{left}" y1="{baseline:.1f}" x2="{width - right}" y2="{baseline:.1f}" class="chart-axis" />')
    parts.append("</svg>")
    return "".join(parts)


def _bar_chart_horizontal(data, vmax, aria_label, width, height, show_value_labels):
    # Size the label gutter to the longest label instead of a fixed 130px:
    # labels are right-anchored at x=label_col, so anything wider than the
    # gutter runs off the left edge of the viewBox and gets silently
    # clipped ("checkout_cam / Register 1" showed as "heckout_cam ...").
    # ~6.1px per char at the 11px axis-label size, with a hard cap so a
    # pathological label can't squeeze the bars out of existence.
    longest = max((len(str(label)) for label, _ in data), default=0)
    label_col = int(min(240, max(110, longest * 6.1 + 14)))
    max_label_chars = int((label_col - 14) / 6.1)
    left, right, top, bottom = label_col, 48, 8, 8
    plot_w = width - left - right
    n = len(data)
    row_h = max(20, min(30, (height - top - bottom) / n))
    height = int(top + bottom + row_h * n)

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(aria_label)}" class="chart-svg">']
    for frac in (0, 0.5, 1.0):
        x = left + plot_w * frac
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - bottom}" class="chart-grid" />')

    bar_h = min(18, row_h * 0.6)
    for i, (label, value) in enumerate(data):
        cy = top + row_h * i + row_h / 2
        bw = plot_w * (value / vmax) if vmax else 0
        y = cy - bar_h / 2
        r = min(4, bw) if bw > 0 else 0
        # Truncate rather than clip when a label exceeds even the capped
        # gutter — the <title> on the bar still carries the full text.
        shown = str(label)
        if len(shown) > max_label_chars:
            shown = shown[: max_label_chars - 1] + "…"
        parts.append(f'<text x="{left - 8}" y="{cy + 4:.1f}" class="chart-axis-label" text-anchor="end">{_esc(shown)}</text>')
        parts.append(
            f'<path d="M{left},{(y + bar_h):.1f} L{left},{(y + r):.1f} '
            f'Q{left},{y:.1f} {(left + r):.1f},{y:.1f} L{(left + bw - r):.1f},{y:.1f} '
            f'Q{(left + bw):.1f},{y:.1f} {(left + bw):.1f},{(y + r):.1f} '
            f'L{(left + bw):.1f},{(y + bar_h):.1f} Z" class="chart-bar">'
            f"<title>{_esc(label)}: {_fmt(value)}</title></path>"
        )
        if show_value_labels:
            parts.append(f'<text x="{(left + bw + 6):.1f}" y="{cy + 4:.1f}" class="chart-value-label">{_fmt(value)}</text>')

    parts.append("</svg>")
    return "".join(parts)


def line_chart_svg(data, *, aria_label, width=640, height=240, label_every=1):
    """data: list of (x_label, value). Single series trend over time."""
    if not data:
        return '<p class="muted">No data yet.</p>'

    left, right, top, bottom = 44, 40, 16, 34
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [v for _, v in data]
    vmax = _nice_max(max(values) if values else 1)
    n = len(data)
    step = plot_w / max(1, n - 1)

    def xy(i, v):
        x = left + step * i
        y = top + plot_h * (1 - (v / vmax if vmax else 0))
        return x, y

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(aria_label)}" class="chart-svg">']
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        y = top + plot_h * (1 - frac)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" class="chart-grid" />')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" class="chart-axis-label" text-anchor="end">{_fmt(vmax * frac)}</text>')

    points = [xy(i, v) for i, (_, v) in enumerate(data)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    baseline_y = top + plot_h
    area_pts = f"{points[0][0]:.1f},{baseline_y:.1f} " + poly + f" {points[-1][0]:.1f},{baseline_y:.1f}"
    parts.append(f'<polygon points="{area_pts}" class="chart-area" />')
    parts.append(f'<polyline points="{poly}" class="chart-line" />')

    for i, ((label, value), (x, y)) in enumerate(zip(data, points)):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="chart-dot"><title>{_esc(label)}: {_fmt(value)}</title></circle>')
        if i % label_every == 0:
            parts.append(f'<text x="{x:.1f}" y="{height - 12}" class="chart-axis-label" text-anchor="middle">{_esc(label)}</text>')

    if points:
        lx, ly = points[-1]
        parts.append(f'<text x="{lx + 6:.1f}" y="{ly + 4:.1f}" class="chart-value-label">{_fmt(values[-1])}</text>')

    parts.append(f'<line x1="{left}" y1="{baseline_y:.1f}" x2="{width - right}" y2="{baseline_y:.1f}" class="chart-axis" />')
    parts.append("</svg>")
    return "".join(parts)
