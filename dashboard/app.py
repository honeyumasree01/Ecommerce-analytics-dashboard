from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
DOCS_DIR = BASE_DIR / "docs"


def _read_csv(name: str) -> pd.DataFrame:
    path = PROCESSED_DIR / name
    if not path.exists():
        st.error(f"Missing artifact: `{name}`. Run `python build_processed.py` first.")
        st.stop()
    return pd.read_csv(path)


st.set_page_config(page_title="Product Analysis Dashboard", layout="wide")
st.markdown(
    """
<style>
.block-container {
    padding-top: 1.6rem;
    padding-bottom: 1.6rem;
}
[data-testid="stMetricValue"] {
    font-size: 1.65rem;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("Product Analysis Dashboard")
st.caption(
    "Event-level e-commerce analysis focused on funnel conversion, activation, and retention."
)

funnel = _read_csv("funnel_stages.csv")
rates = _read_csv("funnel_rates.csv")
cohort = _read_csv("cohort_retention.csv")
segments = _read_csv("segment_conversion.csv")
ab = _read_csv("ab_results_by_variant.csv")
summary = _read_csv("ab_results_summary.csv")
assign = _read_csv("experiment_assignments.csv")

stage_users = {r["stage"]: int(r["users"]) for _, r in funnel.iterrows()}
strict_rate = float(
    rates.loc[rates["metric"] == "cart_to_purchase_strict", "rate_pct"].iloc[0]
)
week1_overall = float(
    cohort["week1_users"].sum() / cohort["cohort_users"].sum() * 100.0
)

k1, k2, k3, k4 = st.columns(4)
k1.metric("View Users", f"{stage_users.get('view', 0):,}")
k2.metric("Cart Users", f"{stage_users.get('cart', 0):,}")
k3.metric("Purchase Users", f"{stage_users.get('purchase', 0):,}")
k4.metric("Cart → Purchase", f"{strict_rate:.2f}%")

with st.expander("Definitions & metric grain"):
    st.markdown("See [`docs/DEFINITIONS.md`](../docs/DEFINITIONS.md) for locked definitions.")

with st.sidebar:
    st.header("Project Context")
    st.markdown("**Goal:** Improve activation and week-1 retention by identifying funnel bottlenecks.")
    st.markdown(
        "**Locked metric definitions**\n"
        "- Funnel: `view → cart → purchase`\n"
        "- Activation: purchase within 24h of first event\n"
        "- Retention: any event in days 7–14 after first event\n"
        "- Funnel level: user-level"
    )
    st.markdown(
        "This analysis uses synthetic data. While the patterns are useful for demonstrating "
        "product analytics methodology, results should be validated using real production data "
        "before making business decisions."
    )

st.divider()

tab_funnel, tab_retention, tab_segments, tab_experiment, tab_sql = st.tabs(
    ["Funnel", "Retention", "Segments", "Experiment", "SQL"]
)


with tab_funnel:
    st.subheader("Funnel drop-off (user-level)")
    st.info(
        f"Key insight: The biggest drop occurs after cart — only ~{strict_rate:.2f}% convert to purchase."
    )
    st.bar_chart(funnel.set_index("stage")["users"], use_container_width=True)
    st.dataframe(funnel[["stage", "users"]], hide_index=True)

    rate_labels = {
        "view_to_cart": "View → Cart",
        "cart_to_purchase_strict": "Strict Cart → Purchase",
        "view_to_purchase_overall": "View → Purchase (Overall)",
    }
    rate_view = rates.copy()
    rate_view["Metric"] = rate_view["metric"].map(rate_labels).fillna(rate_view["metric"])
    rate_view["Rate"] = rate_view["rate_pct"].map(lambda x: f"{x:.2f}%")
    st.markdown("**Conversion rates**")
    st.dataframe(rate_view[["Metric", "Rate"]], hide_index=True)


with tab_retention:
    st.subheader("Week-1 Retention")
    st.info(
        f"Key insight: Only ~{week1_overall:.1f}% users return in week 1, indicating weak repeat engagement."
    )
    st.markdown("Definition: any event in `[first_event+7d, first_event+14d)`.")
    st.line_chart(
        cohort.sort_values("cohort_month").set_index("cohort_month")["week1_retention_pct"],
        use_container_width=True,
    )
    retention_view = cohort.sort_values("cohort_month").rename(
        columns={
            "cohort_month": "Cohort Month",
            "cohort_users": "Cohort Users",
            "week1_users": "Week-1 Active Users",
            "week1_retention_pct": "Week-1 Retention (%)",
        }
    )
    st.dataframe(
        retention_view[["Cohort Month", "Cohort Users", "Week-1 Active Users", "Week-1 Retention (%)"]],
        hide_index=True,
    )


with tab_segments:
    st.subheader("Segment Conversion")
    st.info("Key takeaway: Gender differences are minimal; category differences are more actionable.")
    st.markdown("Strict metric: among users with ≥1 cart, the share with ≥1 purchase.")

    seg_label_map = {
        "gender": "Gender",
        "primary_cart_category": "Primary Cart Category",
    }
    seg_type = st.selectbox(
        "Segment type",
        options=sorted(segments["segment_type"].unique()),
        format_func=lambda x: seg_label_map.get(x, x),
        index=0,
        help="Choose whether to display demographic slices or product-category slices.",
    )
    view = segments.loc[segments["segment_type"] == seg_type].copy()
    view = view.sort_values("cart_to_purchase_conversion_pct", ascending=True)

    st.bar_chart(
        view.set_index("segment_value")["cart_to_purchase_conversion_pct"],
        use_container_width=True,
    )
    view = view.rename(
        columns={
            "segment_value": "Segment",
            "cart_users": "Cart Users",
            "purchased": "Purchased Users",
            "cart_to_purchase_conversion_pct": "Strict Cart → Purchase (%)",
        }
    )
    st.dataframe(
        view[["Segment", "Cart Users", "Purchased Users", "Strict Cart → Purchase (%)"]],
        hide_index=True,
    )


with tab_experiment:
    st.subheader("Experiment")
    st.info("Key takeaway: Checkout optimization targets the highest-friction step: cart to purchase.")
    st.markdown("**Primary metric:** Strict Cart → Purchase within 7 days of first cart.")

    e1, e2, e3 = st.columns(3)
    e1.metric(
        "Control Conversion",
        f"{ab.loc[ab['variant'] == 'A_control', 'conversion_rate_pct'].iloc[0]:.2f}%",
    )
    e2.metric(
        "Treatment Conversion",
        f"{ab.loc[ab['variant'] == 'B_treatment', 'conversion_rate_pct'].iloc[0]:.2f}%",
    )
    e3.metric("Week-1 Retention (overall)", f"{week1_overall:.2f}%")

    if len(summary) == 1:
        row = summary.iloc[0]
        st.markdown("**Lift summary**")
        st.write(f"Lift (absolute): {row['lift_abs_pct_points']:.2f} percentage points")
        st.write(f"p-value (two-sided): {row['p_value_two_sided']:.3f}")

    ab_view = ab.rename(
        columns={
            "variant": "Variant",
            "total_users": "Users",
            "success_users": "Converted Users",
            "conversion_rate_pct": "Conversion (%)",
            "week1_retention_rate_pct": "Week-1 Retention (%)",
            "median_time_to_activation_hours": "Median Time-to-Activation (hrs)",
        }
    )
    st.dataframe(
        ab_view[
            [
                "Variant",
                "Users",
                "Converted Users",
                "Conversion (%)",
                "Week-1 Retention (%)",
                "Median Time-to-Activation (hrs)",
            ]
        ],
        hide_index=True,
    )
    st.caption(f"Assignment rows available: {len(assign):,} users.")


with tab_sql:
    st.subheader("SQL Query Library")
    st.markdown(
        "These SQL queries power the funnel, retention, segmentation, and experiment analysis in this dashboard."
    )
    st.markdown(
        "- `sql/01_funnel_dropoff.sql`\n"
        "- `sql/02_cohort_retention_week1.sql`\n"
        "- `sql/03_conversion_by_segment.sql`\n"
        "- `sql/04_ab_test_primary_and_guardrails.sql`"
    )

st.divider()
st.caption("Built using event-level data, SQL-based analysis, and Streamlit for visualization.")

