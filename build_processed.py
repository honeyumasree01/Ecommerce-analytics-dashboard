"""
Build analytics artifacts under `data/processed/` from the raw CSVs in `data/raw/`.

This script is intentionally dependency-light (pandas + scipy) so it runs even when
DuckDB / Streamlit aren't installed yet.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
from scipy.stats import norm


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
OUT_DIR = BASE_DIR / "data" / "processed"


def _read_events() -> pd.DataFrame:
    events_path = RAW_DIR / "events.csv"
    df = pd.read_csv(events_path)
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], utc=False, errors="raise")
    return df


def _read_users() -> pd.DataFrame:
    return pd.read_csv(RAW_DIR / "users.csv")


def _read_products() -> pd.DataFrame:
    return pd.read_csv(RAW_DIR / "products.csv")


def _variant_for_user(user_id: str) -> str:
    # Deterministic assignment so results are reproducible.
    # (0 -> control, 1 -> treatment)
    h = hashlib.md5(user_id.encode("utf-8")).hexdigest()
    v = int(h, 16) % 2
    return "A_control" if v == 0 else "B_treatment"


def build_funnel(events: pd.DataFrame) -> pd.DataFrame:
    view_users = events.loc[events["event_type"] == "view", "user_id"].nunique()
    cart_users = events.loc[events["event_type"] == "cart", "user_id"].nunique()
    purchase_users = events.loc[events["event_type"] == "purchase", "user_id"].nunique()

    view_to_cart = cart_users / view_users if view_users else 0.0
    cart_to_purchase_strict = (
        events.loc[events["event_type"] == "purchase", "user_id"].isin(
            events.loc[events["event_type"] == "cart", "user_id"].unique()
        )
    )
    # The strict cart->purchase definition for the project:
    # cart users who also have at least one purchase (same as purchasers among cart users).
    cart_user_ids = set(events.loc[events["event_type"] == "cart", "user_id"].unique())
    purchase_user_ids = set(events.loc[events["event_type"] == "purchase", "user_id"].unique())
    cart_users_that_purchase = len(cart_user_ids & purchase_user_ids)
    cart_to_purchase_strict = cart_users_that_purchase / cart_users if cart_users else 0.0

    view_to_purchase_overall = purchase_users / view_users if view_users else 0.0

    out = pd.DataFrame(
        [
            {"stage": "view", "users": int(view_users)},
            {"stage": "cart", "users": int(cart_users)},
            {"stage": "purchase", "users": int(purchase_users)},
        ]
    )

    rates = pd.DataFrame(
        [
            {"metric": "view_to_cart", "rate": float(view_to_cart)},
            {"metric": "cart_to_purchase_strict", "rate": float(cart_to_purchase_strict)},
            {"metric": "view_to_purchase_overall", "rate": float(view_to_purchase_overall)},
        ]
    )

    # Store as 2-row "rates" + a "stages" sheet in wide form for dashboard simplicity.
    # (Streamlit can render both.)
    rates["rate_pct"] = (rates["rate"] * 100.0).round(2)
    out["users"] = out["users"].astype(int)
    out.attrs["rates_df"] = rates
    return out


def build_cohort_retention_week1(events: pd.DataFrame) -> pd.DataFrame:
    # Cohort = each user's first event date (calendar day)
    first_event_ts = events.groupby("user_id")["event_timestamp"].min()
    cohort_date = first_event_ts.dt.floor("D")

    # Week-1 retention = any event in [first+7d, first+14d)
    start = first_event_ts + pd.Timedelta(days=7)
    end = first_event_ts + pd.Timedelta(days=14)
    tmp = events[["user_id", "event_timestamp"]].merge(
        pd.DataFrame({"user_id": first_event_ts.index, "start": start.values, "end": end.values}),
        on="user_id",
        how="left",
    )
    active_week1 = ((tmp["event_timestamp"] >= tmp["start"]) & (tmp["event_timestamp"] < tmp["end"])).groupby(tmp["user_id"]).any()

    users = pd.DataFrame({"user_id": first_event_ts.index, "cohort_date": cohort_date.values})
    users = users.merge(active_week1.rename("week1_active").reset_index(), on="user_id", how="left")
    users["week1_active"] = users["week1_active"].fillna(False)

    users["cohort_month"] = users["cohort_date"].dt.to_period("M").astype(str)

    cohort = (
        users.groupby("cohort_month")
        .agg(cohort_users=("user_id", "nunique"), week1_users=("week1_active", "sum"))
        .reset_index()
    )
    cohort["week1_retention"] = cohort["week1_users"] / cohort["cohort_users"]
    cohort["week1_retention_pct"] = (cohort["week1_retention"] * 100.0).round(2)

    return cohort.sort_values("cohort_month")


def build_segment_conversion(events: pd.DataFrame, users: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    cart_users = set(events.loc[events["event_type"] == "cart", "user_id"].unique())
    purchase_users = set(events.loc[events["event_type"] == "purchase", "user_id"].unique())

    # Segment 1: gender
    gender_users = users[["user_id", "gender"]].drop_duplicates()
    gender_base = gender_users[gender_users["user_id"].isin(cart_users)].copy()
    gender_base["has_purchase"] = gender_base["user_id"].isin(purchase_users)

    gender_seg = (
        gender_base.groupby("gender")
        .agg(cart_users=("user_id", "nunique"), purchased=("has_purchase", "sum"))
        .reset_index()
    )
    gender_seg["cart_to_purchase_conversion"] = gender_seg["purchased"] / gender_seg["cart_users"]
    gender_seg["cart_to_purchase_conversion_pct"] = (gender_seg["cart_to_purchase_conversion"] * 100.0).round(2)
    gender_seg["segment_type"] = "gender"
    gender_seg = gender_seg.rename(columns={"gender": "segment_value"})[
        ["segment_type", "segment_value", "cart_users", "purchased", "cart_to_purchase_conversion", "cart_to_purchase_conversion_pct"]
    ]

    # Segment 2: primary cart category per user (mode of category among cart events)
    carts = events.loc[events["event_type"] == "cart", ["user_id", "product_id"]]
    carts = carts.merge(products[["product_id", "category"]], on="product_id", how="left")
    primary_cat = carts.groupby("user_id")["category"].agg(lambda s: s.value_counts().index[0]).rename("primary_cart_category").reset_index()
    primary_cat = primary_cat[primary_cat["user_id"].isin(cart_users)].copy()
    primary_cat["has_purchase"] = primary_cat["user_id"].isin(purchase_users)

    cat_seg = (
        primary_cat.groupby("primary_cart_category")
        .agg(cart_users=("user_id", "nunique"), purchased=("has_purchase", "sum"))
        .reset_index()
    )
    cat_seg["cart_to_purchase_conversion"] = cat_seg["purchased"] / cat_seg["cart_users"]
    cat_seg["cart_to_purchase_conversion_pct"] = (cat_seg["cart_to_purchase_conversion"] * 100.0).round(2)
    cat_seg["segment_type"] = "primary_cart_category"
    cat_seg = cat_seg.rename(columns={"primary_cart_category": "segment_value"})[
        ["segment_type", "segment_value", "cart_users", "purchased", "cart_to_purchase_conversion", "cart_to_purchase_conversion_pct"]
    ]

    return pd.concat([gender_seg, cat_seg], ignore_index=True).sort_values(["segment_type", "cart_users"], ascending=[True, False])


def build_ab_test(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Experiment population: users with >=1 cart
    cart_users = events.loc[events["event_type"] == "cart", "user_id"].unique()
    cart_users = pd.Series(cart_users, name="user_id")

    # First cart timestamp per user
    first_cart = (
        events.loc[events["event_type"] == "cart", ["user_id", "event_timestamp"]]
        .groupby("user_id")["event_timestamp"]
        .min()
        .rename("first_cart_ts")
        .reset_index()
    )

    # Purchases within 7 days of first cart
    purchases = events.loc[events["event_type"] == "purchase", ["user_id", "event_timestamp"]].merge(first_cart, on="user_id", how="inner")
    in_window = (purchases["event_timestamp"] >= purchases["first_cart_ts"]) & (
        purchases["event_timestamp"] < purchases["first_cart_ts"] + pd.Timedelta(days=7)
    )
    purchase_within_7 = in_window.groupby(purchases["user_id"]).any().rename("purchase_within_7d").reset_index()

    exp = first_cart.merge(purchase_within_7, on="user_id", how="left")
    exp["purchase_within_7d"] = exp["purchase_within_7d"].fillna(False)

    exp["variant"] = exp["user_id"].apply(_variant_for_user)
    exp["experiment_name"] = "checkout_optimization"

    # Guardrail: week-1 retention (based on first event, not first cart)
    first_event_ts = events.groupby("user_id")["event_timestamp"].min()
    start = first_event_ts + pd.Timedelta(days=7)
    end = first_event_ts + pd.Timedelta(days=14)

    tmp = events[["user_id", "event_timestamp"]].merge(
        pd.DataFrame({"user_id": first_event_ts.index, "start": start.values, "end": end.values}),
        on="user_id",
        how="left",
    )
    week1_active = ((tmp["event_timestamp"] >= tmp["start"]) & (tmp["event_timestamp"] < tmp["end"])).groupby(tmp["user_id"]).any().rename("week1_active").reset_index()
    exp = exp.merge(week1_active, on="user_id", how="left")
    exp["week1_active"] = exp["week1_active"].fillna(False)

    # Guardrail: time-to-activation (purchase within 24 hours of first event)
    first_any = events.groupby("user_id")["event_timestamp"].min().rename("first_event_ts").reset_index()
    purchases2 = events.loc[events["event_type"] == "purchase", ["user_id", "event_timestamp"]].merge(first_any, on="user_id", how="left")
    act_mask = (purchases2["event_timestamp"] >= purchases2["first_event_ts"]) & (
        purchases2["event_timestamp"] < purchases2["first_event_ts"] + pd.Timedelta(hours=24)
    )
    # Earliest purchase within activation window per user
    tt = (
        purchases2.loc[act_mask]
        .sort_values(["user_id", "event_timestamp"])
        .groupby("user_id")
        .head(1)
    )
    time_to_activation_hours = (tt["event_timestamp"] - tt["first_event_ts"]).dt.total_seconds() / 3600.0
    act_user = tt[["user_id"]].copy()
    act_user["time_to_activation_hours"] = time_to_activation_hours
    exp = exp.merge(act_user, on="user_id", how="left")

    # Aggregate results
    results = []
    for variant, g in exp.groupby("variant"):
        total = int(g["user_id"].nunique())
        success = int(g["purchase_within_7d"].sum())
        conv = success / total if total else 0.0
        week1_ret = float(g["week1_active"].mean()) if total else 0.0

        tt_vals = g["time_to_activation_hours"].dropna()
        median_tt = float(tt_vals.median()) if len(tt_vals) else None
        mean_tt = float(tt_vals.mean()) if len(tt_vals) else None

        results.append(
            {
                "experiment_name": "checkout_optimization",
                "variant": variant,
                "total_users": total,
                "success_users": success,
                "conversion_rate": conv,
                "conversion_rate_pct": round(conv * 100.0, 4),
                "week1_retention_rate": week1_ret,
                "week1_retention_rate_pct": round(week1_ret * 100.0, 4),
                "median_time_to_activation_hours": median_tt,
                "mean_time_to_activation_hours": mean_tt,
            }
        )

    ab_results = pd.DataFrame(results)

    # Significance for primary metric (two-proportion z-test, two-sided)
    ctrl = ab_results.loc[ab_results["variant"] == "A_control"].iloc[0]
    trt = ab_results.loc[ab_results["variant"] == "B_treatment"].iloc[0]

    n1 = int(ctrl["total_users"])
    x1 = int(ctrl["success_users"])
    n2 = int(trt["total_users"])
    x2 = int(trt["success_users"])
    p1 = x1 / n1 if n1 else 0.0
    p2 = x2 / n2 if n2 else 0.0
    p_pool = (x1 + x2) / (n1 + n2) if (n1 + n2) else 0.0
    se = (p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) ** 0.5 if (n1 and n2) else None
    z = ((p2 - p1) / se) if se else None
    p_value = float(2 * (1 - norm.cdf(abs(z)))) if z is not None else None

    lift_abs = p2 - p1
    lift_rel = (p2 - p1) / p1 if p1 else None

    ab_results_summary = pd.DataFrame(
        [
            {
                "experiment_name": "checkout_optimization",
                "control_variant": "A_control",
                "treatment_variant": "B_treatment",
                "control_conversion_rate": p1,
                "treatment_conversion_rate": p2,
                "lift_abs": lift_abs,
                "lift_abs_pct_points": lift_abs * 100.0,
                "lift_rel": lift_rel,
                "z_stat": float(z) if z is not None else None,
                "p_value_two_sided": p_value,
            }
        ]
    )

    # Assignments table for transparency
    assignments = exp[["user_id", "variant", "experiment_name"]].copy()

    return ab_results, ab_results_summary, assignments


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    events = _read_events()
    users = _read_users()
    products = _read_products()

    # STEP A: Funnel
    funnel_stages = build_funnel(events)
    rates_df = funnel_stages.attrs.get("rates_df")
    funnel_stages.to_csv(OUT_DIR / "funnel_stages.csv", index=False)
    if rates_df is not None:
        rates_df.to_csv(OUT_DIR / "funnel_rates.csv", index=False)

    # For dashboard simplicity, also export a single "funnel.csv"
    funnel_rates = pd.read_csv(OUT_DIR / "funnel_rates.csv")
    funnel = funnel_stages.merge(funnel_rates, how="cross")
    funnel.to_csv(OUT_DIR / "funnel.csv", index=False)

    # STEP B: Cohort retention
    cohort = build_cohort_retention_week1(events)
    cohort.to_csv(OUT_DIR / "cohort_retention.csv", index=False)

    # STEP C: Segments conversion
    seg = build_segment_conversion(events, users, products)
    seg.to_csv(OUT_DIR / "segment_conversion.csv", index=False)

    # STEP D: A/B test (simulated assignment)
    ab_results, ab_summary, assignments = build_ab_test(events)
    ab_results.to_csv(OUT_DIR / "ab_results_by_variant.csv", index=False)
    ab_summary.to_csv(OUT_DIR / "ab_results_summary.csv", index=False)
    assignments.to_csv(OUT_DIR / "experiment_assignments.csv", index=False)

    print("Built processed artifacts:")
    for p in [
        OUT_DIR / "funnel_stages.csv",
        OUT_DIR / "funnel_rates.csv",
        OUT_DIR / "cohort_retention.csv",
        OUT_DIR / "segment_conversion.csv",
        OUT_DIR / "ab_results_by_variant.csv",
        OUT_DIR / "ab_results_summary.csv",
    ]:
        print("-", p.name)


if __name__ == "__main__":
    main()

