"""Shared pure helpers (no I/O, no framework dependencies)."""

from app.utils.clock import utc_now_iso
from app.utils.osha_rules import classify_risk, compute_heat_index_f

__all__ = ["utc_now_iso", "compute_heat_index_f", "classify_risk"]
