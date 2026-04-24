from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings


_COGNITION_CONFIG_DIR = settings.workspace_root / "apps" / "backend" / "config"
_TRACK_SPECTRUM_PATH = _COGNITION_CONFIG_DIR / "track_spectrum.json"
_COMPETITION_TEMPLATES_PATH = _COGNITION_CONFIG_DIR / "competition_templates.json"

_INTENSITY_LIGHT_THRESHOLD = 0.2
_INTENSITY_STRONG_THRESHOLD = 0.5


def _safe_read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return default
        data = json.loads(raw)
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


@lru_cache(maxsize=1)
def load_track_spectrum() -> dict[str, Any]:
    return _safe_read_json(_TRACK_SPECTRUM_PATH, {})


@lru_cache(maxsize=1)
def load_competition_templates() -> dict[str, Any]:
    return _safe_read_json(_COMPETITION_TEMPLATES_PATH, {})


def clear_cognition_cache() -> None:
    load_track_spectrum.cache_clear()
    load_competition_templates.cache_clear()


def default_track_vector() -> dict[str, Any]:
    return {
        "innov_venture": 0.0,
        "biz_public": 0.0,
        "source": "system",
        "updated_at": "",
    }


def default_track_inference_meta() -> dict[str, Any]:
    return {
        "confidence": 0.0,
        "source_mix": {},
        "last_reason": "",
        "last_evidence": [],
        "streaks": {
            "innov_venture": {"direction": "neutral", "count": 0},
            "biz_public": {"direction": "neutral", "count": 0},
        },
    }


def ensure_project_cognition(project_state: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(project_state or {})
    track_vector = base.get("track_vector")
    if not isinstance(track_vector, dict):
        track_vector = default_track_vector()
    else:
        merged = default_track_vector()
        merged.update(track_vector)
        track_vector = merged
    base["track_vector"] = track_vector

    stage = str(base.get("project_stage_v2") or "").strip()
    base["project_stage_v2"] = stage or "structured"

    history = base.get("track_history")
    base["track_history"] = history if isinstance(history, list) else []

    meta = base.get("track_inference_meta")
    if not isinstance(meta, dict):
        meta = default_track_inference_meta()
    else:
        merged_meta = default_track_inference_meta()
        merged_meta.update(meta)
        if not isinstance(merged_meta.get("streaks"), dict):
            merged_meta["streaks"] = default_track_inference_meta()["streaks"]
        for axis in ("innov_venture", "biz_public"):
            axis_streak = merged_meta["streaks"].get(axis)
            if not isinstance(axis_streak, dict):
                merged_meta["streaks"][axis] = {"direction": "neutral", "count": 0}
                continue
            merged_meta["streaks"][axis] = {
                "direction": str(axis_streak.get("direction") or "neutral"),
                "count": int(axis_streak.get("count") or 0),
            }
        meta = merged_meta
    base["track_inference_meta"] = meta
    return base


def clamp_track_value(value: Any) -> float:
    try:
        num = float(value or 0)
    except Exception:
        return 0.0
    return max(-1.0, min(1.0, round(num, 4)))


def normalize_track_vector(track_vector: dict[str, Any] | None) -> dict[str, Any]:
    merged = default_track_vector()
    if isinstance(track_vector, dict):
        merged.update(track_vector)
    merged["innov_venture"] = clamp_track_value(merged.get("innov_venture"))
    merged["biz_public"] = clamp_track_value(merged.get("biz_public"))
    merged["source"] = str(merged.get("source") or "system")
    merged["updated_at"] = str(merged.get("updated_at") or "")
    return merged


def stage_label(stage: str) -> str:
    return {
        "idea": "想法期",
        "structured": "原型期",
        "validated": "验证期",
        "scale": "规模化",
        "document": "验证期",
    }.get(str(stage or "").strip(), "原型期")


def describe_track_vector(track_vector: dict[str, Any] | None) -> dict[str, str]:
    tv = normalize_track_vector(track_vector)
    innov_venture = float(tv["innov_venture"])
    biz_public = float(tv["biz_public"])

    def _axis_desc(value: float, negative: str, positive: str) -> str:
        mag = abs(value)
        if mag < 0.2:
            return f"中性{negative}/{positive}"
        side = negative if value < 0 else positive
        return f"偏{side} {int(round(mag * 100))}%"

    return {
        "innov_venture_label": _axis_desc(innov_venture, "创新", "创业"),
        "biz_public_label": _axis_desc(biz_public, "商业", "公益"),
        "summary": f"{_axis_desc(innov_venture, '创新', '创业')} · {_axis_desc(biz_public, '商业', '公益')}",
    }


def _endpoint_hit(value: float, negative_key: str, positive_key: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    mag = abs(value)
    if mag < _INTENSITY_LIGHT_THRESHOLD:
        return hits
    intensity = "strong" if mag >= _INTENSITY_STRONG_THRESHOLD else "light"
    endpoint = negative_key if value < 0 else positive_key
    hits.append({"endpoint": endpoint, "intensity": intensity, "magnitude": round(mag, 4)})
    return hits


def resolve_endpoint_hits(track_vector: dict[str, Any] | None) -> list[dict[str, Any]]:
    tv = normalize_track_vector(track_vector)
    hits: list[dict[str, Any]] = []
    hits.extend(_endpoint_hit(float(tv["innov_venture"]), "innov", "venture"))
    hits.extend(_endpoint_hit(float(tv["biz_public"]), "biz", "public"))
    return hits


def _get_nested_text(source: dict[str, Any] | None, *keys: str) -> str:
    current: Any = source or {}
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "").strip()


def _competition_prompt_fragment(comp_type: str, role: str) -> str:
    templates = load_competition_templates()
    comp = templates.get(comp_type, {}) if isinstance(templates, dict) else {}
    if not isinstance(comp, dict):
        return ""
    prompts = comp.get("prompt_fragments") or {}
    if not isinstance(prompts, dict):
        return ""
    return str(prompts.get(role) or "").strip()


def _conflict_keys(track_vector: dict[str, Any] | None) -> list[str]:
    tv = normalize_track_vector(track_vector)
    keys: list[str] = []
    if float(tv["innov_venture"]) >= _INTENSITY_STRONG_THRESHOLD and float(tv["biz_public"]) >= _INTENSITY_STRONG_THRESHOLD:
        keys.append("venture_public")
    if abs(float(tv["innov_venture"])) >= _INTENSITY_STRONG_THRESHOLD and abs(float(tv["biz_public"])) >= _INTENSITY_STRONG_THRESHOLD:
        if float(tv["innov_venture"]) < 0 and float(tv["biz_public"]) <= -_INTENSITY_STRONG_THRESHOLD:
            keys.append("innov_biz")
    if abs(float(tv["innov_venture"])) >= _INTENSITY_STRONG_THRESHOLD:
        keys.append("innov_venture")
    return list(dict.fromkeys(keys))


def _modifier_keys(track_vector: dict[str, Any] | None, stage: str) -> list[str]:
    tv = normalize_track_vector(track_vector)
    keys: list[str] = []
    if float(tv["innov_venture"]) <= -_INTENSITY_STRONG_THRESHOLD and stage == "validated":
        keys.append("innov_validated")
    if float(tv["biz_public"]) >= _INTENSITY_STRONG_THRESHOLD and stage == "scale":
        keys.append("public_scale")
    if float(tv["innov_venture"]) >= _INTENSITY_STRONG_THRESHOLD and stage == "idea":
        keys.append("venture_idea")
    return keys


def compose_oriented_prompt(
    role: str,
    track_vector: dict[str, Any] | None,
    stage: str,
    comp_type: str = "",
) -> str:
    cfg = load_track_spectrum()
    if not isinstance(cfg, dict):
        return ""
    stage_key = str(stage or "").strip() or "structured"
    parts: list[str] = []

    base = _get_nested_text(cfg, "role_base", role)
    if base:
        parts.append(base)

    for hit in resolve_endpoint_hits(track_vector):
        endpoint = str(hit.get("endpoint") or "")
        intensity = str(hit.get("intensity") or "light")
        frag = _get_nested_text(cfg, "spectrum_fragments", endpoint, intensity, role)
        if frag:
            parts.append(frag)

    stage_frag = _get_nested_text(cfg, "stage_fragments", stage_key, role)
    if stage_frag:
        parts.append(stage_frag)

    for conflict_key in _conflict_keys(track_vector):
        frag = _get_nested_text(cfg, "conflict_fragments", conflict_key, role)
        if frag:
            parts.append(frag)

    comp_frag = _competition_prompt_fragment(comp_type, role)
    if comp_frag:
        parts.append(comp_frag)

    for modifier_key in _modifier_keys(track_vector, stage_key):
        frag = _get_nested_text(cfg, "modifier_fragments", modifier_key, role)
        if frag:
            parts.append(frag)

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = part.replace(" ", "").replace("\n", "")
        if part and normalized not in seen:
            seen.add(normalized)
            deduped.append(part)
    return "\n".join(deduped).strip()


def _bucket_match(value: float, bucket: dict[str, Any]) -> bool:
    low = float(bucket.get("min", -1.0))
    high = float(bucket.get("max", 1.0))
    include_high = bool(bucket.get("include_max", True))
    if value < low:
        return False
    if include_high:
        return value <= high
    return value < high


def _apply_weight_delta(weights: dict[str, float], delta: dict[str, Any] | None) -> None:
    if not isinstance(delta, dict):
        return
    for key, value in delta.items():
        try:
            weights[key] = max(0.0, weights.get(key, 0.0) + float(value or 0))
        except Exception:
            continue


def resolve_competition_rubric(
    comp_type: str,
    track_vector: dict[str, Any] | None,
    stage: str,
) -> dict[str, Any]:
    templates = load_competition_templates()
    comp = templates.get(comp_type, {}) if isinstance(templates, dict) else {}
    if not isinstance(comp, dict):
        return {"weights": {}, "band_descriptors": {}, "judge_focus_notes": {}}

    base_weights = comp.get("base_weights") or {}
    weights: dict[str, float] = {}
    for key, value in base_weights.items():
        try:
            weights[str(key)] = float(value or 0)
        except Exception:
            continue

    tv = normalize_track_vector(track_vector)
    bucket_rules = comp.get("bucket_rules") or {}
    if isinstance(bucket_rules, dict):
        for axis, buckets in bucket_rules.items():
            if axis not in {"innov_venture", "biz_public"} or not isinstance(buckets, list):
                continue
            axis_value = float(tv.get(axis, 0.0) or 0.0)
            for bucket in buckets:
                if isinstance(bucket, dict) and _bucket_match(axis_value, bucket):
                    _apply_weight_delta(weights, bucket.get("delta"))
                    break

    stage_adjustments = comp.get("stage_adjustments") or {}
    if isinstance(stage_adjustments, dict):
        _apply_weight_delta(weights, stage_adjustments.get(stage) or stage_adjustments.get("structured"))

    track_adjustments = comp.get("track_adjustments") or {}
    if isinstance(track_adjustments, dict):
        for hit in resolve_endpoint_hits(tv):
            endpoint = str(hit.get("endpoint") or "")
            _apply_weight_delta(weights, track_adjustments.get(endpoint))

    total = sum(max(v, 0.0) for v in weights.values()) or 1.0
    normalized = {key: round((max(value, 0.0) / total) * 100, 2) for key, value in weights.items()}
    return {
        "weights": normalized,
        "band_descriptors": comp.get("band_descriptors") or {},
        "judge_focus_notes": comp.get("judge_focus_notes") or {},
        "item_map": comp.get("item_map") or {},
    }


def score_to_band(score: float) -> str:
    if score >= 8.7:
        return "A"
    if score >= 7.6:
        return "A-"
    if score >= 6.8:
        return "B+"
    if score >= 6.0:
        return "B"
    if score >= 5.0:
        return "B-"
    if score >= 4.0:
        return "C"
    return "C-"
