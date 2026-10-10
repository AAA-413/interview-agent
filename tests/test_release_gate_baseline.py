"""PR #11 review round 1：Release Gate 的 fail-closed 契约与脱敏契约。

背景
----
原实现只有一条判据：``passed = completed.returncode == 0``。而
``tests/quality_baseline_eval.py`` 只在 pass rate < 75% 时才 ``sys.exit(1)``，
于是：

```text
原来：105/107 → exit 0 → PASS
回归： 85/107 → exit 0 → 仍然 PASS     ← 质量掉了 20 个检查点，门禁照样放行
空转：无输出  → exit 0 → 仍然 PASS     ← 评测根本没跑，门禁照样放行
```

这与 Release Gate 的定位直接冲突。本文件把新契约钉死：

```text
每个 eval 必须同时满足两件独立的事
  1. returncode == 0
  2. 输出里存在契约内的正式 summary 行，且 >= 冻结基线（scripts/release_baseline.json）

NO_SUMMARY / MALFORMED_SUMMARY / INVALID_SUMMARY / UNKNOWN_CONTRACT / BELOW_BASELINE
一律 → FINAL: FAIL
```

全部用 mock subprocess，**不真的跑三套 eval**（真实执行属于 gate 自己的职责）。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import scripts.interview_release_gate as gate_module

QUALITY = "tests/quality_baseline_eval.py"
CONVERSATION = "tests/conversation_pipeline_eval.py"
GROUNDING = "tests/knowledge_grounding_eval.py"

#: 冻结基线对应的「正常」输出
BASELINE_OUTPUTS: dict[str, str] = {
    QUALITY: "Overall: 105/107 passed (98.1%)\n",
    CONVERSATION: "Conversation Pipeline Contract Eval: 19/19 passed\n",
    GROUNDING: "Knowledge Grounding Eval: 27/27 passed\n",
}


def _install_run(monkeypatch, outputs: dict[str, str], *, codes: dict[str, int] | None = None) -> None:
    """用一个可控的 subprocess.run 替身替换真实执行。"""
    exit_codes = codes or {}

    def _fake_run(cmd, **_kwargs):
        script = cmd[1]
        return subprocess.CompletedProcess(
            cmd,
            exit_codes.get(script, 0),
            stdout=outputs.get(script, ""),
            stderr="",
        )

    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)


def _run_gate(monkeypatch, capsys, outputs: dict[str, str], *, codes: dict[str, int] | None = None):
    _install_run(monkeypatch, outputs, codes=codes)
    exit_code = gate_module.main(list(gate_module.EVAL_SCRIPTS))
    return exit_code, capsys.readouterr().out


# ---------------------------------------------------------------------------
# 冻结基线本身
# ---------------------------------------------------------------------------


def test_baseline_file_is_frozen_at_expected_values():
    """基线数值是**被显式冻结**的：任何调低都会让这个测试变红。

    这是「不允许调低基线来制造 PASS」的可执行约束 —— 想改就必须改这个测试，
    于是改动一定会出现在 PR diff 里被 review 看到。
    """
    config = gate_module.load_baseline()

    assert config.error is None, config.error
    assert set(config.baselines) == set(gate_module.EVAL_SCRIPTS)

    expected = {
        QUALITY: (105, 107, 2),
        CONVERSATION: (19, 19, 0),
        GROUNDING: (27, 27, 0),
    }
    for script, (min_passed, min_total, max_failed) in expected.items():
        entry = config.baselines[script]
        assert (entry.min_passed, entry.min_total, entry.max_failed) == (min_passed, min_total, max_failed), (
            f"{script} 的冻结基线被改动：{(entry.min_passed, entry.min_total, entry.max_failed)}"
        )


def test_every_eval_script_has_spec_and_baseline_entry():
    """EVAL_SCRIPTS / EVAL_SPECS / release_baseline.json 三者不允许漂移。"""
    config = gate_module.load_baseline()

    assert set(config.baselines) == set(gate_module.EVAL_SCRIPTS)
    assert set(gate_module.SPEC_BY_SCRIPT) == set(gate_module.EVAL_SCRIPTS)
    assert not (set(gate_module.EVAL_SCRIPTS) - set(config.baselines))


def test_baseline_missing_file_is_an_error(tmp_path: Path):
    config = gate_module.load_baseline(tmp_path / "nope.json")
    assert config.error is not None
    assert "不存在" in config.error


def test_baseline_malformed_file_is_an_error(tmp_path: Path):
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert gate_module.load_baseline(broken).error is not None


def test_gate_fails_when_baseline_cannot_be_loaded(monkeypatch, capsys, tmp_path: Path):
    """基线读不到 = 门禁本身不可信 → 必须 FAIL，绝不静默放行。"""
    monkeypatch.setattr(gate_module, "BASELINE_PATH", tmp_path / "missing.json")

    exit_code = gate_module.main([QUALITY])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "FINAL: FAIL" in out
    assert "baseline" in out


# ---------------------------------------------------------------------------
# 回归矩阵（review 点名要求）
# ---------------------------------------------------------------------------


def test_gate_passes_at_frozen_baseline(monkeypatch, capsys):
    """105/107 + 19/19 + 27/27，全部 exit 0 → PASS。"""
    exit_code, out = _run_gate(monkeypatch, capsys, BASELINE_OUTPUTS)

    assert exit_code == 0
    assert "FINAL: PASS" in out
    assert "quality_baseline_eval" in out
    assert "105/107" in out


def test_gate_fails_when_quality_baseline_degrades_to_85_of_107(monkeypatch, capsys):
    """85/107 但 exit 0 → FAIL（这就是原实现的 fail-open 漏洞）。"""
    outputs = {**BASELINE_OUTPUTS, QUALITY: "Overall: 85/107 passed (79.4%)\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 1
    assert "FINAL: FAIL" in out
    assert "BELOW_BASELINE" in out
    assert "85/107" in out


def test_gate_fails_on_empty_output(monkeypatch, capsys):
    """空转（没有任何输出）但 exit 0 → FAIL。"""
    outputs = {**BASELINE_OUTPUTS, QUALITY: ""}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 1
    assert "FINAL: FAIL" in out
    assert "NO_SUMMARY" in out


def test_gate_fails_on_malformed_summary(monkeypatch, capsys):
    """有锚点但格式不符（例如改成了 `105 of 107`）→ FAIL。"""
    outputs = {**BASELINE_OUTPUTS, QUALITY: "Overall: 105 of 107 passed\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 1
    assert "MALFORMED_SUMMARY" in out


def test_gate_fails_when_conversation_eval_drops_one_check(monkeypatch, capsys):
    """18/19 但 exit 0 → FAIL。"""
    outputs = {**BASELINE_OUTPUTS, CONVERSATION: "Conversation Pipeline Contract Eval: 18/19 passed\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 1
    assert "BELOW_BASELINE" in out
    assert "18/19" in out


def test_gate_passes_when_grounding_is_exactly_at_baseline(monkeypatch, capsys):
    """27/27 但 exit 0 → PASS（基线是下限，等于基线算通过）。"""
    exit_code, out = _run_gate(monkeypatch, capsys, BASELINE_OUTPUTS)

    assert exit_code == 0
    assert "Knowledge Grounding Eval" not in out or "27/27" in out
    assert "FINAL: PASS" in out


def test_gate_fails_on_timeout(monkeypatch, capsys):
    """超时 → FAIL。"""

    def _fake_run(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=gate_module.EVAL_TIMEOUT_SECONDS)

    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)
    exit_code = gate_module.main([QUALITY])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "TIMEOUT" in out
    assert "FINAL: FAIL" in out


def test_gate_fails_on_nonzero_exit(monkeypatch, capsys):
    """子脚本非 0 → FAIL（即使 summary 看起来正常）。"""
    exit_code, out = _run_gate(monkeypatch, capsys, BASELINE_OUTPUTS, codes={CONVERSATION: 1})

    assert exit_code == 1
    assert "CHILD_EXIT_NONZERO" in out
    assert "FINAL: FAIL" in out


def test_gate_fails_when_passed_exceeds_total(monkeypatch, capsys):
    """passed > total 是坏 summary → FAIL。"""
    outputs = {**BASELINE_OUTPUTS, GROUNDING: "Knowledge Grounding Eval: 30/27 passed\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 1
    assert "INVALID_SUMMARY" in out


def test_gate_fails_when_total_is_zero(monkeypatch, capsys):
    """total == 0 → FAIL（不能靠「一个检查都没跑」过关）。"""
    outputs = {**BASELINE_OUTPUTS, GROUNDING: "Knowledge Grounding Eval: 0/0 passed\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 1
    assert "INVALID_SUMMARY" in out


def test_gate_fails_when_failing_cases_are_deleted(monkeypatch, capsys):
    """删掉失败样例（107 → 105，失败数变 0）不能算通过。"""
    outputs = {**BASELINE_OUTPUTS, QUALITY: "Overall: 105/105 passed (100.0%)\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 1
    assert "min_total" in out


def test_gate_fails_when_easy_checks_mask_a_regression(monkeypatch, capsys):
    """加 2 个简单检查把 failed 从 2 抬到 3 → 仍然 FAIL（不能盖住已有回归）。"""
    outputs = {**BASELINE_OUTPUTS, QUALITY: "Overall: 106/109 passed (97.2%)\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 1
    assert "max_failed" in out


def test_gate_accepts_genuine_improvement(monkeypatch, capsys):
    """真的修好了（107/107）→ PASS。"""
    outputs = {**BASELINE_OUTPUTS, QUALITY: "Overall: 107/107 passed (100.0%)\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 0
    assert "FINAL: PASS" in out


def test_gate_accepts_added_checks_without_new_failures(monkeypatch, capsys):
    """新增检查项且不引入新失败（110/112，failed 仍为 2）→ PASS。"""
    outputs = {**BASELINE_OUTPUTS, QUALITY: "Overall: 110/112 passed (98.2%)\n"}

    exit_code, out = _run_gate(monkeypatch, capsys, outputs)

    assert exit_code == 0
    assert "FINAL: PASS" in out


def test_gate_fails_for_unregistered_script(monkeypatch, capsys):
    """没登记 summary 契约的脚本不能被当成通过。"""
    _install_run(monkeypatch, {})
    exit_code = gate_module.main(["tests/some_unknown_eval.py"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "UNKNOWN_CONTRACT" in out


# ---------------------------------------------------------------------------
# summary 解析：不能随便取 stdout 里最后一个 X/Y
# ---------------------------------------------------------------------------


def test_parse_summary_ignores_noise_before_and_after():
    """只认正式汇总行；前后噪点（含别的 X/Y）不影响结果。"""
    output = (
        "  [PASS] topic_count - got 4\n"
        "  [FAIL] ranking_accuracy - scores 12/4 inverted\n"
        "Overall: 105/107 passed (98.1%)\n"
        "Report: tests/quality_baselines/x/report.md\n"
        "Results: 3/3 files written\n"
    )

    summary = gate_module.parse_summary(QUALITY, output)

    assert summary.ok is True
    assert (summary.passed, summary.total) == (105, 107)


def test_parse_summary_distinguishes_missing_from_malformed():
    assert gate_module.parse_summary(QUALITY, "nothing here\n").reason.startswith("NO_SUMMARY")
    assert gate_module.parse_summary(QUALITY, "Overall: 105 of 107\n").reason.startswith("MALFORMED_SUMMARY")


# ---------------------------------------------------------------------------
# 脱敏：.env（未 export）也要覆盖
# ---------------------------------------------------------------------------


def test_child_env_neutralizes_ai_credentials(monkeypatch):
    """子进程环境必须强制覆盖 AI 凭证，绝不把本机真实 Key 传下去。"""
    monkeypatch.setenv("AI_ZHIPU_API_KEY", "real-looking-zhipu-key-from-shell")

    env = gate_module.build_child_env()

    assert env["AI_ZHIPU_API_KEY"] == "", "子进程不得读到真实智谱 Key"
    assert env["AI_BAILIAN_API_KEY"] == "dummy-key"
    assert env["STRICT_CONFIG"] == "false"
    assert env["PYTHONPATH"].startswith(".")


def test_redact_still_covers_os_environ(monkeypatch, tmp_path: Path):
    """原有能力保留：os.environ 里的 secret 仍被脱敏。"""
    monkeypatch.setenv(gate_module.ENV_FILE_OVERRIDE_ENV, str(tmp_path / "absent.env"))
    monkeypatch.setenv("AI_ZHIPU_API_KEY", "shell-only-secret-abcdef")

    out = gate_module.redact("Authorization: Bearer shell-only-secret-abcdef")

    assert "shell-only-secret-abcdef" not in out
    assert gate_module.REDACTION_PLACEHOLDER in out


def test_redact_covers_env_file_only_secret(monkeypatch, tmp_path: Path):
    """secret 只在 .env、不在 os.environ 时也必须被脱敏。"""
    secret = "sk-envfile-only-9f8e7d6c5b4a"
    monkeypatch.delenv("AI_ZHIPU_API_KEY", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(f"# local config\nAI_ZHIPU_API_KEY={secret}\n", encoding="utf-8")
    monkeypatch.setenv(gate_module.ENV_FILE_OVERRIDE_ENV, str(env_file))

    assert secret in gate_module.collect_secret_values(), "secret 必须来自 .env 而不是 os.environ"

    out = gate_module.redact(f"traceback: provider rejected key {secret}")
    assert secret not in out
    assert gate_module.REDACTION_PLACEHOLDER in out


def test_redact_covers_json_escaped_secret(monkeypatch, tmp_path: Path):
    """JSON 转义形态（\\uXXXX）也必须被脱敏（PR6 sabotage S6 的教训）。"""
    secret = "sk-中文-测试-key-abcdef"
    monkeypatch.delenv("AI_ZHIPU_API_KEY", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(f'AI_ZHIPU_API_KEY="{secret}"\n', encoding="utf-8")
    monkeypatch.setenv(gate_module.ENV_FILE_OVERRIDE_ENV, str(env_file))

    escaped = json.dumps(secret, ensure_ascii=True)[1:-1]
    assert escaped != secret, "测试前提：该 secret 确实存在转义形态"

    payload = json.dumps({"error": f"bad key {secret}"}, ensure_ascii=True)
    out = gate_module.redact(payload)

    assert secret not in out
    assert escaped not in out, "转义形态残留会让断言假阳性通过"


def test_gate_output_redacts_env_file_secret_end_to_end(monkeypatch, capsys, tmp_path: Path):
    """端到端：子进程输出泄露了 .env 里的 Key → gate 输出里不能出现它。"""
    secret = "sk-envfile-leak-1234567890ab"
    monkeypatch.delenv("AI_ZHIPU_API_KEY", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(f"AI_ZHIPU_API_KEY={secret}\n", encoding="utf-8")
    monkeypatch.setenv(gate_module.ENV_FILE_OVERRIDE_ENV, str(env_file))

    def _fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout=f"Traceback\nhttpx.Authorization: Bearer {secret}\n",
            stderr=f"boom while using {secret}",
        )

    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)
    exit_code = gate_module.main([QUALITY])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert secret not in out, ".env 里（未 export）的 Key 泄漏到了 gate 输出"
    assert gate_module.REDACTION_PLACEHOLDER in out


@pytest.mark.parametrize("script", gate_module.EVAL_SCRIPTS)
def test_each_eval_has_a_parseable_summary_contract(script: str):
    spec = gate_module.SPEC_BY_SCRIPT[script]
    assert spec.anchor
    assert spec.pattern.groups >= 2
