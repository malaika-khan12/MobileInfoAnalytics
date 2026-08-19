"""Interactive live Streamlit dashboard for MobileInfoAnalytics.

All values are loaded from the finalized Supabase schemas through the same
server-side control-plane client used by the Flask/TypeScript frontends. No
fixture or fallback market data is used.
"""
from __future__ import annotations

import html
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.control_plane import SupabaseREST, dashboard_payload, query_view  # noqa: E402

# -----------------------------------------------------------------------------
# Visual system
# -----------------------------------------------------------------------------

PINE = "#213D31"
FOREST = "#355E4B"
MOSS = "#6B705C"
SAGE = "#A7B88D"
CREAM = "#F4F6F0"
INK = "#17231D"
PALETTE = [PINE, FOREST, MOSS, SAGE]

PLOTLY_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
    "toImageButtonOptions": {
        "format": "png",
        "filename": "mobile-market-intelligence",
        "height": 900,
        "width": 1500,
        "scale": 2,
    },
}

st.set_page_config(
    page_title="Mobile Market Intelligence",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
            --pine: {PINE}; --forest: {FOREST}; --moss: {MOSS};
            --sage: {SAGE}; --cream: {CREAM}; --ink: {INK};
        }}
        .stApp {{
            color: var(--ink);
            background:
                radial-gradient(circle at 88% 5%, rgba(167,184,141,.25), transparent 28%),
                linear-gradient(180deg, rgba(244,246,240,.96), rgba(244,246,240,.72));
        }}
        [data-testid="stHeader"] {{ background: rgba(244,246,240,.72); backdrop-filter: blur(12px); }}
        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, var(--pine), var(--forest));
            border-right: 1px solid rgba(167,184,141,.45);
        }}
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {{ color: #e9f0df; }}
        [data-testid="stSidebar"] hr {{ border-color: rgba(167,184,141,.35); }}
        [data-testid="stSidebar"] [data-baseweb="select"] > div,
        [data-testid="stSidebar"] [data-baseweb="input"] > div {{
            background: rgba(255,255,255,.08); border-color: rgba(167,184,141,.48);
        }}
        [data-testid="stSidebar"] button {{ border-color: var(--sage); color: #e9f0df; }}
        .block-container {{ max-width: 1550px; padding-top: 1.2rem; padding-bottom: 3rem; }}
        .hero {{
            padding: 1.55rem 1.65rem 1.4rem; border-radius: 20px; color: #edf3e6;
            background: linear-gradient(118deg, var(--pine), var(--forest));
            box-shadow: 0 15px 42px rgba(33,61,49,.20); margin-bottom: .9rem;
            overflow: hidden; position: relative;
        }}
        .hero:after {{
            content:""; position:absolute; width:260px; height:260px; right:-80px; top:-120px;
            border-radius:50%; border:45px solid rgba(167,184,141,.09);
        }}
        .hero-kicker {{ margin:0 0 .45rem; color:var(--sage); font-size:.72rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }}
        .hero h1 {{ margin:0; color:#f1f5ec; font-size:clamp(1.9rem,3vw,2.7rem); line-height:1.05; letter-spacing:-.035em; }}
        .hero p {{ max-width:900px; margin:.7rem 0 0; color:#d9e3d0; font-size:1rem; }}
        .hero-meta {{ display:flex; flex-wrap:wrap; gap:.55rem; margin-top:1rem; }}
        .hero-meta span {{ padding:.34rem .58rem; border:1px solid rgba(167,184,141,.28); border-radius:999px; background:rgba(255,255,255,.05); color:#dfe8d7; font-size:.74rem; }}
        [data-testid="stMetric"] {{
            min-height: 112px; padding: 1rem 1.05rem; border: 1px solid rgba(107,112,92,.28);
            border-radius: 15px; background: rgba(255,255,255,.74); box-shadow: 0 8px 24px rgba(33,61,49,.07);
        }}
        [data-testid="stMetricLabel"] {{ color:var(--moss); font-weight:700; }}
        [data-testid="stMetricValue"] {{ color:var(--pine); font-weight:800; letter-spacing:-.025em; }}
        .insight-strip {{
            display:flex; gap:.8rem; align-items:flex-start; margin:.9rem 0 1.15rem; padding:.9rem 1rem;
            border-left:5px solid var(--forest); border-radius:0 12px 12px 0; color:var(--pine); background:rgba(167,184,141,.17);
        }}
        .insight-strip strong {{ color:var(--forest); }}
        .section-heading {{ margin:.1rem 0 .05rem; color:var(--pine); font-size:1.18rem; font-weight:800; letter-spacing:-.01em; }}
        .section-copy {{ margin:0 0 .45rem; color:var(--moss); font-size:.9rem; }}
        .sample-note {{ margin:.35rem 0 1rem; padding:.7rem .85rem; border:1px solid rgba(107,112,92,.28); border-radius:10px; color:var(--moss); background:rgba(255,255,255,.58); font-size:.84rem; }}
        [data-baseweb="tab-list"] {{ gap:.45rem; border-bottom:1px solid rgba(107,112,92,.25); }}
        [data-baseweb="tab"] {{ color:var(--moss); border-radius:10px 10px 0 0; padding-left:1rem; padding-right:1rem; }}
        [aria-selected="true"][data-baseweb="tab"] {{ color:var(--pine); background:rgba(167,184,141,.16); }}
        [data-testid="stExpander"] {{ border-color:rgba(107,112,92,.27); background:rgba(255,255,255,.55); }}
        div[data-testid="stDataFrame"] {{ border:1px solid rgba(107,112,92,.25); border-radius:12px; overflow:hidden; }}
        @media (max-width:760px) {{ .block-container{{padding-left:.8rem;padding-right:.8rem}} .hero{{padding:1.15rem;border-radius:14px}} .insight-strip{{display:block}} }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def hex_rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha})"


def apply_chart_theme(fig: go.Figure, *, height: int = 470, show_legend: bool = True, margin: dict[str, int] | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=margin or {"l": 55, "r": 26, "t": 34, "b": 52},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, Segoe UI, sans-serif", "color": INK, "size": 12},
        colorway=PALETTE,
        hoverlabel={"bgcolor": PINE, "bordercolor": MOSS, "font": {"color": "#f3f6ef"}},
        showlegend=show_legend,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0, "bgcolor": "rgba(0,0,0,0)"},
    )
    fig.update_xaxes(showgrid=True, gridcolor=hex_rgba(SAGE, .30), zeroline=False, linecolor=hex_rgba(MOSS, .42), tickfont={"color": MOSS})
    fig.update_yaxes(showgrid=True, gridcolor=hex_rgba(SAGE, .30), zeroline=False, linecolor=hex_rgba(MOSS, .42), tickfont={"color": MOSS})
    return fig


def render_chart(fig: go.Figure, key: str) -> None:
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=key)


def section_heading(title: str, copy: str) -> None:
    st.markdown(
        f'<div class="section-heading">{html.escape(title)}</div><div class="section-copy">{html.escape(copy)}</div>',
        unsafe_allow_html=True,
    )


def frame(rows: Any) -> pd.DataFrame:
    return pd.DataFrame(rows or [])


def safe_number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def compact_number(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def money(value: float | int | None, currency: str = "") -> str:
    if value is None or pd.isna(value):
        return "—"
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{float(value):,.2f}"


# -----------------------------------------------------------------------------
# Chart builders
# -----------------------------------------------------------------------------


def source_coverage_chart(sources: pd.DataFrame) -> go.Figure:
    data = sources.copy()
    for column in ["total_listings", "distinct_products_covered", "avg_data_completeness_pct"]:
        data[column] = pd.to_numeric(data.get(column), errors="coerce")
    data = data.sort_values("total_listings", ascending=False)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=data["source_domain"], y=data["total_listings"], name="Listings",
            marker={"color": FOREST, "line": {"color": PINE, "width": .7}},
            customdata=data[["distinct_products_covered", "avg_data_completeness_pct"]].to_numpy(),
            hovertemplate="<b>%{x}</b><br>Listings: %{y:,}<br>Distinct products: %{customdata[0]:,.0f}<br>Completeness: %{customdata[1]:.1f}%<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=data["source_domain"], y=data["avg_data_completeness_pct"], name="Completeness",
            mode="lines+markers", line={"color": SAGE, "width": 3}, marker={"size": 10, "color": SAGE, "line": {"color": PINE, "width": 1}},
            hovertemplate="<b>%{x}</b><br>Completeness: %{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_yaxes(title="Listings", secondary_y=False)
    fig.update_yaxes(title="Completeness", ticksuffix="%", range=[0, 105], secondary_y=True, showgrid=False)
    fig.update_xaxes(title="Source")
    return apply_chart_theme(fig, height=500)


def source_quality_scatter(sources: pd.DataFrame) -> go.Figure:
    data = sources.copy()
    data["total_listings"] = pd.to_numeric(data["total_listings"], errors="coerce").fillna(0)
    data["distinct_products_covered"] = pd.to_numeric(data["distinct_products_covered"], errors="coerce").fillna(0)
    data["avg_data_completeness_pct"] = pd.to_numeric(data["avg_data_completeness_pct"], errors="coerce")
    maximum = max(1.0, float(data["distinct_products_covered"].max() or 1))
    sizes = 18 + 38 * np.sqrt(data["distinct_products_covered"] / maximum)
    fig = go.Figure(
        go.Scatter(
            x=data["total_listings"], y=data["avg_data_completeness_pct"], mode="markers+text",
            text=data["source_domain"], textposition="top center",
            marker={"size": sizes, "color": data["avg_data_completeness_pct"], "colorscale": [[0, MOSS], [.55, FOREST], [1, SAGE]], "cmin": 0, "cmax": 100, "showscale": True, "colorbar": {"title": "Completeness", "ticksuffix": "%", "thickness": 14}, "line": {"color": PINE, "width": 1}, "opacity": .88},
            customdata=data[["distinct_products_covered", "last_scraped_at"]].to_numpy(),
            hovertemplate="<b>%{text}</b><br>Listings: %{x:,}<br>Completeness: %{y:.1f}%<br>Distinct products: %{customdata[0]:,.0f}<br>Last scrape: %{customdata[1]}<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_xaxes(title="Market listings")
    fig.update_yaxes(title="Average completeness", ticksuffix="%", range=[0, 105])
    return apply_chart_theme(fig, height=500, show_legend=False)


def category_bar(rows: list[dict[str, Any]], title: str) -> go.Figure:
    data = pd.DataFrame(rows)
    if data.empty:
        return go.Figure()
    data = data.sort_values("count", ascending=True)
    fig = go.Figure(
        go.Bar(
            x=data["count"], y=data["label"], orientation="h",
            marker={"color": [PALETTE[i % len(PALETTE)] for i in range(len(data))], "line": {"color": PINE, "width": .5}},
            text=[f"{int(value):,}" for value in data["count"]], textposition="outside",
            hovertemplate="<b>%{y}</b><br>Products in sample: %{x:,}<extra></extra>", showlegend=False,
        )
    )
    fig.update_xaxes(title="Products in analytics sample")
    fig.update_yaxes(title="")
    fig.add_annotation(x=0, y=1.10, xref="paper", yref="paper", text=title, showarrow=False, font={"color": MOSS, "size": 11}, xanchor="left")
    return apply_chart_theme(fig, height=470, show_legend=False)


def category_donut(rows: list[dict[str, Any]], center: str) -> go.Figure:
    data = pd.DataFrame(rows)
    fig = go.Figure(
        go.Pie(
            labels=data.get("label", []), values=data.get("count", []), hole=.62, sort=False,
            marker={"colors": [PALETTE[i % len(PALETTE)] for i in range(len(data))], "line": {"color": CREAM, "width": 2}},
            textinfo="label+percent", textposition="outside",
            hovertemplate="<b>%{label}</b><br>Products: %{value:,}<br>Share: %{percent}<extra></extra>",
        )
    )
    fig.add_annotation(x=.5, y=.5, text=f"<b>{center}</b><br>sample", showarrow=False, font={"color": PINE, "size": 13})
    return apply_chart_theme(fig, height=470, show_legend=False, margin={"l": 24, "r": 24, "t": 32, "b": 34})


def release_year_chart(rows: list[dict[str, Any]]) -> go.Figure:
    data = pd.DataFrame(rows)
    if data.empty:
        return go.Figure()
    known = data[data["label"].astype(str).str.fullmatch(r"\d{4}")].copy()
    known["year"] = pd.to_numeric(known["label"], errors="coerce")
    known = known.sort_values("year")
    fig = go.Figure(
        go.Bar(
            x=known["year"], y=known["count"], marker={"color": FOREST, "line": {"color": PINE, "width": .6}},
            text=known["count"], textposition="outside", hovertemplate="Release year: %{x:.0f}<br>Products: %{y:,}<extra></extra>", showlegend=False,
        )
    )
    fig.update_xaxes(title="Release year", dtick=1)
    fig.update_yaxes(title="Products in sample")
    return apply_chart_theme(fig, height=440, show_legend=False)


def technology_scatter(rows: list[dict[str, Any]]) -> go.Figure:
    data = pd.DataFrame(rows)
    if data.empty:
        return go.Figure()
    data["capacity_mah"] = pd.to_numeric(data["capacity_mah"], errors="coerce")
    data["refresh_rate_hz"] = pd.to_numeric(data["refresh_rate_hz"], errors="coerce")
    data["pixel_density_ppi"] = pd.to_numeric(data["pixel_density_ppi"], errors="coerce")
    data = data.dropna(subset=["capacity_mah", "refresh_rate_hz"])
    if data.empty:
        return go.Figure()
    ppi = data["pixel_density_ppi"].fillna(data["pixel_density_ppi"].median() if data["pixel_density_ppi"].notna().any() else 300)
    ppi_min, ppi_max = float(ppi.min()), float(ppi.max())
    sizes = np.full(len(ppi), 12.0) if math.isclose(ppi_min, ppi_max) else 8 + 22 * np.sqrt((ppi - ppi_min) / (ppi_max - ppi_min))
    fig = go.Figure()
    screens = list(data["screen_technology"].fillna("Unknown").astype(str).value_counts().index)
    for index, screen in enumerate(screens):
        part = data[data["screen_technology"].fillna("Unknown").astype(str).eq(screen)]
        idx = part.index
        fig.add_trace(
            go.Scatter(
                x=part["capacity_mah"], y=part["refresh_rate_hz"], mode="markers", name=screen,
                marker={"size": pd.Series(sizes, index=data.index).loc[idx], "color": PALETTE[index % len(PALETTE)], "opacity": .72, "line": {"color": PINE, "width": .5}},
                customdata=part[["company_name", "mobile_name", "pixel_density_ppi", "supports_5g", "release_year"]].to_numpy(),
                hovertemplate="<b>%{customdata[0]} %{customdata[1]}</b><br>Battery: %{x:,.0f} mAh<br>Refresh: %{y:,.0f} Hz<br>Pixel density: %{customdata[2]} ppi<br>5G: %{customdata[3]}<br>Release year: %{customdata[4]}<extra></extra>",
            )
        )
    fig.update_xaxes(title="Battery capacity · mAh")
    fig.update_yaxes(title="Refresh rate · Hz")
    return apply_chart_theme(fig, height=540)


def adoption_donut(label: str, yes_count: int, sample_size: int) -> go.Figure:
    no_count = max(0, sample_size - yes_count)
    fig = go.Figure(
        go.Pie(
            labels=["Yes", "No"], values=[yes_count, no_count], hole=.68, sort=False,
            marker={"colors": [FOREST, hex_rgba(SAGE, .55)], "line": {"color": CREAM, "width": 2}},
            textinfo="percent", hovertemplate="%{label}: %{value:,} products (%{percent})<extra></extra>",
        )
    )
    pct = 100 * yes_count / sample_size if sample_size else 0
    fig.add_annotation(x=.5, y=.5, text=f"<b>{pct:.1f}%</b><br>{html.escape(label)}", showarrow=False, font={"color": PINE, "size": 13})
    return apply_chart_theme(fig, height=400, show_legend=False, margin={"l": 20, "r": 20, "t": 25, "b": 20})


def price_range_chart(prices: pd.DataFrame, currency: str | None = None) -> go.Figure:
    data = prices.copy()
    for column in ["min_price", "avg_price", "max_price", "price_spread"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if currency and currency != "All":
        data = data[data["currency_code"].astype(str).eq(currency)]
    data = data.dropna(subset=["min_price", "max_price"]).head(15).copy()
    data["label"] = (data["company_name"].astype(str) + " " + data["mobile_name"].astype(str)).str.slice(0, 44)
    data = data.sort_values("price_spread", ascending=True)
    fig = go.Figure()
    for row in data.itertuples(index=False):
        fig.add_trace(
            go.Scatter(
                x=[row.min_price, row.max_price], y=[row.label, row.label], mode="lines",
                line={"color": MOSS, "width": 7}, opacity=.58, showlegend=False, hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=data["avg_price"], y=data["label"], mode="markers", name="Average",
            marker={"size": 11, "color": PINE, "line": {"color": CREAM, "width": 1}},
            customdata=data[["currency_code", "min_price", "max_price", "price_spread", "sources_count"]].to_numpy(),
            hovertemplate="<b>%{y}</b><br>Average: %{x:,.2f} %{customdata[0]}<br>Min: %{customdata[1]:,.2f}<br>Max: %{customdata[2]:,.2f}<br>Spread: %{customdata[3]:,.2f}<br>Sources: %{customdata[4]}<extra></extra>",
        )
    )
    fig.update_xaxes(title="Price")
    fig.update_yaxes(title="")
    return apply_chart_theme(fig, height=600, show_legend=False, margin={"l": 165, "r": 30, "t": 30, "b": 55})


def price_spread_scatter(prices: pd.DataFrame) -> go.Figure:
    data = prices.copy()
    for column in ["avg_price", "price_spread", "sources_count", "total_listings"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["avg_price", "price_spread"])
    if data.empty:
        return go.Figure()
    source_max = max(1.0, float(data["sources_count"].fillna(1).max()))
    size = 11 + 30 * np.sqrt(data["sources_count"].fillna(1) / source_max)
    fig = go.Figure(
        go.Scatter(
            x=data["avg_price"], y=data["price_spread"], mode="markers", text=data["mobile_name"],
            marker={"size": size, "color": data["sources_count"], "colorscale": [[0, MOSS], [.5, FOREST], [1, SAGE]], "showscale": True, "colorbar": {"title": "Sources", "thickness": 14}, "line": {"color": PINE, "width": .6}, "opacity": .76},
            customdata=data[["company_name", "currency_code", "sources_count", "total_listings"]].to_numpy(),
            hovertemplate="<b>%{customdata[0]} %{text}</b><br>Average price: %{x:,.2f} %{customdata[1]}<br>Spread: %{y:,.2f}<br>Sources: %{customdata[2]}<br>Listings: %{customdata[3]}<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_xaxes(title="Average price")
    fig.update_yaxes(title="Cross-site price spread")
    return apply_chart_theme(fig, height=520, show_legend=False)


def discrepancy_heatmap(rows: list[dict[str, Any]]) -> go.Figure:
    data = pd.DataFrame(rows)
    if data.empty:
        return go.Figure()
    sources = data["source_domain"].astype(str).tolist()
    z = data[["battery_pct", "screen_pct", "refresh_pct"]].astype(float).to_numpy()
    fig = go.Figure(
        go.Heatmap(
            z=z, x=["Battery", "Screen technology", "Refresh rate"], y=sources,
            zmin=0, zmax=max(1.0, float(np.nanmax(z))), colorscale=[[0, CREAM], [.35, SAGE], [.72, FOREST], [1, PINE]],
            colorbar={"title": "Discrepancy %", "ticksuffix": "%", "thickness": 14},
            hovertemplate="<b>%{y}</b><br>%{x}: %{z:.1f}% discrepancy rate<extra></extra>",
        )
    )
    for y_index, source in enumerate(sources):
        for x_index in range(3):
            value = z[y_index, x_index]
            fig.add_annotation(x=x_index, y=source, text=f"{value:.1f}%", showarrow=False, font={"color": PINE if value < 45 else "#f4f6f0", "size": 10})
    fig.update_xaxes(title="")
    fig.update_yaxes(title="")
    return apply_chart_theme(fig, height=max(360, 90 + len(sources) * 62), show_legend=False, margin={"l": 125, "r": 40, "t": 35, "b": 55})


def freshness_chart(sources: pd.DataFrame) -> go.Figure:
    data = sources.copy()
    data["last_scraped_at"] = pd.to_datetime(data["last_scraped_at"], errors="coerce", utc=True)
    data = data.dropna(subset=["last_scraped_at"]).sort_values("last_scraped_at")
    fig = go.Figure(
        go.Scatter(
            x=data["last_scraped_at"], y=data["source_domain"], mode="markers",
            marker={"size": 18, "color": FOREST, "symbol": "diamond", "line": {"color": PINE, "width": 1}},
            customdata=data[["total_listings", "avg_data_completeness_pct"]].to_numpy(),
            hovertemplate="<b>%{y}</b><br>Last scraped: %{x}<br>Listings: %{customdata[0]:,}<br>Completeness: %{customdata[1]:.1f}%<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_xaxes(title="Last scraped timestamp")
    fig.update_yaxes(title="")
    return apply_chart_theme(fig, height=390, show_legend=False)


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------


def sidebar_filters(scatter: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.markdown("## Product sample filters")
    st.sidebar.caption("Filters apply to product-technology charts only. Source and market charts remain full live summaries.")
    if scatter.empty:
        st.sidebar.info("No canonical product sample is currently available.")
        return scatter

    companies = sorted(scatter["company_name"].dropna().astype(str).unique())
    screens = sorted(scatter["screen_technology"].fillna("Unknown").astype(str).unique())
    years = sorted({int(value) for value in pd.to_numeric(scatter["release_year"], errors="coerce").dropna()}, reverse=True)
    selected_companies = st.sidebar.multiselect("Companies", companies, default=companies)
    selected_screens = st.sidebar.multiselect("Screen technology", screens, default=screens)
    selected_years = st.sidebar.multiselect("Release years", years, default=years)
    network = st.sidebar.radio("5G support", ["All", "5G only", "Non-5G only"], horizontal=False)

    mask = scatter["company_name"].astype(str).isin(selected_companies)
    mask &= scatter["screen_technology"].fillna("Unknown").astype(str).isin(selected_screens)
    numeric_year = pd.to_numeric(scatter["release_year"], errors="coerce")
    if selected_years:
        mask &= numeric_year.isin(selected_years) | numeric_year.isna()
    if network == "5G only":
        mask &= scatter["supports_5g"].astype(bool)
    elif network == "Non-5G only":
        mask &= ~scatter["supports_5g"].astype(bool)
    filtered = scatter.loc[mask].copy()
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**{len(filtered):,} products** in filtered technology sample")
    return filtered


def live_insight(payload: dict[str, Any]) -> str:
    sources = payload.get("sources", [])
    leader = max(sources, key=lambda row: safe_number(row.get("total_listings")) or 0, default=None)
    company_counts = payload.get("product_insights", {}).get("company_counts", [])
    brand = company_counts[0] if company_counts else None
    price_rows = payload.get("price_spreads", [])
    spread = price_rows[0] if price_rows else None
    bits = []
    if leader:
        bits.append(f"<strong>{html.escape(str(leader.get('source_domain')))}</strong> currently carries the largest listing footprint at {int(safe_number(leader.get('total_listings')) or 0):,} rows")
    if brand:
        bits.append(f"<strong>{html.escape(str(brand.get('label')))}</strong> is the most represented brand in the bounded canonical-product sample")
    if spread and safe_number(spread.get("price_spread")) is not None:
        bits.append(f"the largest returned cross-site spread is <strong>{safe_number(spread.get('price_spread')):,.2f} {html.escape(str(spread.get('currency_code') or ''))}</strong> for {html.escape(str(spread.get('company_name') or ''))} {html.escape(str(spread.get('mobile_name') or ''))}")
    return "; ".join(bits) + "." if bits else "Live analytics are connected; richer insight text will appear as the database fills."


def main() -> None:
    inject_css()
    client = SupabaseREST()

    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Production mobile-market analytics</div>
          <h1>Mobile Market Intelligence</h1>
          <p>Explore catalogue growth, source coverage, technology patterns, price dispersion, data quality, and scraper freshness directly from the finalized Supabase database.</p>
          <div class="hero-meta"><span>Live Supabase analytics</span><span>No fixture data</span><span>Cross-source comparison</span><span>Production ETL observability</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not client.configured:
        st.error("Supabase is not configured. Set SUPABASE_URL and a server-side SUPABASE_SECRET_KEY/SUPABASE_KEY in this repository's .env file.")
        st.stop()

    try:
        payload = dashboard_payload(client)
    except Exception as exc:
        st.error(f"Could not load live database analytics: {exc}")
        st.stop()

    metrics = payload["metrics"]
    products = payload.get("product_insights", {})
    sources = frame(payload.get("sources"))
    prices = frame(payload.get("price_spreads"))
    scatter = frame(products.get("scatter"))
    filtered_scatter = sidebar_filters(scatter)

    columns = st.columns(6)
    columns[0].metric("Companies", f"{metrics['companies']:,}", "catalog.companies")
    columns[1].metric("Canonical products", f"{metrics['products']:,}", "catalog.products")
    columns[2].metric("Market listings", f"{metrics['listings']:,}", f"{len(sources):,} populated sources")
    columns[3].metric("Price observations", f"{metrics['price_entries']:,}", "listings.listing_prices")
    completeness = metrics.get("avg_completeness_pct")
    columns[4].metric("Mean completeness", "—" if completeness is None else f"{completeness:.1f}%", "latest quality scores")
    five_g = products.get("five_g_pct")
    columns[5].metric("5G in sample", "—" if five_g is None else f"{five_g:.1f}%", f"latest {products.get('sample_size', 0):,} products")

    st.markdown(f'<div class="insight-strip"><span>◆</span><span>{live_insight(payload)}</span></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sample-note"><strong>Analytics scope:</strong> total catalogue/listing metrics and source summaries are live population-level database values. Technology distributions use the latest <strong>{int(products.get("sample_size") or 0):,}</strong> canonical products; discrepancy rates use the latest <strong>{int(payload.get("discrepancy_insights", {}).get("sample_size") or 0):,}</strong> cross-source comparison rows. The UI labels these samples rather than presenting them as whole-database statistics.</div>',
        unsafe_allow_html=True,
    )

    overview_tab, technology_tab, price_tab, quality_tab = st.tabs([
        "Market overview", "Product technology", "Price intelligence", "Quality & freshness"
    ])

    with overview_tab:
        section_heading("Source coverage and data quality", "Compare listing footprint with average completeness across each populated market source.")
        if sources.empty:
            st.info("No source summary rows are currently available.")
        else:
            left, right = st.columns([1.08, .92], gap="large")
            with left:
                render_chart(source_coverage_chart(sources), "source-coverage")
            with right:
                render_chart(source_quality_scatter(sources), "source-quality")

        st.markdown("---")
        left, right = st.columns([1.1, .9], gap="large")
        with left:
            section_heading("Brand representation", "Top companies in the bounded latest-product analytics sample.")
            render_chart(category_bar(products.get("company_counts", []), "Latest canonical-product sample"), "brand-mix")
        with right:
            section_heading("Screen technology mix", "Relative technology mix among the same canonical-product sample.")
            render_chart(category_donut(products.get("screen_counts", []), f"n={products.get('sample_size', 0):,}"), "screen-mix")

        section_heading("Release-year distribution", "How the latest canonical-product sample is distributed across declared release years.")
        render_chart(release_year_chart(products.get("release_year_counts", [])), "release-years")

        with st.expander("Inspect recent canonical products", expanded=False):
            recent = frame(payload.get("recent_products"))
            if recent.empty:
                st.info("No canonical product rows were returned.")
            else:
                visible = [column for column in ["product_id", "company_name", "mobile_name", "release_year", "screen_technology", "refresh_rate_hz", "pixel_density_ppi", "operating_system", "chipset_name", "capacity_mah", "supports_5g"] if column in recent.columns]
                st.dataframe(recent[visible], use_container_width=True, hide_index=True, height=420)

    with technology_tab:
        section_heading("Technology landscape", "Battery capacity, display refresh rate, and pixel density reveal how recent devices cluster by display technology.")
        if filtered_scatter.empty:
            st.info("No products match the current sidebar technology filters.")
        else:
            render_chart(technology_scatter(filtered_scatter.to_dict("records")), "technology-scatter")

        left, right, third = st.columns(3, gap="large")
        with left:
            section_heading("5G adoption", "Share of the bounded canonical-product sample with 5G support.")
            render_chart(adoption_donut("5G", int(products.get("five_g_count") or 0), int(products.get("sample_size") or 0)), "five-g-donut")
        with right:
            section_heading("Wireless charging", "Share of the same sample that reports wireless charging support.")
            render_chart(adoption_donut("wireless", int(products.get("wireless_charging_count") or 0), int(products.get("sample_size") or 0)), "wireless-donut")
        with third:
            section_heading("Battery profile", "Central battery-capacity statistics from products with populated capacity values.")
            st.metric("Average battery", "—" if products.get("battery_avg_mah") is None else f"{products['battery_avg_mah']:,.0f} mAh")
            st.metric("Median battery", "—" if products.get("battery_median_mah") is None else f"{products['battery_median_mah']:,.0f} mAh")
            st.metric("Products sampled", f"{int(products.get('sample_size') or 0):,}")

        left, right = st.columns(2, gap="large")
        with left:
            section_heading("Operating-system families", "OS-family mix in the bounded product sample.")
            render_chart(category_bar(products.get("os_counts", []), "Operating-system families"), "os-families")
        with right:
            section_heading("Filtered product records", "The sidebar filters apply here and to the technology scatter.")
            visible = [column for column in ["company_name", "mobile_name", "release_year", "supports_5g", "screen_technology", "refresh_rate_hz", "pixel_density_ppi", "operating_system", "capacity_mah", "has_wireless_charging"] if column in filtered_scatter.columns]
            st.dataframe(filtered_scatter[visible].head(160), use_container_width=True, hide_index=True, height=460)

    with price_tab:
        section_heading("Cross-site price dispersion", "Range bars show minimum-to-maximum observed price; the dark marker is the mean price.")
        if prices.empty:
            st.info("No cross-site price comparison rows are currently available.")
        else:
            currencies = ["All"] + sorted(prices["currency_code"].dropna().astype(str).unique())
            currency = st.selectbox("Currency", currencies, key="price_currency")
            render_chart(price_range_chart(prices, currency), "price-range")
            section_heading("Average price versus spread", "Bubble size represents the number of distinct sources contributing to each comparison row.")
            render_chart(price_spread_scatter(prices if currency == "All" else prices[prices["currency_code"].astype(str).eq(currency)]), "price-spread-scatter")

            with st.expander("Inspect largest returned price spreads", expanded=False):
                visible = [column for column in ["company_name", "mobile_name", "currency_code", "sources_count", "total_listings", "min_price", "avg_price", "max_price", "price_spread"] if column in prices.columns]
                st.dataframe(prices[visible], use_container_width=True, hide_index=True, height=430)

    with quality_tab:
        section_heading("Specification discrepancy matrix", "Rates compare marketplace-listing fields with canonical specifications for the bounded discrepancy sample.")
        discrepancies = payload.get("discrepancy_insights", {}).get("by_source", [])
        if discrepancies:
            render_chart(discrepancy_heatmap(discrepancies), "discrepancy-heatmap")
        else:
            st.info("No cross-source discrepancy rows are currently available.")

        left, right = st.columns([.92, 1.08], gap="large")
        with left:
            section_heading("Source freshness", "Latest marketplace scrape timestamp reported by analytics.v_site_summary.")
            if not sources.empty:
                render_chart(freshness_chart(sources), "source-freshness")
        with right:
            section_heading("Source detail", "Coverage, completeness, and scrape-window timestamps.")
            if not sources.empty:
                st.dataframe(sources, use_container_width=True, hide_index=True, height=390)

        runs = frame(payload.get("recent_runs"))
        section_heading("Recent ingestion runs", "Direct metadata.scrape_runs history available to this local Streamlit operator dashboard.")
        if runs.empty:
            st.info("No recent scrape-run rows were returned.")
        else:
            st.dataframe(runs, use_container_width=True, hide_index=True, height=390)

        with st.expander("Search the canonical product view", expanded=False):
            search = st.text_input("Search company, model, chipset or OS", key="canonical_search")
            limit = st.slider("Rows", 10, 100, 40, 10, key="canonical_rows")
            if search:
                try:
                    result = query_view(client, "products", limit=limit, search=search)
                    result_df = frame(result.get("rows"))
                    st.caption(f"{result.get('total', len(result_df)):,} matching row(s) reported; showing up to {limit}.")
                    st.dataframe(result_df, use_container_width=True, hide_index=True, height=430)
                except Exception as exc:
                    st.error(f"Search failed: {exc}")
            else:
                st.caption("Enter a search term to query the live analytics.v_canonical_products view.")

    st.caption(f"Dashboard generated from live Supabase data at {payload.get('generated_at', '—')} · no dummy-data fallback is implemented.")


if __name__ == "__main__":
    main()
