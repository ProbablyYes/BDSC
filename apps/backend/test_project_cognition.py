from app.services.project_cognition import compose_oriented_prompt, ensure_project_cognition, resolve_competition_rubric
from app.services.track_inference import merge_track_vector


def test_compose_oriented_prompt_includes_expected_layers():
    prompt = compose_oriented_prompt(
        role="coach",
        track_vector={"innov_venture": 0.72, "biz_public": 0.66},
        stage="structured",
        comp_type="internet_plus",
    )
    assert "角色基调" in prompt
    assert "强创业" in prompt
    assert "强公益" in prompt
    assert "原型期" in prompt
    assert "互联网+" in prompt


def test_resolve_competition_rubric_normalizes_weights():
    resolved = resolve_competition_rubric(
        "challenge_cup",
        {"innov_venture": -0.8, "biz_public": 0.2},
        "validated",
    )
    weights = resolved["weights"]
    assert weights["innovation"] > weights["business_model"]
    assert round(sum(weights.values()), 2) == 100.0


def test_merge_track_vector_applies_confidence_gating():
    state = ensure_project_cognition({})
    merged, snapshot = merge_track_vector(
        state,
        {
            "track_vector": {"innov_venture": 0.9, "biz_public": -0.6},
            "confidence": 0.3,
            "source_mix": {"message": 1.0},
            "reason": "low confidence",
            "evidence": ["signal"],
        },
        source="inferred",
    )
    assert abs(merged["track_vector"]["innov_venture"]) < 0.2
    assert snapshot["confidence"] == 0.3
    assert merged["track_history"]
