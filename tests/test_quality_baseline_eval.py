import importlib.util
import sys
from pathlib import Path


def _load_quality_eval_module():
    module_path = Path(__file__).with_name("quality_baseline_eval.py")
    spec = importlib.util.spec_from_file_location("quality_baseline_eval", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_json_object_accepts_fenced_json():
    quality_eval = _load_quality_eval_module()

    parsed = quality_eval._parse_json_object(
        """```json
        {"ranking_ok": true, "reason": "ok"}
        ```"""
    )

    assert parsed == {"ranking_ok": True, "reason": "ok"}


def test_llm_judge_preflight_rejects_missing_default_key(monkeypatch):
    quality_eval = _load_quality_eval_module()

    from app.config import settings

    monkeypatch.setattr(settings.ai, "bailian_api_key", "")

    error = quality_eval._llm_judge_preflight_error(None)

    assert error
    assert "AI_BAILIAN_API_KEY" in error


def test_generate_comparison_tracks_rate_and_failure_changes():
    quality_eval = _load_quality_eval_module()
    previous = {
        "run_id": "previous",
        "pass_rate": 80.0,
        "passed": 8,
        "total_checks": 10,
        "all_failures": ["[F_old] fixed", "[F_same] unchanged"],
        "quality_lines": {
            "followup_quality": {"rate": 70.0, "failures": 2},
            "scoring_quality": {"rate": 80.0, "failures": 1},
        },
    }
    current = {
        "run_id": "current",
        "pass_rate": 90.0,
        "passed": 9,
        "total_checks": 10,
        "all_failures": ["[F_same] unchanged", "[F_new] regression"],
        "quality_lines": {
            "followup_quality": {"rate": 90.0, "failures": 1},
            "scoring_quality": {"rate": 80.0, "failures": 1},
        },
    }

    comparison = quality_eval.generate_comparison(previous, current)

    assert comparison["pass_rate_delta"] == 10.0
    assert comparison["new_failures"] == ["[F_new] regression"]
    assert comparison["fixed_failures"] == ["[F_old] fixed"]
    assert comparison["unchanged_failures"] == ["[F_same] unchanged"]
    assert comparison["quality_line_deltas"]["followup_quality"]["delta"] == 20.0


def test_write_comparison_md_marks_empty_sections(tmp_path):
    quality_eval = _load_quality_eval_module()
    comparison = quality_eval.generate_comparison(
        {
            "run_id": "same-old",
            "pass_rate": 100.0,
            "passed": 10,
            "total_checks": 10,
            "all_failures": [],
            "quality_lines": {},
        },
        {
            "run_id": "same-new",
            "pass_rate": 100.0,
            "passed": 10,
            "total_checks": 10,
            "all_failures": [],
            "quality_lines": {},
        },
    )

    quality_eval.write_comparison_md(comparison, tmp_path)

    content = (tmp_path / "comparison.md").read_text()
    assert "100.0% -> 100.0%" in content
    assert "## 新增失败" in content
    assert "- 无" in content
