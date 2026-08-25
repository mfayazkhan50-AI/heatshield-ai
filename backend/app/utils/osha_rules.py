"""
osha_rules.py
=============
Pure Python OSHA / NWS heat-index calculations.

No I/O, no framework dependencies — safe to unit test in isolation.
"""

from __future__ import annotations


def compute_heat_index_f(temp_f: float, rh_pct: float) -> float:
    """
    NWS Rothfusz regression for heat index.

    Falls back to the simplified formula when the calculated heat index
    is below 80°F.
    """

    T, R = temp_f, rh_pct

    simple_hi = 0.5 * (
        T
        + 61.0
        + ((T - 68.0) * 1.2)
        + (R * 0.094)
    )

    if simple_hi < 80.0:
        return round(simple_hi, 1)

    hi = (
        -42.379
        + 2.04901523 * T
        + 10.14333127 * R
        - 0.22475541 * T * R
        - 0.00683783 * T * T
        - 0.05481717 * R * R
        + 0.00122874 * T * T * R
        + 0.00085282 * T * R * R
        - 0.00000199 * T * T * R * R
    )

    if R < 13 and 80 <= T <= 112:
        hi -= (
            ((13 - R) / 4)
            * (
                (17 - abs(T - 95.0)) / 17
            )
            ** 0.5
        )

    elif R > 85 and 80 <= T <= 87:
        hi += (
            ((R - 85) / 10)
            * ((87 - T) / 5)
        )

    return round(hi, 1)


def classify_risk(heat_index_f: float) -> str:
    """Map a heat index reading onto OSHA-aligned risk bins."""

    if heat_index_f < 80:
        return "Low"

    if heat_index_f < 91:
        return "Caution"

    if heat_index_f < 103:
        return "Warning"

    if heat_index_f < 125:
        return "Danger"

    return "Extreme Danger"
