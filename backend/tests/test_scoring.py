"""
test_scoring.py
===============
Regression tests for the deterministic Response-Gap engine.

Contract under test:
    R = 0.40·Heat_Exposure + 0.35·Vulnerability_Index + 0.25·Resource_Deficit

The engine is the anti-hallucination guarantee of the product: these tests
pin its math so any drift is a loud failure.
"""

from __future__ import annotations

import pytest

from app.engine.actions import build_tactical_actions
from app.engine.scoring import (
    DISPATCH_THRESHOLD,
    OPERATION_PROFILES,
    WEIGHT_HEAT_EXPOSURE,
    WEIGHT_RESOURCE_DEFICIT,
    WEIGHT_VULNERABILITY,
    clamp_score,
    compute_heat_exposure,
    compute_resource_deficit,
    compute_vulnerability,
    is_dispatch_eligible,
    linear_ramp,
    osha_bin_for_heat_index,
    score_response_gap,
    tier_for_score,
)


BASE_INPUTS = dict(
    peak_temp_f=105.0,
    relative_humidity_pct=20.0,
    heat_index_f=104.0,
    consecutive_hours_above_40c=2.0,
    svi=0.6,
    population_density_per_km2=1200,
    cooling_center_buffer_km=3.0,
    shade_coverage_pct=25.0,
    operation="construction",
)


# ---------------------------------------------------------------------------
# Weight integrity — the formula the UI renders must match the engine
# ---------------------------------------------------------------------------

class TestFormulaWeights:
    def test_weights_sum_to_one(self):
        assert (
            WEIGHT_HEAT_EXPOSURE
            + WEIGHT_VULNERABILITY
            + WEIGHT_RESOURCE_DEFICIT
            == pytest.approx(1.0)
        )

    def test_canonical_weight_values(self):
        assert WEIGHT_HEAT_EXPOSURE == 0.40
        assert WEIGHT_VULNERABILITY == 0.35
        assert WEIGHT_RESOURCE_DEFICIT == 0.25

    def test_dispatch_threshold_is_seven(self):
        assert DISPATCH_THRESHOLD == 7.0


# ---------------------------------------------------------------------------
# Hand-computed golden case (verified by hand from the docstring anchors)
# ---------------------------------------------------------------------------

class TestGoldenCase:
    def test_hand_computed_breakdown(self):
        """
        Inputs: HI=104°F, operation=delivery.

        HI sub:      ramp(104, 91, 124) = 10*(13/33) = 3.94
        PEAK sub:    ramp(105+0, 95, 118) = 10*(10/23) = 4.35
        DURATION:    delivery scale 0.85 → 2*0.85 = 1.70 h
                     ramp(1.7, 0, 6) = 2.83
        E = .45*3.94 + .35*4.35 + .20*2.83 = 3.86

        V: svi 0.60 → 6.00 ; density 1200 → ramp(1200,250,4000)=2.53
           V = .70*6 + .30*2.53 = 4.96

        D: cooling 3km → ramp(3, 0, 5) = 6.00 ; shade deficit 75 → 7.50
           D = .60*6 + .40*7.5 = 6.60

        R = .40*3.86 + .35*4.96 + .25*6.60 ≈ 4.93 → ELEVATED
        """
        result = score_response_gap(
            **{**BASE_INPUTS, "operation": "delivery"}
        )

        e, v, d = result["components"]

        assert e["value"] == pytest.approx(3.86, abs=0.02)
        assert v["value"] == pytest.approx(4.96, abs=0.02)
        assert d["value"] == pytest.approx(6.60, abs=0.01)
        assert result["response_gap"] == pytest.approx(4.93, abs=0.05)

        # Contributions must equal weight × value (stored rounded to 2dp).
        for c in result["components"]:
            assert c["contribution"] == pytest.approx(
                c["weight"] * c["value"], abs=0.005
            )

        total = sum(c["contribution"] for c in result["components"])
        assert result["response_gap"] == pytest.approx(total, abs=0.05)


# ---------------------------------------------------------------------------
# Monotonicity — more heat can never lower the score
# ---------------------------------------------------------------------------

class TestMonotonicity:
    def test_hotter_peak_never_lower_score(self):
        base = score_response_gap(**BASE_INPUTS)

        hotter = score_response_gap(
            **{**BASE_INPUTS, "peak_temp_f": 115.0, "heat_index_f": 118.0}
        )

        assert hotter["response_gap"] > base["response_gap"]

    def test_longer_sustained_exposure_raises_score(self):
        base = score_response_gap(**BASE_INPUTS)
        longer = score_response_gap(**{**BASE_INPUTS, "consecutive_hours_above_40c": 8.0})

        assert longer["response_gap"] > base["response_gap"]

    def test_farther_cooling_center_raises_score(self):
        """REGRESSION GUARD: access deficit must RISE with distance."""
        close = score_response_gap(**{**BASE_INPUTS, "cooling_center_buffer_km": 0.2})
        far = score_response_gap(**{**BASE_INPUTS, "cooling_center_buffer_km": 4.9})

        assert far["response_gap"] > close["response_gap"]

    def test_more_shade_lowers_score(self):
        shaded = score_response_gap(**{**BASE_INPUTS, "shade_coverage_pct": 90.0})
        bare = score_response_gap(**{**BASE_INPUTS, "shade_coverage_pct": 0.0})

        assert bare["response_gap"] > shaded["response_gap"]


# ---------------------------------------------------------------------------
# Clamping + normalization primitives
# ---------------------------------------------------------------------------

class TestClamps:
    def test_scores_bounded_zero_ten(self):
        extreme = score_response_gap(
            **{
                **BASE_INPUTS,
                "peak_temp_f": 200.0,
                "heat_index_f": 300.0,
                "consecutive_hours_above_40c": 99.0,
                "svi": 1.0,
                "cooling_center_buffer_km": 100.0,
                "shade_coverage_pct": 0.0,
            }
        )
        assert 0.0 <= extreme["response_gap"] <= 10.0

        mild = score_response_gap(
            **{
                **BASE_INPUTS,
                "peak_temp_f": 40.0,
                "heat_index_f": 30.0,
                "consecutive_hours_above_40c": 0.0,
                "svi": 0.0,
                "shade_coverage_pct": 100.0,
            }
        )
        assert mild["response_gap"] >= 0.0

    def test_clamp_score_helper(self):
        assert clamp_score(-5) == 0.0
        assert clamp_score(11) == 10.0
        assert clamp_score(4.2) == 4.2

    def test_linear_ramp_anchors(self):
        assert linear_ramp(0, 0, 10) == 0.0
        assert linear_ramp(10, 0, 10) == 10.0
        assert linear_ramp(5, 0, 10) == 5.0
        assert linear_ramp(-1, 0, 10) == 0.0
        assert linear_ramp(20, 0, 10) == 10.0


# ---------------------------------------------------------------------------
# Tier mapping + dispatch gate
# ---------------------------------------------------------------------------

class TestTiers:
    @pytest.mark.parametrize(
        ("score", "tier"),
        [
            (0.0, "NORMAL"),
            (2.99, "NORMAL"),
            (3.0, "ELEVATED"),
            (5.49, "ELEVATED"),
            (5.5, "HIGH"),
            (6.99, "HIGH"),
            (7.0, "CRITICAL"),
            (10.0, "CRITICAL"),
        ],
    )
    def test_tier_boundaries(self, score, tier):
        assert tier_for_score(score) == tier

    def test_dispatch_gate_strictly_at_seven(self):
        assert not is_dispatch_eligible(6.999)
        assert is_dispatch_eligible(7.0)

    def test_critical_scenario_reaches_dispatch(self):
        """Thermal, CA-style scenario must cross the autonomous gate."""
        critical = score_response_gap(
            **{
                **BASE_INPUTS,
                "peak_temp_f": 117.0,
                "heat_index_f": 114.0,
                "consecutive_hours_above_40c": 5.0,
                "svi": 0.97,
                "population_density_per_km2": 420,
                "cooling_center_buffer_km": 6.8,
                "shade_coverage_pct": 8.0,
                "operation": "roadwork",
            }
        )
        assert critical["risk_tier"] == "CRITICAL"
        assert critical["dispatch_eligible"] is True


# ---------------------------------------------------------------------------
# Operation context modifiers are visible and directional
# ---------------------------------------------------------------------------

class TestOperationModifiers:
    def test_profiles_exist_for_all_operations(self):
        assert set(OPERATION_PROFILES) == {"construction", "delivery", "roadwork"}

    def test_roadwork_radiant_offset_raises_exposure(self):
        roadwork = compute_heat_exposure(
            peak_temp_f=108.0,
            relative_humidity_pct=15.0,
            consecutive_hours_above_40c=3.0,
            heat_index_f=112.0,
            operation="roadwork",
        )
        delivery = compute_heat_exposure(
            peak_temp_f=108.0,
            relative_humidity_pct=15.0,
            consecutive_hours_above_40c=3.0,
            heat_index_f=112.0,
            operation="delivery",
        )

        assert roadwork["value"] > delivery["value"]
        assert roadwork["effective_inputs"]["radiant_offset_f"] == 4.0
        assert delivery["effective_inputs"]["radiant_offset_f"] == 0.0

    def test_operation_recorded_in_raw_inputs(self):
        out = score_response_gap(**{**BASE_INPUTS, "operation": "roadwork"})
        assert out["raw_inputs"]["operation"] == "roadwork"


# ---------------------------------------------------------------------------
# Determinism — same inputs, byte-identical artifact (no hidden state)
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_repeat_calls_identical(self):
        a = score_response_gap(**BASE_INPUTS)
        b = score_response_gap(**BASE_INPUTS)

        assert a == b

    def test_formula_substitution_matches_components(self):
        out = score_response_gap(**BASE_INPUTS)
        e, v, d = out["components"]

        expected = (
            f"R = {e['weight']:.2f}×{e['value']:.2f} "
            f"+ {v['weight']:.2f}×{v['value']:.2f} "
            f"+ {d['weight']:.2f}×{d['value']:.2f} = "
            f"{out['response_gap']:.2f}"
        )
        assert out["formula_substitution"] == expected


# ---------------------------------------------------------------------------
# OSHA bin mapping stays orthogonal but stable
# ---------------------------------------------------------------------------

class TestOSHABins:
    @pytest.mark.parametrize(
        ("hi", "expected"),
        [
            (79.9, "Low"),
            (80.0, "Caution"),
            (90.9, "Caution"),
            (91.0, "Warning"),
            (102.9, "Warning"),
            (103.0, "Danger"),
            (124.9, "Danger"),
            (125.0, "Extreme Danger"),
        ],
    )
    def test_bin_boundaries(self, hi, expected):
        assert osha_bin_for_heat_index(hi) == expected


# ---------------------------------------------------------------------------
# Deterministic tactical actions (numbered directives)
# ---------------------------------------------------------------------------

class TestTacticalActions:
    def _breakdown(self, tier):
        return {
            "risk_tier": tier,
            "raw_inputs": {
                "shade_coverage_pct": 12.0,
                "cooling_center_buffer_km": 4.0,
            },
        }

    def test_normal_tier_no_actions(self):
        actions = build_tactical_actions(self._breakdown("NORMAL"), "Low")
        assert actions == []

    def test_actions_numbered_and_ordered(self):
        actions = build_tactical_actions(self._breakdown("CRITICAL"), "Extreme Danger")

        ids = [a["id"] for a in actions]
        assert ids[0] == "01"
        assert ids == sorted(ids)
        assert len(ids) >= 5

    def test_high_tier_is_subset_of_critical(self):
        high = build_tactical_actions(self._breakdown("HIGH"), "Danger")
        critical = build_tactical_actions(self._breakdown("CRITICAL"), "Extreme Danger")

        assert {a["id"] for a in high} < {a["id"] for a in critical}

    def test_every_action_has_required_fields(self):
        for action in build_tactical_actions(self._breakdown("CRITICAL"), "Extreme Danger"):
            assert action["title"]
            assert action["detail"]
            assert action["horizon"]
            assert action["source"]
