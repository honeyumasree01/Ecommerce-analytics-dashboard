# Locked definitions (Step 4)

These definitions are fixed for this project unless explicitly revised.

## Funnel

Ordered steps:

**view → cart → purchase**

(`wishlist` exists in the data but is **not** part of this funnel.)

## Activation

A user is **activated** if they have a **`purchase`** event **within 24 hours** of their **first event** (any type), by `event_timestamp`.

## Cohort

Cohort assignment uses each user’s **first event date** (calendar date of the earliest `event_timestamp` for that user).

## Funnel level

**User-level** (aggregate each user’s journey across all products), **not** product-level.
