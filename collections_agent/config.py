"""Policy thresholds. Every number the engine uses to make a call lives here,
so a controller can review (and change) collections policy in one place."""

# --- Aging buckets: (label, min days past due, max days past due) -------------
BUCKETS = [
    ("current", None, 0),
    ("1-30", 1, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
]

# --- Email tone tiers, keyed by the oldest undisputed past-due invoice -------
# (tier id, min days past due, max days past due, display name)
TIERS = [
    ("friendly", 1, 30, "Friendly reminder"),
    ("firm", 31, 60, "Firm follow-up"),
    ("escalation", 61, 90, "Escalation to account owner / finance leader"),
    ("final", 91, None, "Final notice / credit hold recommendation"),
]

# --- Payment-behavior trend ---------------------------------------------------
TREND_RECENT_WINDOW_DAYS = 90       # payments received in the last 90 days = "recent"
TREND_LOOKBACK_DAYS = 365           # baseline = payments 91-365 days before as-of
TREND_MIN_BASELINE_PAYMENTS = 3     # fewer than this -> "insufficient history"
DETERIORATING_DELTA_DAYS = 10       # recent avg days late - baseline avg >= this -> flag
IMPROVING_DELTA_DAYS = -10
CHRONIC_LATE_DAYS = 30              # recent avg days late >= this (and not deteriorating)

# --- Risk score weights (sum = 100) -------------------------------------------
RISK_WEIGHTS = {
    "aging_severity": 30,   # share of open balance 61+ days past due
    "max_days_past_due": 20,  # oldest undisputed past-due item, capped at 120 days
    "trend": 20,            # deterioration delta, capped at 30 days
    "credit_utilization": 15,  # open AR / credit limit, capped at 150%
    "chronic_lateness": 10,  # recent avg days late, capped at 60 days
    "open_dispute": 5,      # any open dispute
}
RISK_BANDS = [("High", 45), ("Medium", 25), ("Low", 0)]

# --- Hold recommendation ------------------------------------------------------
HOLD_UTILIZATION = 1.00             # over 100% of credit limit ...
HOLD_MIN_DAYS_PAST_DUE = 61         # ... and something 61+ days past due

# --- Expected-loss reserve rates by bucket ------------------------------------
# Used for the expected-loss metric AND to rank the worklist (priority value).
RESERVE_RATES = {"current": 0.00, "1-30": 0.02, "31-60": 0.10, "61-90": 0.25, "90+": 0.50}

# --- DSO -----------------------------------------------------------------------
DSO_SALES_WINDOW_DAYS = 90
DSO_TREND_MONTHS = 6
