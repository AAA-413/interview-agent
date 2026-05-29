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
