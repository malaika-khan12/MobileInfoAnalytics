"""Interactive telecom churn dashboard.

Run:
    pip install streamlit plotly pandas numpy
    streamlit run telecom_churn_dashboard.py

Place ``master_view_v1.csv`` beside this file, or upload it from the app sidebar.
"""

from __future__ import annotations

import html
import io
import math
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# -----------------------------------------------------------------------------
# Visual system
# -----------------------------------------------------------------------------

DARK = "#304D3D"
SAGE = "#A7B88D"
MOSS = "#6B705C"
FOREST = "#3A5A40"
PALETTE = [DARK, MOSS, SAGE, FOREST]

STATUS_COLORS = {"Churned": DARK, "Retained": SAGE}
STATUS_SYMBOLS = {"Churned": "diamond", "Retained": "circle"}

PLOTLY_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
    "toImageButtonOptions": {
        "format": "png",
        "filename": "telecom-retention-analysis",
        "height": 900,
        "width": 1500,
        "scale": 2,
    },
}

NUMERIC_COLUMNS = [
    "age",
    "tenure_months",
    "married",
    "phone_service",
    "number_of_dependents",
    "number_of_referrals",
    "avg_monthly_gb_download",
    "monthly_charges",
    "total_charges",
    "total_refunds",
    "total_extra_data_charges",
    "total_long_distance_charges",
    "total_revenue",
    "satisfaction_score",
    "cltv",
    "churn_score",
]

CATEGORICAL_COLUMNS = [
    "gender",
    "city",
    "offer",
    "internet_type",
    "contract",
    "payment_method",
    "customer_status",
    "online_backup",
    "device_protection",
    "tech_support",
    "streaming_tv",
    "streaming_movies",
]

FILTER_STATE_KEYS = [
    "flt_status",
    "flt_contract",
    "flt_internet",
    "flt_age",
    "flt_tenure",
    "flt_satisfaction",
    "flt_risk",
    "flt_charges",
    "flt_gender",
    "flt_payment",
    "flt_offer",
    "flt_city",
]


st.set_page_config(
    page_title="Customer Retention Intelligence",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    """Apply a compact, accessible theme using only the requested colours."""

    st.markdown(
        f"""
        <style>
        :root {{
            --pine: {DARK};
            --sage: {SAGE};
            --moss: {MOSS};
            --forest: {FOREST};
        }}

        .stApp {{
            color: var(--pine);
            background:
                radial-gradient(circle at 85% 8%, rgba(167,184,141,.24), transparent 28%),
                linear-gradient(180deg, rgba(167,184,141,.10), rgba(167,184,141,.03));
        }}

        [data-testid="stHeader"] {{
            background: rgba(167,184,141,.08);
        }}

        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, var(--pine), var(--forest));
            border-right: 1px solid var(--sage);
        }}

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {{
            color: var(--sage);
        }}

        [data-testid="stSidebar"] hr {{
            border-color: rgba(167,184,141,.35);
        }}

        [data-testid="stSidebar"] [data-baseweb="select"] > div,
        [data-testid="stSidebar"] [data-baseweb="input"] > div,
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{
            background: rgba(167,184,141,.10);
            border-color: rgba(167,184,141,.48);
        }}

        [data-testid="stSidebar"] button {{
            border-color: var(--sage);
            color: var(--sage);
        }}

        .block-container {{
            max-width: 1540px;
            padding-top: 1.4rem;
            padding-bottom: 3rem;
        }}

        .hero {{
            padding: 1.35rem 1.5rem 1.25rem;
            border-radius: 18px;
            color: var(--sage);
            background: linear-gradient(118deg, var(--pine), var(--forest));
            box-shadow: 0 12px 32px rgba(48,77,61,.18);
            margin-bottom: .8rem;
        }}

        .hero-kicker {{
            margin: 0 0 .45rem;
            color: var(--sage);
            font-size: .74rem;
            font-weight: 700;
            letter-spacing: .13em;
            text-transform: uppercase;
        }}

        .hero h1 {{
            margin: 0;
            color: var(--sage);
            font-size: clamp(1.75rem, 3vw, 2.55rem);
            line-height: 1.08;
            letter-spacing: -.025em;
        }}

        .hero p {{
            max-width: 850px;
            margin: .65rem 0 0;
            color: var(--sage);
            opacity: .92;
            font-size: 1rem;
        }}

        [data-testid="stMetric"] {{
            padding: 1rem 1.05rem;
            border: 1px solid rgba(107,112,92,.42);
            border-radius: 14px;
            background: rgba(167,184,141,.12);
            box-shadow: 0 7px 20px rgba(48,77,61,.07);
        }}

        [data-testid="stMetricLabel"] {{
            color: var(--moss);
            font-weight: 650;
        }}

        [data-testid="stMetricValue"] {{
            color: var(--pine);
            font-weight: 750;
        }}

        .insight-strip {{
            display: flex;
            gap: .8rem;
            align-items: flex-start;
            margin: .85rem 0 1.1rem;
            padding: .85rem 1rem;
            border-left: 5px solid var(--forest);
            border-radius: 0 12px 12px 0;
            color: var(--pine);
            background: rgba(167,184,141,.16);
        }}

        .insight-strip strong {{ color: var(--forest); }}

        .section-heading {{
            margin: .1rem 0 .05rem;
            color: var(--pine);
            font-size: 1.18rem;
            font-weight: 750;
            letter-spacing: -.01em;
        }}

        .section-copy {{
            margin: 0 0 .4rem;
            color: var(--moss);
            font-size: .9rem;
        }}

        .method-note {{
            margin: .35rem 0 1rem;
            padding: .7rem .85rem;
            border: 1px solid rgba(107,112,92,.30);
            border-radius: 10px;
            color: var(--moss);
            background: rgba(167,184,141,.08);
            font-size: .86rem;
        }}

        [data-baseweb="tab-list"] {{
            gap: .5rem;
            border-bottom: 1px solid rgba(107,112,92,.30);
        }}

        [data-baseweb="tab"] {{
            color: var(--moss);
            border-radius: 10px 10px 0 0;
            padding-left: 1rem;
            padding-right: 1rem;
        }}

        [aria-selected="true"][data-baseweb="tab"] {{
            color: var(--pine);
            background: rgba(167,184,141,.16);
        }}

        [data-testid="stExpander"] {{
            border-color: rgba(107,112,92,.32);
            background: rgba(167,184,141,.06);
        }}

        div[data-testid="stDataFrame"] {{
            border: 1px solid rgba(107,112,92,.28);
            border-radius: 12px;
            overflow: hidden;
        }}

        @media (max-width: 760px) {{
            .block-container {{ padding-left: .85rem; padding-right: .85rem; }}
            .hero {{ padding: 1.1rem; border-radius: 14px; }}
            .insight-strip {{ display: block; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Data loading and preparation
# -----------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def read_uploaded_csv(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw), low_memory=False)


@st.cache_data(show_spinner=False)
def read_local_csv(path: str, modified_ns: int) -> pd.DataFrame:
    del modified_ns  # Included only to invalidate the cache after a file change.
    return pd.read_csv(path, low_memory=False)


def clean_category(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    cleaned = cleaned.replace(
        {
            "": pd.NA,
            "nan": pd.NA,
            "NaN": pd.NA,
            "None": pd.NA,
            "none": pd.NA,
            "<NA>": pd.NA,
        }
    )
    return cleaned.fillna("Missing")


def parse_churn_flag(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip().str.lower()
    mapped = text.map(
        {
            "1": 1.0,
            "1.0": 1.0,
            "true": 1.0,
            "yes": 1.0,
            "y": 1.0,
            "churned": 1.0,
            "0": 0.0,
            "0.0": 0.0,
            "false": 0.0,
            "no": 0.0,
            "n": 0.0,
            "stayed": 0.0,
            "joined": 0.0,
        }
    )
    return mapped


def binary_indicator(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() >= 0.8:
        return (numeric > 0).astype(float)

    text = series.astype("string").str.strip().str.lower()
    return text.map(
        {
            "yes": 1.0,
            "true": 1.0,
            "1": 1.0,
            "1.0": 1.0,
            "no": 0.0,
            "false": 0.0,
            "0": 0.0,
            "0.0": 0.0,
        }
    )


def prepare_data(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [str(column).strip().lower() for column in df.columns]

    for column in NUMERIC_COLUMNS:
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")

    for column in CATEGORICAL_COLUMNS:
        if column not in df.columns:
            df[column] = "Missing"
        df[column] = clean_category(df[column])

    if "customer_id" not in df.columns:
        df["customer_id"] = [f"Customer {index + 1:,}" for index in range(len(df))]
    df["customer_id"] = clean_category(df["customer_id"])

    if "churn_value" in df.columns:
        explicit_flag = parse_churn_flag(df["churn_value"])
    else:
        explicit_flag = pd.Series(np.nan, index=df.index, dtype=float)

    status_flag = (
        df["customer_status"]
        .astype("string")
        .str.strip()
        .str.lower()
        .eq("churned")
        .astype(float)
    )
    df["churn_flag"] = explicit_flag.fillna(status_flag).fillna(0).astype(int)
    df["churn_label"] = np.where(df["churn_flag"].eq(1), "Churned", "Retained")

    # Friendly, ordered categories used throughout the dashboard.
    df["risk_band"] = (
        pd.cut(
            df["churn_score"],
            bins=[-np.inf, 30, 70, np.inf],
            labels=["Low risk", "Medium risk", "High risk"],
            right=False,
        )
        .astype("string")
        .fillna("Unknown risk")
    )

    df["satisfaction_band"] = (
        pd.cut(
            df["satisfaction_score"],
            bins=[-np.inf, 2.5, 3.5, 4.5, np.inf],
            labels=["Low · 1–2", "Neutral · 3", "Good · 4", "Excellent · 5"],
            right=False,
        )
        .astype("string")
        .fillna("Unknown")
    )

    df["tenure_band"] = (
        pd.cut(
            df["tenure_months"],
            bins=[-np.inf, 6, 12, 24, 48, np.inf],
            labels=[
                "0–5 months",
                "6–11 months",
                "12–23 months",
                "24–47 months",
                "48+ months",
            ],
            right=False,
        )
        .astype("string")
        .fillna("Unknown")
    )

    return df.replace([np.inf, -np.inf], np.nan)


def load_data() -> tuple[pd.DataFrame | None, str]:
    st.sidebar.markdown("## Data & filters")
    uploaded = st.sidebar.file_uploader(
        "Upload telecom CSV",
        type=["csv"],
        help="If no file is uploaded, the app looks for master_view_v1.csv beside this Python file.",
    )

    default_path = Path(__file__).resolve().with_name("master_view_v1.csv")
    try:
        if uploaded is not None:
            return prepare_data(read_uploaded_csv(uploaded.getvalue())), uploaded.name
        if default_path.exists():
            stat = default_path.stat()
            return prepare_data(
                read_local_csv(str(default_path), stat.st_mtime_ns)
            ), default_path.name
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, ValueError) as exc:
        st.error(f"The CSV could not be read: {exc}")
        return None, "Unavailable"

    return None, "No data loaded"


# -----------------------------------------------------------------------------
# Filtering and formatting helpers
# -----------------------------------------------------------------------------


def ordered_values(series: pd.Series, preferred: Sequence[str] = ()) -> list[str]:
    values = [str(value) for value in series.dropna().unique()]
    preferred_values = [value for value in preferred if value in values]
    remainder = sorted(value for value in values if value not in preferred_values)
    return preferred_values + remainder


def clear_filters() -> None:
    for key in FILTER_STATE_KEYS:
        st.session_state.pop(key, None)


def int_range_filter(series: pd.Series, label: str, key: str) -> tuple[float, float]:
    usable = series.dropna()
    if usable.empty:
        return -np.inf, np.inf
    minimum = math.floor(usable.min())
    maximum = math.ceil(usable.max())
    if minimum == maximum:
        st.sidebar.caption(f"{label}: {minimum:,}")
        return minimum, maximum
    selected = st.sidebar.slider(label, minimum, maximum, (minimum, maximum), key=key)
    return float(selected[0]), float(selected[1])


def float_range_filter(series: pd.Series, label: str, key: str) -> tuple[float, float]:
    usable = series.dropna()
    if usable.empty:
        return -np.inf, np.inf
    minimum = float(math.floor(usable.min()))
    maximum = float(math.ceil(usable.max()))
    if math.isclose(minimum, maximum):
        st.sidebar.caption(f"{label}: {minimum:,.1f}")
        return minimum, maximum
    selected = st.sidebar.slider(
        label,
        min_value=minimum,
        max_value=maximum,
        value=(minimum, maximum),
        step=1.0,
        key=key,
    )
    return float(selected[0]), float(selected[1])


def build_filters(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    st.sidebar.caption(f"Source · {source_name} · {len(df):,} rows")
    if st.sidebar.button("Reset all filters", use_container_width=True):
        clear_filters()
        st.rerun()

    st.sidebar.markdown("### Audience")
    status_options = ordered_values(
        df["customer_status"], ["Churned", "Stayed", "Joined"]
    )
    contract_options = ordered_values(
        df["contract"], ["Month-to-Month", "One Year", "Two Year", "Missing"]
    )
    internet_options = ordered_values(
        df["internet_type"], ["Fiber Optic", "Cable", "DSL", "Missing"]
    )

    selected_status = st.sidebar.multiselect(
        "Customer status", status_options, default=status_options, key="flt_status"
    )
    selected_contract = st.sidebar.multiselect(
        "Contract", contract_options, default=contract_options, key="flt_contract"
    )
    selected_internet = st.sidebar.multiselect(
        "Internet type", internet_options, default=internet_options, key="flt_internet"
    )

    st.sidebar.markdown("### Numerical ranges")
    age_range = int_range_filter(df["age"], "Age", "flt_age")
    tenure_range = int_range_filter(
        df["tenure_months"], "Tenure · months", "flt_tenure"
    )
    satisfaction_range = int_range_filter(
        df["satisfaction_score"], "Satisfaction score", "flt_satisfaction"
    )
    risk_range = int_range_filter(df["churn_score"], "Churn risk score", "flt_risk")
    charge_range = float_range_filter(
        df["monthly_charges"], "Monthly charges", "flt_charges"
    )

    with st.sidebar.expander("More segmentation", expanded=False):
        gender_options = ordered_values(df["gender"])
        payment_options = ordered_values(df["payment_method"])
        offer_options = ordered_values(df["offer"])
        city_options = list(df["city"].value_counts().head(50).index.astype(str))

        selected_gender = st.multiselect(
            "Gender", gender_options, default=gender_options, key="flt_gender"
        )
        selected_payment = st.multiselect(
            "Payment method",
            payment_options,
            default=payment_options,
            key="flt_payment",
        )
        selected_offer = st.multiselect(
            "Offer", offer_options, default=offer_options, key="flt_offer"
        )
        selected_cities = st.multiselect(
            "Cities · optional",
            city_options,
            default=[],
            key="flt_city",
            help="The 50 largest cities in the current data are offered to keep this filter usable.",
        )

    mask = (
        df["customer_status"].isin(selected_status)
        & df["contract"].isin(selected_contract)
        & df["internet_type"].isin(selected_internet)
        & df["gender"].isin(selected_gender)
        & df["payment_method"].isin(selected_payment)
        & df["offer"].isin(selected_offer)
    )

    numerical_filters = [
        ("age", age_range),
        ("tenure_months", tenure_range),
        ("satisfaction_score", satisfaction_range),
        ("churn_score", risk_range),
        ("monthly_charges", charge_range),
    ]
    for column, (lower, upper) in numerical_filters:
        # Missing values remain visible when the slider is at its full range.
        usable = df[column].dropna()
        full_range = usable.empty or (
            lower <= float(usable.min()) and upper >= float(usable.max())
        )
        column_mask = df[column].between(lower, upper, inclusive="both")
        if full_range:
            column_mask = column_mask | df[column].isna()
        mask &= column_mask

    if selected_cities:
        mask &= df["city"].isin(selected_cities)

    filtered = df.loc[mask].copy()
    share = len(filtered) / len(df) if len(df) else 0
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**{len(filtered):,} customers** · {share:.1%} of data")
    if not filtered.empty:
        csv_bytes = filtered.to_csv(index=False).encode("utf-8")
        st.sidebar.download_button(
            "Download filtered rows",
            data=csv_bytes,
            file_name="telecom_customers_filtered.csv",
            mime="text/csv",
            use_container_width=True,
        )
    return filtered


def format_money(value: float) -> str:
    if pd.isna(value):
        return "—"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.2f}"


def humanize(column: str) -> str:
    replacements = {
        "cltv": "Customer lifetime value",
        "avg_monthly_gb_download": "Average monthly download (GB)",
        "churn_score": "Churn risk score",
        "satisfaction_score": "Satisfaction score",
        "total_long_distance_charges": "Total long-distance charges",
    }
    return replacements.get(column, column.replace("_", " ").title())


def sample_rows(df: pd.DataFrame, maximum: int = 4500) -> pd.DataFrame:
    if len(df) <= maximum:
        return df.copy()
    return df.sample(maximum, random_state=42)


def scaled_sizes(series: pd.Series, low: float = 7, high: float = 24) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce")
    if values.notna().sum() == 0:
        return np.full(len(series), (low + high) / 2)
    values = values.fillna(values.median())
    minimum, maximum = float(values.min()), float(values.max())
    if math.isclose(minimum, maximum):
        return np.full(len(series), (low + high) / 2)
    normalized = (values - minimum) / (maximum - minimum)
    return low + np.sqrt(normalized.clip(0, 1)) * (high - low)


def hex_rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha})"


def apply_chart_theme(
    fig: go.Figure,
    *,
    height: int = 500,
    show_legend: bool = True,
    margin: dict[str, int] | None = None,
) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=margin or {"l": 52, "r": 26, "t": 28, "b": 48},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, Segoe UI, sans-serif", "color": DARK, "size": 12},
        colorway=PALETTE,
        hoverlabel={
            "bgcolor": DARK,
            "bordercolor": MOSS,
            "font": {"color": SAGE, "family": "Inter, Segoe UI, sans-serif"},
        },
        hovermode="closest",
        showlegend=show_legend,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "left",
            "x": 0,
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"color": DARK},
        },
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor=hex_rgba(SAGE, 0.34),
        zeroline=False,
        linecolor=hex_rgba(MOSS, 0.48),
        tickfont={"color": MOSS},
        title_font={"color": DARK},
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=hex_rgba(SAGE, 0.34),
        zeroline=False,
        linecolor=hex_rgba(MOSS, 0.48),
        tickfont={"color": MOSS},
        title_font={"color": DARK},
    )
    return fig


def render_chart(fig: go.Figure, key: str) -> None:
    st.plotly_chart(
        fig,
        use_container_width=True,
        config=PLOTLY_CONFIG,
        key=key,
    )


def section_heading(title: str, copy: str) -> None:
    st.markdown(
        f'<div class="section-heading">{html.escape(title)}</div>'
        f'<div class="section-copy">{html.escape(copy)}</div>',
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Visualisations
# -----------------------------------------------------------------------------


def streaming_adoption(df: pd.DataFrame) -> go.Figure:
    """Compare adoption of the two streaming products."""

    service_columns = [
        ("Streaming movies", "streaming_movies"),
        ("Streaming TV", "streaming_tv"),
    ]
    summary_rows: list[dict[str, object]] = []
    for service_label, column in service_columns:
        if column not in df.columns:
            continue
        indicator = binary_indicator(df[column])
        valid = indicator.dropna()
        denominator = len(valid)
        if denominator == 0:
            continue
        for value, answer in [(0.0, "No"), (1.0, "Yes")]:
            count = int(valid.eq(value).sum())
            summary_rows.append(
                {
                    "service": service_label,
                    "answer": answer,
                    "customers": count,
                    "share": count / denominator,
                }
            )

    summary = pd.DataFrame(summary_rows)
    fig = go.Figure()
    answer_colors = {"No": MOSS, "Yes": SAGE}
    for answer in ["No", "Yes"]:
        part = summary.loc[summary["answer"].eq(answer)]
        if part.empty:
            continue
        fig.add_trace(
            go.Bar(
                x=part["service"],
                y=part["share"],
                name=answer,
                marker={
                    "color": answer_colors[answer],
                    "line": {"color": FOREST, "width": 0.8},
                },
                text=[f"{value:.1%}" for value in part["share"]],
                textposition="outside",
                customdata=part[["customers", "share"]].to_numpy(),
                hovertemplate=(
                    f"<b>{answer}</b><br>"
                    "Service: %{x}<br>"
                    "Customers: %{customdata[0]:,}<br>"
                    "Share: %{customdata[1]:.1%}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(barmode="group", bargap=0.30, bargroupgap=0.08)
    fig.update_xaxes(title="Streaming service")
    fig.update_yaxes(title="Share of customers", tickformat=".0%", range=[0, 1.08])
    return apply_chart_theme(
        fig, height=430, margin={"l": 58, "r": 18, "t": 28, "b": 58}
    )


def referral_marital_donut(df: pd.DataFrame) -> go.Figure:
    """Show how recorded referrals divide between married and unmarried customers."""

    married = (
        binary_indicator(df["married"])
        if "married" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    referrals = pd.to_numeric(df["number_of_referrals"], errors="coerce").fillna(0)
    working = pd.DataFrame({"married": married, "referrals": referrals}).dropna(
        subset=["married"]
    )
    working["status"] = np.where(working["married"].eq(1), "Married", "Not married")
    summary = (
        working.groupby("status", observed=True)
        .agg(
            total_referrals=("referrals", "sum"),
            customers=("referrals", "size"),
            avg_referrals=("referrals", "mean"),
        )
        .reindex(["Married", "Not married"])
        .dropna(subset=["customers"])
        .reset_index()
    )

    fig = go.Figure(
        go.Pie(
            labels=summary["status"],
            values=summary["total_referrals"],
            hole=0.62,
            sort=False,
            direction="clockwise",
            marker={
                "colors": [FOREST, SAGE][: len(summary)],
                "line": {"color": MOSS, "width": 1},
            },
            textinfo="label+percent",
            textposition="outside",
            customdata=summary[["customers", "avg_referrals"]].to_numpy(),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Total referrals: %{value:,.0f}<br>"
                "Share of referrals: %{percent}<br>"
                "Customers: %{customdata[0]:,}<br>"
                "Average referrals: %{customdata[1]:.2f}"
                "<extra></extra>"
            ),
        )
    )
    total_referrals = float(summary["total_referrals"].sum())
    fig.add_annotation(
        x=0.5,
        y=0.5,
        text=f"<b>{total_referrals:,.0f}</b><br>referrals",
        showarrow=False,
        font={"color": DARK, "size": 14},
    )
    return apply_chart_theme(
        fig,
        height=430,
        margin={"l": 24, "r": 24, "t": 28, "b": 34},
    )


def churn_outcome_donut(df: pd.DataFrame) -> go.Figure:
    """Show the overall retained-versus-churned composition."""

    counts = (
        df["churn_label"]
        .value_counts()
        .reindex(["Retained", "Churned"])
        .fillna(0)
        .astype(int)
    )
    labels = [label for label in counts.index if counts[label] > 0]
    values = [int(counts[label]) for label in labels]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.58,
            sort=False,
            marker={
                "colors": [STATUS_COLORS[label] for label in labels],
                "line": {"color": MOSS, "width": 1},
            },
            textinfo="label+percent",
            textposition="outside",
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Customers: %{value:,}<br>"
                "Share: %{percent}"
                "<extra></extra>"
            ),
        )
    )
    fig.add_annotation(
        x=0.5,
        y=0.5,
        text=f"<b>{len(df):,}</b><br>customers",
        showarrow=False,
        font={"color": DARK, "size": 14},
    )
    return apply_chart_theme(
        fig,
        height=430,
        margin={"l": 24, "r": 24, "t": 28, "b": 34},
    )


def churned_customers_by_contract(df: pd.DataFrame) -> go.Figure:
    """Count churned customers within each contract type."""

    base = (
        df.groupby("contract", observed=True)
        .agg(base_customers=("customer_id", "size"), churn_rate=("churn_flag", "mean"))
        .reset_index()
    )
    churned = (
        df.loc[df["churn_flag"].eq(1)]
        .groupby("contract", observed=True)
        .size()
        .rename("churned_customers")
        .reset_index()
    )
    summary = base.merge(churned, on="contract", how="left")
    summary["churned_customers"] = summary["churned_customers"].fillna(0).astype(int)
    total_churned = max(1, int(summary["churned_customers"].sum()))
    summary["share_of_churn"] = summary["churned_customers"] / total_churned
    summary = summary.sort_values("churned_customers", ascending=True)
    contract_colors = {
        "Month-to-Month": DARK,
        "One Year": MOSS,
        "Two Year": SAGE,
        "Missing": FOREST,
    }

    fig = go.Figure(
        go.Bar(
            x=summary["churned_customers"],
            y=summary["contract"],
            orientation="h",
            marker={
                "color": [
                    contract_colors.get(value, FOREST) for value in summary["contract"]
                ],
                "line": {"color": FOREST, "width": 0.7},
            },
            text=[f"{value:,}" for value in summary["churned_customers"]],
            textposition="outside",
            customdata=summary[
                ["base_customers", "churn_rate", "share_of_churn"]
            ].to_numpy(),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Churned customers: %{x:,}<br>"
                "Customers on contract: %{customdata[0]:,}<br>"
                "Within-contract churn rate: %{customdata[1]:.1%}<br>"
                "Share of all churn: %{customdata[2]:.1%}"
                "<extra></extra>"
            ),
            showlegend=False,
        )
    )
    maximum = max(1, int(summary["churned_customers"].max()))
    fig.update_xaxes(title="Churned customers", range=[0, maximum * 1.20])
    fig.update_yaxes(title="")
    return apply_chart_theme(fig, height=430, show_legend=False)


def average_monthly_charge_by_internet(df: pd.DataFrame) -> go.Figure:
    """Compare average monthly charges across internet products."""

    usable = df.loc[df["internet_type"].ne("Missing") & df["monthly_charges"].notna()]
    if usable.empty:
        usable = df.loc[df["monthly_charges"].notna()]
    summary = (
        usable.groupby("internet_type", observed=True)
        .agg(
            avg_monthly_charge=("monthly_charges", "mean"),
            customers=("customer_id", "size"),
            median_monthly_charge=("monthly_charges", "median"),
        )
        .reset_index()
        .sort_values("avg_monthly_charge", ascending=True)
    )
    colors = [PALETTE[index % len(PALETTE)] for index in range(len(summary))]
    fig = go.Figure(
        go.Bar(
            x=summary["avg_monthly_charge"],
            y=summary["internet_type"],
            orientation="h",
            marker={
                "color": colors,
                "line": {"color": FOREST, "width": 0.7},
            },
            text=[f"${value:,.0f}" for value in summary["avg_monthly_charge"]],
            textposition="outside",
            customdata=summary[["customers", "median_monthly_charge"]].to_numpy(),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Average monthly charge: $%{x:,.2f}<br>"
                "Median monthly charge: $%{customdata[1]:,.2f}<br>"
                "Customers: %{customdata[0]:,}"
                "<extra></extra>"
            ),
            showlegend=False,
        )
    )
    maximum = max(1.0, float(summary["avg_monthly_charge"].max()))
    fig.update_xaxes(
        title="Average monthly charge", tickprefix="$", range=[0, maximum * 1.20]
    )
    fig.update_yaxes(title="")
    return apply_chart_theme(fig, height=430, show_legend=False)


def revenue_long_distance_scatter(df: pd.DataFrame) -> go.Figure:
    """Relate long-distance charges to total customer revenue."""

    plot = df.dropna(subset=["total_long_distance_charges", "total_revenue"]).copy()
    plot = sample_rows(plot, 5500)
    fig = go.Figure()
    for label in ["Retained", "Churned"]:
        part = plot.loc[plot["churn_label"].eq(label)]
        if part.empty:
            continue
        custom = part[
            [
                "customer_id",
                "contract",
                "internet_type",
                "tenure_months",
                "monthly_charges",
            ]
        ].to_numpy()
        fig.add_trace(
            go.Scattergl(
                x=part["total_long_distance_charges"],
                y=part["total_revenue"],
                mode="markers",
                name=label,
                marker={
                    "size": 7,
                    "color": STATUS_COLORS[label],
                    "symbol": STATUS_SYMBOLS[label],
                    "opacity": 0.56 if label == "Retained" else 0.72,
                    "line": {"color": MOSS, "width": 0.35},
                },
                customdata=custom,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    + f"Outcome: {label}<br>"
                    + "Long-distance charges: $%{x:,.2f}<br>"
                    + "Total revenue: $%{y:,.2f}<br>"
                    + "Contract: %{customdata[1]}<br>"
                    + "Internet: %{customdata[2]}<br>"
                    + "Tenure: %{customdata[3]:,.0f} months<br>"
                    + "Monthly charge: $%{customdata[4]:,.2f}"
                    + "<extra></extra>"
                ),
            )
        )
    fig.update_xaxes(
        title="Total long-distance charges", tickprefix="$", tickformat="~s"
    )
    fig.update_yaxes(title="Total revenue", tickprefix="$", tickformat="~s")
    return apply_chart_theme(
        fig, height=560, margin={"l": 72, "r": 24, "t": 32, "b": 62}
    )


def top_feature_pairplot(df: pd.DataFrame) -> go.Figure:
    """Build an interactive pairplot with histograms on the diagonal."""

    feature_specs = [
        ("tenure_months", "Tenure"),
        ("total_revenue", "Total revenue"),
        ("total_long_distance_charges", "Long-distance charges"),
        ("monthly_charges", "Monthly charge"),
        ("churn_score", "Churn risk score"),
    ]
    features = [
        (column, label)
        for column, label in feature_specs
        if column in df.columns and df[column].notna().sum() >= 3
    ]
    if len(features) < 2:
        fig = go.Figure()
        fig.add_annotation(
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            text="At least two numeric features are required for the pairplot.",
            showarrow=False,
            font={"color": MOSS, "size": 14},
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        return apply_chart_theme(fig, height=360, show_legend=False)

    feature_columns = [column for column, _ in features]
    plot = df.dropna(subset=feature_columns).copy()
    plot = sample_rows(plot, 700)
    size = len(features)
    fig = make_subplots(
        rows=size,
        cols=size,
        horizontal_spacing=0.022,
        vertical_spacing=0.022,
    )

    for row_index, (y_column, y_label) in enumerate(features, start=1):
        for col_index, (x_column, x_label) in enumerate(features, start=1):
            if row_index == col_index:
                for outcome in ["Retained", "Churned"]:
                    part = plot.loc[plot["churn_label"].eq(outcome)]
                    if part.empty:
                        continue
                    fig.add_trace(
                        go.Histogram(
                            x=part[x_column],
                            nbinsx=22,
                            name=outcome,
                            legendgroup=outcome,
                            marker={"color": STATUS_COLORS[outcome]},
                            opacity=0.55,
                            showlegend=row_index == 1,
                            hovertemplate=(
                                f"<b>{outcome}</b><br>"
                                f"{html.escape(x_label)}: %{{x:,.2f}}<br>"
                                "Customers in bin: %{y:,}"
                                "<extra></extra>"
                            ),
                        ),
                        row=row_index,
                        col=col_index,
                    )
            else:
                for outcome in ["Retained", "Churned"]:
                    part = plot.loc[plot["churn_label"].eq(outcome)]
                    if part.empty:
                        continue
                    fig.add_trace(
                        go.Scattergl(
                            x=part[x_column],
                            y=part[y_column],
                            mode="markers",
                            name=outcome,
                            legendgroup=outcome,
                            marker={
                                "size": 4.5,
                                "color": STATUS_COLORS[outcome],
                                "symbol": STATUS_SYMBOLS[outcome],
                                "opacity": 0.42 if outcome == "Retained" else 0.58,
                            },
                            customdata=part[["customer_id"]].to_numpy(),
                            showlegend=False,
                            hovertemplate=(
                                "<b>%{customdata[0]}</b><br>"
                                + f"Outcome: {outcome}<br>"
                                + f"{html.escape(x_label)}: %{{x:,.2f}}<br>"
                                + f"{html.escape(y_label)}: %{{y:,.2f}}"
                                + "<extra></extra>"
                            ),
                        ),
                        row=row_index,
                        col=col_index,
                    )

            show_x_labels = row_index == size
            show_y_labels = col_index == 1
            fig.update_xaxes(
                title_text=x_label if show_x_labels else "",
                showticklabels=show_x_labels,
                tickfont={"size": 8, "color": MOSS},
                title_font={"size": 10, "color": DARK},
                row=row_index,
                col=col_index,
            )
            fig.update_yaxes(
                title_text=("Count" if row_index == col_index else y_label)
                if show_y_labels
                else "",
                showticklabels=show_y_labels,
                tickfont={"size": 8, "color": MOSS},
                title_font={"size": 10, "color": DARK},
                row=row_index,
                col=col_index,
            )

    fig.update_layout(barmode="overlay")
    return apply_chart_theme(
        fig,
        height=1030,
        margin={"l": 88, "r": 24, "t": 42, "b": 88},
    )


def important_feature_heatmap(df: pd.DataFrame) -> go.Figure:
    """Display Pearson correlations for the important features in the reference."""

    numeric_specs = [
        ("tenure_months", "Tenure"),
        ("number_of_referrals", "Referrals"),
        ("number_of_dependents", "Dependents"),
        ("age", "Age"),
        ("avg_monthly_gb_download", "Monthly download"),
        ("total_extra_data_charges", "Extra-data charges"),
        ("churn_score", "Churn risk score"),
    ]
    binary_specs = [
        ("married", "Married"),
        ("phone_service", "Phone service"),
    ]
    frame = pd.DataFrame(index=df.index)
    for column, label in numeric_specs:
        if column in df.columns:
            values = pd.to_numeric(df[column], errors="coerce")
            if values.nunique(dropna=True) > 1:
                frame[label] = values
    for column, label in binary_specs:
        if column in df.columns:
            values = binary_indicator(df[column])
            if values.nunique(dropna=True) > 1:
                frame[label] = values

    if frame.shape[1] < 2:
        fig = go.Figure()
        fig.add_annotation(
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            text="At least two varying features are required for the heatmap.",
            showarrow=False,
            font={"color": MOSS, "size": 14},
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        return apply_chart_theme(fig, height=360, show_legend=False)

    minimum_periods = min(len(frame), max(3, min(30, len(frame) // 10)))
    correlation = frame.corr(method="pearson", min_periods=minimum_periods)
    labels = list(correlation.columns)
    fig = go.Figure(
        go.Heatmap(
            z=correlation.to_numpy(),
            x=labels,
            y=labels,
            zmin=-1,
            zmax=1,
            zmid=0,
            colorscale=[
                [0.0, DARK],
                [0.40, FOREST],
                [0.50, MOSS],
                [0.72, SAGE],
                [1.0, SAGE],
            ],
            xgap=1.2,
            ygap=1.2,
            colorbar={
                "title": "Pearson r",
                "tickvals": [-1, -0.5, 0, 0.5, 1],
                "thickness": 15,
                "outlinewidth": 0,
            },
            hovertemplate=(
                "<b>%{y}</b> × <b>%{x}</b><br>"
                "Pearson correlation: %{z:+.3f}"
                "<extra></extra>"
            ),
        )
    )
    for y_index, y_label in enumerate(labels):
        for x_index, x_label in enumerate(labels):
            value = correlation.iloc[y_index, x_index]
            if pd.isna(value):
                continue
            fig.add_annotation(
                x=x_label,
                y=y_label,
                text=f"{value:.2f}",
                showarrow=False,
                font={
                    "color": DARK if value >= 0.55 else SAGE,
                    "size": 10,
                },
            )
    fig.update_xaxes(title="", tickangle=-35, tickfont={"size": 10})
    fig.update_yaxes(title="", autorange="reversed", tickfont={"size": 10})
    return apply_chart_theme(
        fig,
        height=720,
        show_legend=False,
        margin={"l": 132, "r": 38, "t": 40, "b": 128},
    )


def risk_landscape(df: pd.DataFrame) -> go.Figure:
    plot = df.dropna(subset=["churn_score", "satisfaction_score"]).copy()
    plot = sample_rows(plot)

    hashes = pd.util.hash_pandas_object(plot["customer_id"], index=False).astype(
        "uint64"
    )
    jitter = ((hashes % 1000).astype(float) / 1000 - 0.5) * 0.18
    plot["_satisfaction_jitter"] = plot["satisfaction_score"] + jitter
    plot["_marker_size"] = scaled_sizes(plot["monthly_charges"])

    fig = go.Figure()
    ymin = max(0.5, float(plot["satisfaction_score"].min()) - 0.5)
    ymax = min(5.5, float(plot["satisfaction_score"].max()) + 0.5)

    fig.add_shape(
        type="rect",
        x0=70,
        x1=100,
        y0=ymin,
        y1=3.5,
        fillcolor=hex_rgba(DARK, 0.08),
        line={"width": 0},
        layer="below",
    )
    fig.add_shape(
        type="rect",
        x0=0,
        x1=30,
        y0=3.5,
        y1=ymax,
        fillcolor=hex_rgba(SAGE, 0.16),
        line={"width": 0},
        layer="below",
    )

    for label in ["Retained", "Churned"]:
        part = plot.loc[plot["churn_label"].eq(label)]
        if part.empty:
            continue
        custom = part[
            [
                "customer_id",
                "contract",
                "internet_type",
                "monthly_charges",
                "tenure_months",
                "satisfaction_score",
            ]
        ].to_numpy()
        fig.add_trace(
            go.Scattergl(
                x=part["churn_score"],
                y=part["_satisfaction_jitter"],
                mode="markers",
                name=label,
                marker={
                    "size": part["_marker_size"],
                    "color": STATUS_COLORS[label],
                    "symbol": STATUS_SYMBOLS[label],
                    "opacity": 0.68 if label == "Retained" else 0.78,
                    "line": {"color": MOSS, "width": 0.6},
                },
                customdata=custom,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    + f"Outcome: {label}<br>"
                    + "Risk score: %{x:.0f}/100<br>"
                    + "Satisfaction: %{customdata[5]:.0f}/5<br>"
                    + "Contract: %{customdata[1]}<br>"
                    + "Internet: %{customdata[2]}<br>"
                    + "Monthly charge: $%{customdata[3]:,.2f}<br>"
                    + "Tenure: %{customdata[4]:,.0f} months"
                    + "<extra></extra>"
                ),
            )
        )

    fig.add_vline(x=70, line_width=1.2, line_dash="dot", line_color=MOSS)
    fig.add_hline(y=3.5, line_width=1.2, line_dash="dot", line_color=MOSS)
    fig.add_annotation(
        x=85,
        y=max(ymin + 0.12, 1.0),
        text="High risk · low satisfaction",
        showarrow=False,
        font={"color": DARK, "size": 11},
        bgcolor=hex_rgba(SAGE, 0.76),
        bordercolor=MOSS,
        borderpad=4,
    )
    fig.update_xaxes(title="Churn risk score · 0–100", range=[0, 100])
    fig.update_yaxes(
        title="Satisfaction score · jittered for visibility",
        range=[ymin, ymax],
        tickmode="linear",
        dtick=1,
    )
    return apply_chart_theme(fig, height=535)


def segment_treemap(df: pd.DataFrame) -> go.Figure:
    segment = (
        df.groupby(["contract", "internet_type"], dropna=False, observed=True)
        .agg(
            customers=("customer_id", "size"),
            churn_rate=("churn_flag", "mean"),
            avg_monthly_charge=("monthly_charges", "mean"),
            total_revenue=("total_revenue", "sum"),
            avg_satisfaction=("satisfaction_score", "mean"),
        )
        .reset_index()
    )

    # Plotly Express is intentionally avoided so the app remains fully controlled
    # from one file; this helper builds a hierarchy compatible with go.Treemap.
    labels = ["Filtered customers"]
    ids = ["root"]
    parents = [""]
    values = [int(segment["customers"].sum())]
    churn_rates = [float(df["churn_flag"].mean())]
    monthly = [float(df["monthly_charges"].mean())]
    revenue = [float(df["total_revenue"].sum())]
    satisfaction = [float(df["satisfaction_score"].mean())]

    for contract, contract_rows in segment.groupby("contract", observed=True):
        contract_id = f"contract::{contract}"
        labels.append(str(contract))
        ids.append(contract_id)
        parents.append("root")
        values.append(int(contract_rows["customers"].sum()))
        weighted_rate = np.average(
            contract_rows["churn_rate"], weights=contract_rows["customers"]
        )
        churn_rates.append(float(weighted_rate))
        weighted_monthly = np.average(
            contract_rows["avg_monthly_charge"].fillna(0),
            weights=contract_rows["customers"],
        )
        monthly.append(float(weighted_monthly))
        revenue.append(float(contract_rows["total_revenue"].sum()))
        weighted_sat = np.average(
            contract_rows["avg_satisfaction"].fillna(0),
            weights=contract_rows["customers"],
        )
        satisfaction.append(float(weighted_sat))

        for row in contract_rows.itertuples(index=False):
            labels.append(str(row.internet_type))
            ids.append(f"{contract_id}::internet::{row.internet_type}")
            parents.append(contract_id)
            values.append(int(row.customers))
            churn_rates.append(float(row.churn_rate))
            monthly.append(float(row.avg_monthly_charge))
            revenue.append(float(row.total_revenue))
            satisfaction.append(float(row.avg_satisfaction))

    custom = np.column_stack([churn_rates, monthly, revenue, satisfaction])
    fig = go.Figure(
        go.Treemap(
            labels=labels,
            ids=ids,
            parents=parents,
            values=values,
            branchvalues="total",
            marker={
                "colors": churn_rates,
                "colorscale": [[0.0, SAGE], [0.40, MOSS], [0.72, FOREST], [1.0, DARK]],
                "cmin": 0,
                "cmax": max(0.01, float(np.nanmax(churn_rates))),
                "colorbar": {
                    "title": "Churn rate",
                    "tickformat": ".0%",
                    "thickness": 14,
                    "outlinewidth": 0,
                },
                "line": {"color": hex_rgba(SAGE, 0.7), "width": 1.2},
            },
            customdata=custom,
            texttemplate="<b>%{label}</b><br>%{value:,} customers",
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Customers: %{value:,}<br>"
                "Churn rate: %{customdata[0]:.1%}<br>"
                "Avg monthly charge: $%{customdata[1]:,.2f}<br>"
                "Total revenue: $%{customdata[2]:,.0f}<br>"
                "Avg satisfaction: %{customdata[3]:.2f}/5"
                "<extra></extra>"
            ),
            pathbar={"visible": True, "textfont": {"color": DARK}},
            root={"color": hex_rgba(SAGE, 0.34)},
        )
    )
    return apply_chart_theme(
        fig,
        height=535,
        show_legend=False,
        margin={"l": 8, "r": 8, "t": 25, "b": 8},
    )


def retention_sankey(df: pd.DataFrame) -> go.Figure:
    contracts = ordered_values(
        df["contract"], ["Month-to-Month", "One Year", "Two Year"]
    )
    internet_types = ordered_values(
        df["internet_type"], ["Fiber Optic", "Cable", "DSL"]
    )
    outcomes = [
        value
        for value in ["Retained", "Churned"]
        if value in df["churn_label"].unique()
    ]

    node_keys = (
        [("Contract", value) for value in contracts]
        + [("Internet", value) for value in internet_types]
        + [("Outcome", value) for value in outcomes]
    )
    node_index = {key: index for index, key in enumerate(node_keys)}
    labels = [value for _, value in node_keys]
    node_colors = (
        [MOSS] * len(contracts)
        + [FOREST] * len(internet_types)
        + [STATUS_COLORS[value] for value in outcomes]
    )

    source: list[int] = []
    target: list[int] = []
    values: list[int] = []
    link_colors: list[str] = []
    link_detail: list[str] = []

    first_stage = (
        df.groupby(["contract", "internet_type"], observed=True)
        .size()
        .reset_index(name="n")
    )
    for row in first_stage.itertuples(index=False):
        source.append(node_index[("Contract", str(row.contract))])
        target.append(node_index[("Internet", str(row.internet_type))])
        values.append(int(row.n))
        link_colors.append(hex_rgba(MOSS, 0.27))
        link_detail.append(f"{row.contract} → {row.internet_type}")

    second_stage = (
        df.groupby(["internet_type", "churn_label"], observed=True)
        .size()
        .reset_index(name="n")
    )
    for row in second_stage.itertuples(index=False):
        source.append(node_index[("Internet", str(row.internet_type))])
        target.append(node_index[("Outcome", str(row.churn_label))])
        values.append(int(row.n))
        link_colors.append(hex_rgba(STATUS_COLORS[str(row.churn_label)], 0.34))
        link_detail.append(f"{row.internet_type} → {row.churn_label}")

    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            valueformat=",d",
            node={
                "pad": 18,
                "thickness": 22,
                "line": {"color": SAGE, "width": 1},
                "label": labels,
                "color": node_colors,
                "hovertemplate": "<b>%{label}</b><br>%{value:,} customer flows<extra></extra>",
            },
            link={
                "source": source,
                "target": target,
                "value": values,
                "color": link_colors,
                "customdata": link_detail,
                "hovertemplate": "<b>%{customdata}</b><br>%{value:,} customers<extra></extra>",
            },
        )
    )
    return apply_chart_theme(
        fig,
        height=500,
        show_legend=False,
        margin={"l": 12, "r": 12, "t": 25, "b": 20},
    )


def risk_matrix(df: pd.DataFrame) -> go.Figure:
    usable = df.dropna(subset=["satisfaction_score"]).copy()
    usable["satisfaction_display"] = (
        usable["satisfaction_score"].round().clip(1, 5).astype(int).astype(str)
    )
    matrix = (
        usable.groupby(["contract", "satisfaction_display"], observed=True)
        .agg(
            customers=("customer_id", "size"),
            churn_rate=("churn_flag", "mean"),
            avg_charge=("monthly_charges", "mean"),
            avg_risk=("churn_score", "mean"),
        )
        .reset_index()
    )

    maximum = max(1, int(matrix["customers"].max()))
    sizes = 15 + 48 * np.sqrt(matrix["customers"] / maximum)
    text_threshold = max(2, int(matrix["customers"].quantile(0.25)))
    text = [
        f"{rate:.0%}" if count >= text_threshold else ""
        for rate, count in zip(matrix["churn_rate"], matrix["customers"])
    ]

    fig = go.Figure(
        go.Scatter(
            x=matrix["satisfaction_display"],
            y=matrix["contract"],
            mode="markers+text",
            text=text,
            textposition="middle center",
            textfont={"color": DARK, "size": 10},
            marker={
                "size": sizes,
                "color": matrix["churn_rate"],
                "colorscale": [[0.0, SAGE], [0.42, MOSS], [0.72, FOREST], [1.0, DARK]],
                "cmin": 0,
                "cmax": max(0.01, float(matrix["churn_rate"].max())),
                "showscale": True,
                "colorbar": {
                    "title": "Churn rate",
                    "tickformat": ".0%",
                    "thickness": 14,
                    "outlinewidth": 0,
                },
                "line": {"color": MOSS, "width": 1},
                "opacity": 0.88,
            },
            customdata=matrix[
                ["customers", "churn_rate", "avg_charge", "avg_risk"]
            ].to_numpy(),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Satisfaction: %{x}/5<br>"
                "Customers: %{customdata[0]:,}<br>"
                "Churn rate: %{customdata[1]:.1%}<br>"
                "Avg monthly charge: $%{customdata[2]:,.2f}<br>"
                "Avg risk score: %{customdata[3]:.1f}/100"
                "<extra></extra>"
            ),
            showlegend=False,
        )
    )
    fig.update_xaxes(
        title="Satisfaction score · 1 low → 5 high",
        categoryorder="array",
        categoryarray=["1", "2", "3", "4", "5"],
    )
    fig.update_yaxes(
        title="",
        categoryorder="array",
        categoryarray=["Two Year", "One Year", "Month-to-Month", "Missing"],
    )
    return apply_chart_theme(fig, height=500, show_legend=False)


def signal_separation(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Satisfaction score", "Churn risk score"),
        horizontal_spacing=0.13,
    )
    for label in ["Retained", "Churned"]:
        part = df.loc[df["churn_label"].eq(label)]
        fig.add_trace(
            go.Violin(
                y=part["satisfaction_score"],
                name=label,
                legendgroup=label,
                scalegroup=label,
                line={"color": STATUS_COLORS[label], "width": 2},
                fillcolor=hex_rgba(STATUS_COLORS[label], 0.42),
                opacity=0.82,
                box={"visible": True},
                meanline={"visible": True},
                points="outliers",
                hoveron="violins+points",
                showlegend=True,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Violin(
                y=part["churn_score"],
                name=label,
                legendgroup=label,
                scalegroup=label,
                line={"color": STATUS_COLORS[label], "width": 2},
                fillcolor=hex_rgba(STATUS_COLORS[label], 0.42),
                opacity=0.82,
                box={"visible": True},
                meanline={"visible": True},
                points="outliers",
                hoveron="violins+points",
                showlegend=False,
            ),
            row=1,
            col=2,
        )
    fig.update_yaxes(title="Score · 1–5", row=1, col=1)
    fig.update_yaxes(title="Score · 0–100", row=1, col=2)
    fig.update_xaxes(title="Customer outcome", row=1, col=1)
    fig.update_xaxes(title="Customer outcome", row=1, col=2)
    return apply_chart_theme(fig, height=470)


def customer_value_landscape(df: pd.DataFrame) -> go.Figure:
    plot = df.dropna(subset=["tenure_months", "total_revenue"]).copy()
    plot = sample_rows(plot)
    plot["_size"] = scaled_sizes(plot["monthly_charges"], 6, 20)

    fig = make_subplots(
        rows=2,
        cols=2,
        row_heights=[0.22, 0.78],
        column_widths=[0.80, 0.20],
        shared_xaxes=True,
        shared_yaxes=True,
        vertical_spacing=0.035,
        horizontal_spacing=0.035,
        specs=[
            [{"type": "histogram"}, None],
            [{"type": "scattergl"}, {"type": "histogram"}],
        ],
    )

    for label in ["Retained", "Churned"]:
        part = plot.loc[plot["churn_label"].eq(label)].sort_values("tenure_months")
        if part.empty:
            continue
        custom = part[
            [
                "customer_id",
                "contract",
                "internet_type",
                "monthly_charges",
                "cltv",
                "satisfaction_score",
            ]
        ].to_numpy()
        fig.add_trace(
            go.Histogram(
                x=part["tenure_months"],
                histnorm="probability density",
                nbinsx=28,
                marker={"color": STATUS_COLORS[label]},
                opacity=0.35,
                legendgroup=label,
                showlegend=False,
                hovertemplate=f"{label}<br>Tenure: %{{x}} months<br>Density: %{{y:.3f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scattergl(
                x=part["tenure_months"],
                y=part["total_revenue"],
                mode="markers",
                name=label,
                legendgroup=label,
                marker={
                    "size": part["_size"],
                    "color": STATUS_COLORS[label],
                    "symbol": STATUS_SYMBOLS[label],
                    "opacity": 0.62,
                    "line": {"color": MOSS, "width": 0.5},
                },
                customdata=custom,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    + f"Outcome: {label}<br>"
                    + "Tenure: %{x:,.0f} months<br>"
                    + "Total revenue: $%{y:,.2f}<br>"
                    + "Monthly charge: $%{customdata[3]:,.2f}<br>"
                    + "CLTV: $%{customdata[4]:,.0f}<br>"
                    + "Contract: %{customdata[1]}<br>"
                    + "Internet: %{customdata[2]}<br>"
                    + "Satisfaction: %{customdata[5]:.0f}/5"
                    + "<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )

        regression = part[["tenure_months", "total_revenue"]].dropna()
        if len(regression) >= 10 and regression["tenure_months"].nunique() > 1:
            slope, intercept = np.polyfit(
                regression["tenure_months"].to_numpy(),
                regression["total_revenue"].to_numpy(),
                1,
            )
            x_line = np.array(
                [regression["tenure_months"].min(), regression["tenure_months"].max()]
            )
            fig.add_trace(
                go.Scatter(
                    x=x_line,
                    y=slope * x_line + intercept,
                    mode="lines",
                    line={"color": STATUS_COLORS[label], "width": 2.2, "dash": "dot"},
                    name=f"{label} trend",
                    legendgroup=label,
                    showlegend=False,
                    hovertemplate=f"{label} linear trend<extra></extra>",
                ),
                row=2,
                col=1,
            )

        fig.add_trace(
            go.Histogram(
                y=part["total_revenue"],
                orientation="h",
                histnorm="probability density",
                nbinsy=28,
                marker={"color": STATUS_COLORS[label]},
                opacity=0.35,
                legendgroup=label,
                showlegend=False,
                hovertemplate=f"{label}<br>Revenue: $%{{y:,.0f}}<br>Density: %{{x:.3f}}<extra></extra>",
            ),
            row=2,
            col=2,
        )

    fig.update_layout(barmode="overlay")
    fig.update_xaxes(title="Tenure · months", row=2, col=1)
    fig.update_yaxes(
        title="Total revenue", tickprefix="$", tickformat="~s", row=2, col=1
    )
    fig.update_xaxes(showticklabels=False, title="", row=1, col=1)
    fig.update_yaxes(title="Density", showticklabels=False, row=1, col=1)
    fig.update_xaxes(title="Density", showticklabels=False, row=2, col=2)
    fig.update_yaxes(showticklabels=False, title="", row=2, col=2)
    return apply_chart_theme(
        fig, height=625, margin={"l": 65, "r": 20, "t": 35, "b": 55}
    )


def gini_coefficient(values: Iterable[float]) -> float:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    array = np.clip(array, 0, None)
    if len(array) == 0 or math.isclose(float(array.sum()), 0.0):
        return 0.0
    array.sort()
    n = len(array)
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * array) / (n * array.sum())) - (n + 1) / n)


def revenue_concentration(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[0, 1],
            y=[0, 1],
            mode="lines",
            name="Equal distribution",
            line={"color": MOSS, "width": 1.4, "dash": "dash"},
            hoverinfo="skip",
        )
    )

    for label in ["Retained", "Churned"]:
        revenue = (
            df.loc[df["churn_label"].eq(label), "total_revenue"]
            .dropna()
            .clip(lower=0)
            .sort_values()
            .to_numpy()
        )
        if len(revenue) == 0 or revenue.sum() <= 0:
            continue
        cumulative_revenue = np.insert(np.cumsum(revenue) / revenue.sum(), 0, 0)
        cumulative_customers = np.linspace(0, 1, len(revenue) + 1)
        if len(cumulative_customers) > 350:
            indices = np.unique(
                np.linspace(0, len(cumulative_customers) - 1, 350).astype(int)
            )
            cumulative_customers = cumulative_customers[indices]
            cumulative_revenue = cumulative_revenue[indices]
        gini = gini_coefficient(revenue)
        fig.add_trace(
            go.Scatter(
                x=cumulative_customers,
                y=cumulative_revenue,
                mode="lines",
                name=f"{label} · Gini {gini:.2f}",
                line={"color": STATUS_COLORS[label], "width": 3},
                fill="tozeroy" if label == "Retained" else None,
                fillcolor=hex_rgba(STATUS_COLORS[label], 0.10),
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    "Bottom customer share: %{x:.0%}<br>"
                    "Cumulative revenue share: %{y:.1%}<br>"
                    f"Gini coefficient: {gini:.2f}<extra></extra>"
                ),
            )
        )

    fig.update_xaxes(
        title="Cumulative share of customers", tickformat=".0%", range=[0, 1]
    )
    fig.update_yaxes(
        title="Cumulative share of revenue", tickformat=".0%", range=[0, 1]
    )
    return apply_chart_theme(fig, height=470)


def correlation_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(index=df.index)
    numeric_map = {
        "Age": "age",
        "Tenure": "tenure_months",
        "Dependents": "number_of_dependents",
        "Referrals": "number_of_referrals",
        "Monthly charges": "monthly_charges",
        "Total charges": "total_charges",
        "Refunds": "total_refunds",
        "Extra data charges": "total_extra_data_charges",
        "Long-distance charges": "total_long_distance_charges",
        "Total revenue": "total_revenue",
        "Satisfaction": "satisfaction_score",
        "CLTV": "cltv",
        "Churn risk score": "churn_score",
        "Monthly download": "avg_monthly_gb_download",
    }
    for label, column in numeric_map.items():
        if column in df.columns and df[column].notna().sum() >= 3:
            frame[label] = pd.to_numeric(df[column], errors="coerce")

    binary_map = {
        "Married": "married",
        "Streaming TV": "streaming_tv",
        "Streaming movies": "streaming_movies",
        "Tech support": "tech_support",
        "Online backup": "online_backup",
    }
    for label, column in binary_map.items():
        if column in df.columns:
            indicator = binary_indicator(df[column])
            if indicator.nunique(dropna=True) > 1:
                frame[label] = indicator

    for category in ["Month-to-Month", "One Year", "Two Year"]:
        if category in set(df["contract"]):
            frame[f"Contract · {category}"] = df["contract"].eq(category).astype(float)
    for category in ["Fiber Optic", "Cable", "DSL", "Missing"]:
        if category in set(df["internet_type"]):
            frame[f"Internet · {category}"] = (
                df["internet_type"].eq(category).astype(float)
            )

    frame["Churn outcome"] = df["churn_flag"].astype(float)
    frame = frame.loc[:, frame.nunique(dropna=True).gt(1)]
    return frame


def wrapped_label(label: str, width: int = 18) -> str:
    words = label.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "<br>".join(lines[:2])


def correlation_network(df: pd.DataFrame, threshold: float) -> go.Figure:
    frame = correlation_feature_frame(df)
    minimum_periods = min(len(frame), max(3, min(30, len(frame) // 10)))
    corr = frame.corr(min_periods=minimum_periods)
    target = "Churn outcome"

    if target not in corr.columns:
        fig = go.Figure()
        fig.add_annotation(
            x=0.5,
            y=0.56,
            xref="paper",
            yref="paper",
            text="Churn outcome is constant in this filtered view",
            showarrow=False,
            font={"color": DARK, "size": 18},
        )
        fig.add_annotation(
            x=0.5,
            y=0.45,
            xref="paper",
            yref="paper",
            text="Include both churned and retained customers to calculate churn correlations.",
            showarrow=False,
            font={"color": MOSS, "size": 12},
        )
        fig.update_xaxes(visible=False, range=[0, 1])
        fig.update_yaxes(visible=False, range=[0, 1])
        return apply_chart_theme(fig, height=420, show_legend=False)

    direct = corr[target].drop(target).dropna().abs().sort_values(ascending=False)
    if direct.empty:
        fig = go.Figure()
        fig.add_annotation(
            x=0.5,
            y=0.56,
            xref="paper",
            yref="paper",
            text="Not enough observations for a stable correlation network",
            showarrow=False,
            font={"color": DARK, "size": 18},
        )
        fig.add_annotation(
            x=0.5,
            y=0.45,
            xref="paper",
            yref="paper",
            text="Broaden the filters to include more customers and variation in churn outcome.",
            showarrow=False,
            font={"color": MOSS, "size": 12},
        )
        fig.update_xaxes(visible=False, range=[0, 1])
        fig.update_yaxes(visible=False, range=[0, 1])
        return apply_chart_theme(fig, height=420, show_legend=False)

    selected: list[str] = [target] + list(direct.head(8).index)

    upper_pairs: list[tuple[float, str, str]] = []
    features = [column for column in corr.columns if column != target]
    for left_index, left in enumerate(features):
        for right in features[left_index + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value):
                upper_pairs.append((abs(float(value)), left, right))
    upper_pairs.sort(reverse=True)
    for _, left, right in upper_pairs:
        for node in (left, right):
            if node not in selected and len(selected) < 14:
                selected.append(node)
        if len(selected) >= 14:
            break

    ring_nodes = [node for node in selected if node != target]
    positions: dict[str, tuple[float, float]] = {target: (0.0, 0.0)}
    for index, node in enumerate(ring_nodes):
        angle = (2 * math.pi * index / max(1, len(ring_nodes))) + math.pi / 2
        positions[node] = (math.cos(angle), math.sin(angle))

    edges: list[tuple[float, str, str]] = []
    for left_index, left in enumerate(selected):
        for right in selected[left_index + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value) and abs(float(value)) >= threshold:
                edges.append((float(value), left, right))
    edges.sort(key=lambda item: abs(item[0]))

    fig = go.Figure()
    midpoint_x: list[float] = []
    midpoint_y: list[float] = []
    midpoint_hover: list[str] = []
    for value, left, right in edges:
        x0, y0 = positions[left]
        x1, y1 = positions[right]
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line={
                    "color": FOREST if value >= 0 else MOSS,
                    "width": 1.2 + 5.2 * abs(value),
                    "dash": "solid" if value >= 0 else "dot",
                },
                opacity=0.30 + 0.60 * abs(value),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        midpoint_x.append((x0 + x1) / 2)
        midpoint_y.append((y0 + y1) / 2)
        midpoint_hover.append(
            f"<b>{html.escape(left)} ↔ {html.escape(right)}</b><br>Correlation: {value:+.2f}"
        )

    if midpoint_x:
        fig.add_trace(
            go.Scatter(
                x=midpoint_x,
                y=midpoint_y,
                mode="markers",
                marker={"size": 18, "color": hex_rgba(SAGE, 0.01)},
                text=midpoint_hover,
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            )
        )

    node_x = [positions[node][0] for node in selected]
    node_y = [positions[node][1] for node in selected]
    churn_correlations = [
        1.0 if node == target else float(corr.loc[node, target]) for node in selected
    ]
    node_sizes = [
        42 if node == target else 23 + 19 * abs(value)
        for node, value in zip(selected, churn_correlations)
    ]
    node_colors = [
        MOSS if node == target else (DARK if value >= 0 else SAGE)
        for node, value in zip(selected, churn_correlations)
    ]
    node_symbols = ["diamond" if node == target else "circle" for node in selected]
    node_hover = [
        (
            "<b>Churn outcome</b><br>Target variable"
            if node == target
            else f"<b>{html.escape(node)}</b><br>Correlation with churn: {value:+.2f}"
        )
        for node, value in zip(selected, churn_correlations)
    ]

    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=[wrapped_label(node) for node in selected],
            textposition="bottom center",
            textfont={"color": DARK, "size": 10},
            marker={
                "size": node_sizes,
                "color": node_colors,
                "symbol": node_symbols,
                "line": {"color": FOREST, "width": 1.4},
                "opacity": 0.95,
            },
            texttemplate="%{text}",
            customdata=node_hover,
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        )
    )

    # Compact semantic legend. Edge sign is also encoded with solid/dotted lines.
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker={"size": 11, "color": DARK},
            name="Positive with churn",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker={"size": 11, "color": SAGE, "line": {"color": FOREST, "width": 1}},
            name="Negative with churn",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="lines",
            line={"width": 3, "color": FOREST},
            name="Positive relationship",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="lines",
            line={"width": 3, "color": MOSS, "dash": "dot"},
            name="Negative relationship",
        )
    )

    if not edges:
        fig.add_annotation(
            x=0,
            y=-1.28,
            text=f"No relationships exceed |r| ≥ {threshold:.2f}. Lower the threshold.",
            showarrow=False,
            font={"color": MOSS},
        )
    fig.update_xaxes(visible=False, range=[-1.35, 1.35])
    fig.update_yaxes(visible=False, range=[-1.35, 1.35], scaleanchor="x", scaleratio=1)
    return apply_chart_theme(
        fig, height=650, margin={"l": 12, "r": 12, "t": 35, "b": 20}
    )


def relationship_explorer(
    df: pd.DataFrame, x_column: str, y_column: str, group_column: str
) -> go.Figure:
    plot = df.dropna(subset=[x_column, y_column]).copy()
    plot = sample_rows(plot, 5000)

    if group_column not in plot.columns:
        plot["_group"] = "All customers"
    else:
        plot["_group"] = clean_category(plot[group_column])

    counts = plot["_group"].value_counts()
    if len(counts) > 4:
        keep = set(counts.head(3).index)
        plot["_group"] = plot["_group"].where(plot["_group"].isin(keep), "Other")

    groups = ordered_values(plot["_group"], ["Retained", "Churned"])
    group_colors = {
        group: PALETTE[index % len(PALETTE)] for index, group in enumerate(groups)
    }
    if "Retained" in groups:
        group_colors["Retained"] = SAGE
    if "Churned" in groups:
        group_colors["Churned"] = DARK

    fig = make_subplots(
        rows=2,
        cols=2,
        row_heights=[0.22, 0.78],
        column_widths=[0.80, 0.20],
        shared_xaxes=True,
        shared_yaxes=True,
        vertical_spacing=0.035,
        horizontal_spacing=0.035,
        specs=[
            [{"type": "histogram"}, None],
            [{"type": "scattergl"}, {"type": "histogram"}],
        ],
    )

    for index, group in enumerate(groups):
        part = plot.loc[plot["_group"].eq(group)].sort_values(x_column)
        if part.empty:
            continue
        color = group_colors[group]
        fig.add_trace(
            go.Histogram(
                x=part[x_column],
                nbinsx=30,
                histnorm="probability density",
                marker={"color": color},
                opacity=0.30,
                legendgroup=group,
                showlegend=False,
                hovertemplate=f"{html.escape(group)}<br>{html.escape(humanize(x_column))}: %{{x:,.2f}}<br>Density: %{{y:.3f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        custom = part[
            [
                "customer_id",
                "churn_label",
                "contract",
                "internet_type",
                "monthly_charges",
                "tenure_months",
            ]
        ].to_numpy()
        fig.add_trace(
            go.Scattergl(
                x=part[x_column],
                y=part[y_column],
                mode="markers",
                name=group,
                legendgroup=group,
                marker={
                    "size": 7.5,
                    "color": color,
                    "symbol": ["circle", "diamond", "square", "triangle-up"][index % 4],
                    "opacity": 0.55,
                    "line": {"color": MOSS, "width": 0.35},
                },
                customdata=custom,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    f"{html.escape(humanize(x_column))}: %{{x:,.2f}}<br>"
                    f"{html.escape(humanize(y_column))}: %{{y:,.2f}}<br>"
                    "Outcome: %{customdata[1]}<br>"
                    "Contract: %{customdata[2]}<br>"
                    "Internet: %{customdata[3]}<br>"
                    "Monthly charge: $%{customdata[4]:,.2f}<br>"
                    "Tenure: %{customdata[5]:,.0f} months"
                    "<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )

        regression = part[[x_column, y_column]].dropna()
        if len(regression) >= 10 and regression[x_column].nunique() > 1:
            slope, intercept = np.polyfit(regression[x_column], regression[y_column], 1)
            x_line = np.array([regression[x_column].min(), regression[x_column].max()])
            fig.add_trace(
                go.Scatter(
                    x=x_line,
                    y=slope * x_line + intercept,
                    mode="lines",
                    line={"color": color, "width": 2.4, "dash": "dot"},
                    legendgroup=group,
                    showlegend=False,
                    hovertemplate=f"{html.escape(group)} linear trend<extra></extra>",
                ),
                row=2,
                col=1,
            )

        fig.add_trace(
            go.Histogram(
                y=part[y_column],
                orientation="h",
                nbinsy=30,
                histnorm="probability density",
                marker={"color": color},
                opacity=0.30,
                legendgroup=group,
                showlegend=False,
                hovertemplate=f"{html.escape(group)}<br>{html.escape(humanize(y_column))}: %{{y:,.2f}}<br>Density: %{{x:.3f}}<extra></extra>",
            ),
            row=2,
            col=2,
        )

    pearson = plot[[x_column, y_column]].corr(method="pearson").iloc[0, 1]
    spearman = plot[[x_column, y_column]].corr(method="spearman").iloc[0, 1]
    fig.add_annotation(
        x=0.99,
        y=0.98,
        xref="paper",
        yref="paper",
        xanchor="right",
        yanchor="top",
        text=f"Pearson r = {pearson:+.2f}<br>Spearman ρ = {spearman:+.2f}<br>n = {len(plot):,}",
        align="left",
        showarrow=False,
        bgcolor=hex_rgba(SAGE, 0.82),
        bordercolor=MOSS,
        borderpad=6,
        font={"color": DARK, "size": 11},
    )
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(title=humanize(x_column), row=2, col=1)
    fig.update_yaxes(title=humanize(y_column), row=2, col=1)
    fig.update_xaxes(showticklabels=False, title="", row=1, col=1)
    fig.update_yaxes(showticklabels=False, title="Density", row=1, col=1)
    fig.update_xaxes(showticklabels=False, title="Density", row=2, col=2)
    fig.update_yaxes(showticklabels=False, title="", row=2, col=2)
    return apply_chart_theme(
        fig, height=650, margin={"l": 65, "r": 20, "t": 38, "b": 55}
    )


# -----------------------------------------------------------------------------
# Dashboard composition
# -----------------------------------------------------------------------------


def render_metrics(all_data: pd.DataFrame, filtered: pd.DataFrame) -> None:
    customers = len(filtered)
    churn_rate = float(filtered["churn_flag"].mean()) if customers else 0.0
    baseline_churn = float(all_data["churn_flag"].mean()) if len(all_data) else 0.0
    high_risk_retained = int(
        (filtered["churn_label"].eq("Retained") & filtered["churn_score"].ge(70)).sum()
    )
    avg_monthly = float(filtered["monthly_charges"].mean())
    revenue = float(filtered["total_revenue"].sum(min_count=1))

    columns = st.columns(5)
    with columns[0]:
        st.metric(
            "Customers in view",
            f"{customers:,}",
            f"{customers / max(1, len(all_data)):.1%} of data",
        )
    with columns[1]:
        delta_points = (churn_rate - baseline_churn) * 100
        st.metric(
            "Churn rate",
            f"{churn_rate:.1%}",
            f"{delta_points:+.1f} pp vs all",
            delta_color="inverse",
        )
    with columns[2]:
        st.metric(
            "High-risk retained",
            f"{high_risk_retained:,}",
            "score ≥ 70",
            help="Retained customers whose churn_score is 70 or higher.",
        )
    with columns[3]:
        st.metric("Average monthly charge", format_money(avg_monthly))
    with columns[4]:
        st.metric("Revenue represented", format_money(revenue))


def hotspot_summary(df: pd.DataFrame) -> str:
    segment = (
        df.groupby(["contract", "internet_type"], observed=True)
        .agg(customers=("customer_id", "size"), churn_rate=("churn_flag", "mean"))
        .reset_index()
    )
    minimum_size = max(5, math.ceil(len(df) * 0.01))
    eligible = segment.loc[segment["customers"].ge(minimum_size)]
    if eligible.empty:
        eligible = segment
    row = eligible.sort_values(["churn_rate", "customers"], ascending=False).iloc[0]
    return (
        f"<strong>Highest-risk meaningful segment:</strong> "
        f"{html.escape(str(row['contract']))} contract with "
        f"{html.escape(str(row['internet_type']))} internet · "
        f"{row['churn_rate']:.1%} churn across {int(row['customers']):,} customers."
    )


def main() -> None:
    inject_css()
    data, source_name = load_data()

    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">Telecom customer analytics</div>
            <h1>Customer Retention Intelligence</h1>
            <p>See where churn risk concentrates, how customers move through service choices,
            and which segments carry the most durable value.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if data is None:
        st.warning(
            "Upload **master_view_v1.csv** from the sidebar, or place it in the same folder "
            "as `telecom_churn_dashboard.py`, then rerun the app."
        )
        st.code("streamlit run telecom_churn_dashboard.py", language="bash")
        st.stop()

    filtered = build_filters(data, source_name)
    if filtered.empty:
        st.error("No customers match this filter combination.")
        if st.button("Reset filters", type="primary"):
            clear_filters()
            st.rerun()
        st.stop()

    render_metrics(data, filtered)
    st.markdown(
        f'<div class="insight-strip"><span>◆</span><span>{hotspot_summary(filtered)}</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="method-note"><strong>Counting rule:</strong> '
        "<code>churn_value</code> determines churned versus retained customers. "
        "<code>churn_score</code> remains a continuous 0–100 risk signal and is never used to count churn.</div>",
        unsafe_allow_html=True,
    )

    foundation_tab, journey_tab, value_tab, relationship_tab = st.tabs(
        [
            "Foundational analysis",
            "Retention pathways",
            "Customer value",
            "Relationship lab",
        ]
    )

    with foundation_tab:
        section_heading(
            "1 · Customer composition",
            "Begin with direct counts, percentages and category comparisons before moving into relationships.",
        )
        left, right = st.columns([1.12, 0.88], gap="large")
        with left:
            section_heading(
                "Streaming service adoption",
                "Compare the share of customers subscribed to streaming movies and streaming TV.",
            )
            render_chart(streaming_adoption(filtered), "streaming-adoption")
        with right:
            section_heading(
                "Referral share by marital status",
                "The donut represents total referrals, not simply the number of married and unmarried customers.",
            )
            render_chart(referral_marital_donut(filtered), "referral-marital-donut")

        churn_column, contract_column, internet_column = st.columns(
            [0.72, 1.05, 1.05], gap="large"
        )
        with churn_column:
            section_heading(
                "Customer outcome",
                "Overall retained-versus-churned composition using churn_value.",
            )
            render_chart(churn_outcome_donut(filtered), "churn-outcome-donut")
        with contract_column:
            section_heading(
                "Churned customers by contract",
                "Bar length is the number of churned customers; hover for the within-contract churn rate.",
            )
            render_chart(
                churned_customers_by_contract(filtered),
                "churned-customers-by-contract",
            )
        with internet_column:
            section_heading(
                "Average monthly charge by internet type",
                "Compare average bills across the available internet products.",
            )
            render_chart(
                average_monthly_charge_by_internet(filtered),
                "average-charge-by-internet",
            )

        st.markdown("---")
        section_heading(
            "2 · Revenue relationship",
            "Move from category summaries to a two-variable relationship; colour and shape retain the customer outcome.",
        )
        section_heading(
            "Revenue versus long-distance charges",
            "Each point is a customer. Zoom, pan or hover to inspect the customer and service context.",
        )
        if filtered[["total_long_distance_charges", "total_revenue"]].dropna().empty:
            st.info(
                "Revenue and long-distance charges are unavailable for the selected customers."
            )
        else:
            render_chart(
                revenue_long_distance_scatter(filtered),
                "revenue-long-distance-scatter",
            )

        st.markdown("---")
        section_heading(
            "3 · Multivariate patterns",
            "Finish the page with the harder views: distributions and pairwise relationships, followed by a correlation matrix.",
        )
        section_heading(
            "Pairplot of five key features",
            "Diagonal cells show distributions; every other cell compares a feature pair and separates actual outcomes.",
        )
        render_chart(top_feature_pairplot(filtered), "top-feature-pairplot")

        section_heading(
            "Correlation heatmap of important features",
            "Values are Pearson correlations from −1 to +1; correlation describes association, not causation.",
        )
        render_chart(important_feature_heatmap(filtered), "important-feature-heatmap")

    with journey_tab:
        left, right = st.columns([1.14, 0.86], gap="large")
        with left:
            section_heading(
                "Risk–satisfaction landscape",
                "Bubble size represents monthly charge; shape and colour separate actual outcome.",
            )
            if filtered[["churn_score", "satisfaction_score"]].dropna().empty:
                st.info(
                    "Risk and satisfaction scores are unavailable for the selected customers."
                )
            else:
                render_chart(risk_landscape(filtered), "risk-landscape")
        with right:
            section_heading(
                "Segment retention architecture",
                "Area shows customer volume; colour intensity shows churn rate. Click a tile to drill in.",
            )
            render_chart(segment_treemap(filtered), "segment-treemap")

        st.markdown("---")
        left, right = st.columns([1.08, 0.92], gap="large")
        with left:
            section_heading(
                "Contract → internet → outcome",
                "Follow customer volume through two service choices into retained or churned outcomes.",
            )
            render_chart(retention_sankey(filtered), "retention-sankey")
        with right:
            section_heading(
                "Retention risk matrix",
                "Bubble area represents customers; colour and labels represent churn rate.",
            )
            if filtered["satisfaction_score"].notna().sum() == 0:
                st.info(
                    "Satisfaction scores are unavailable for the selected customers."
                )
            else:
                render_chart(risk_matrix(filtered), "risk-matrix")

        section_heading(
            "Signal separation",
            "Distribution, median, quartiles and outliers reveal how satisfaction and risk scores separate outcomes.",
        )
        render_chart(signal_separation(filtered), "signal-separation")

    with value_tab:
        section_heading(
            "Customer value landscape",
            "Revenue and tenure share one view with marginal distributions and outcome-specific trend lines.",
        )
        if filtered[["tenure_months", "total_revenue"]].dropna().empty:
            st.info("Tenure and revenue are unavailable for the selected customers.")
        else:
            render_chart(customer_value_landscape(filtered), "customer-value-landscape")

        left, right = st.columns([0.68, 0.32], gap="large")
        with left:
            section_heading(
                "Revenue concentration curve",
                "A larger bow below the equality line means revenue is concentrated among fewer customers.",
            )
            render_chart(revenue_concentration(filtered), "revenue-concentration")
        with right:
            section_heading(
                "Value interpretation",
                "Use this panel as a decision aid, not a second chart.",
            )
            retained_revenue = filtered.loc[
                filtered["churn_label"].eq("Retained"), "total_revenue"
            ].sum(min_count=1)
            churned_revenue = filtered.loc[
                filtered["churn_label"].eq("Churned"), "total_revenue"
            ].sum(min_count=1)
            total = retained_revenue + churned_revenue
            retained_share = (
                retained_revenue / total if pd.notna(total) and total != 0 else np.nan
            )
            avg_cltv_retained = filtered.loc[
                filtered["churn_label"].eq("Retained"), "cltv"
            ].mean()
            avg_cltv_churned = filtered.loc[
                filtered["churn_label"].eq("Churned"), "cltv"
            ].mean()
            st.metric(
                "Revenue from retained",
                f"{retained_share:.1%}" if pd.notna(retained_share) else "—",
            )
            st.metric("Avg CLTV · retained", format_money(avg_cltv_retained))
            st.metric("Avg CLTV · churned", format_money(avg_cltv_churned))

    with relationship_tab:
        section_heading(
            "Correlation network",
            "Node size reflects association with churn; edge width reflects relationship strength. Dotted edges are negative.",
        )
        threshold = st.slider(
            "Minimum absolute correlation shown",
            min_value=0.20,
            max_value=0.80,
            value=0.35,
            step=0.05,
            key="correlation_threshold",
        )
        render_chart(correlation_network(filtered, threshold), "correlation-network")

        st.markdown("---")
        section_heading(
            "Interactive relationship explorer",
            "Choose any two continuous measures; marginal distributions, grouped points and trend lines update together.",
        )
        candidate_columns = [
            column
            for column in NUMERIC_COLUMNS
            if column in filtered.columns and filtered[column].nunique(dropna=True) >= 3
        ]
        if len(candidate_columns) < 2:
            st.info(
                "At least two non-constant numeric fields are required for the relationship explorer."
            )
        else:
            controls = st.columns([1, 1, 1])
            default_x = (
                "total_long_distance_charges"
                if "total_long_distance_charges" in candidate_columns
                else candidate_columns[0]
            )
            with controls[0]:
                x_column = st.selectbox(
                    "Horizontal measure",
                    candidate_columns,
                    index=candidate_columns.index(default_x),
                    format_func=humanize,
                )
            y_candidates = [
                column for column in candidate_columns if column != x_column
            ]
            default_y = (
                "total_revenue" if "total_revenue" in y_candidates else y_candidates[0]
            )
            with controls[1]:
                y_column = st.selectbox(
                    "Vertical measure",
                    y_candidates,
                    index=y_candidates.index(default_y),
                    format_func=humanize,
                )
            group_options = {
                "Churn outcome": "churn_label",
                "Contract": "contract",
                "Internet type": "internet_type",
                "Customer status": "customer_status",
            }
            with controls[2]:
                group_label = st.selectbox("Group points by", list(group_options))
            render_chart(
                relationship_explorer(
                    filtered, x_column, y_column, group_options[group_label]
                ),
                "relationship-explorer",
            )

    with st.expander("Inspect filtered records", expanded=False):
        visible_columns = [
            "customer_id",
            "customer_status",
            "churn_value",
            "churn_score",
            "satisfaction_score",
            "contract",
            "internet_type",
            "tenure_months",
            "monthly_charges",
            "total_revenue",
            "cltv",
        ]
        visible_columns = [
            column for column in visible_columns if column in filtered.columns
        ]
        st.dataframe(
            filtered[visible_columns].head(1000),
            use_container_width=True,
            hide_index=True,
            height=360,
        )
        st.caption(
            "Showing up to 1,000 filtered rows. Use the sidebar download for the complete filtered set."
        )


if __name__ == "__main__":
    main()
