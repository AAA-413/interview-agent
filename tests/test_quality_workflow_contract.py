"""PR6：CI / Release Gate 契约测试。

两件事：

```text
1. quality.yml 的 trigger 与 backend steps 契约 —— 谁把 main 从 trigger 里删掉、
   或把 release gate 从 CI 里摘掉，pytest 直接失败（不靠人眼 review）。
2. interview_release_gate.py 的 wrapper 语义 —— 全 PASS → exit 0；
   任一 FAIL / timeout → exit 1；子进程用 sys.executable；失败输出不泄漏 secret。
```

wrapper 测试用 mock subprocess，**不真的跑三套 eval**（那属于 release gate 自己的职责，
由 CI 的 Interview Release Gate step 真实执行）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import scripts.interview_release_gate as gate_module

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "quality.yml"
QUALITY_CHECK_PATH = REPO_ROOT / "scripts" / "quality_check.sh"


def _workflow_text() -> str:
    assert WORKFLOW_PATH.is_file(), "quality.yml 必须存在"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _workflow_doc() -> dict:
    # YAML 1.1 会把裸 `on` 解析成布尔 True，两种 key 都接受
    doc = yaml.safe_load(_workflow_text())
    assert isinstance(doc, dict)
    return doc


def _triggers(doc: dict) -> dict:
    triggers = doc.get("on")
    if triggers is None:
        triggers = doc.get(True)
    assert isinstance(triggers, dict), "workflow 必须声明 on:"
    return triggers


# ---------------------------------------------------------------------------
# Workflow trigger contract
# ---------------------------------------------------------------------------


def test_quality_workflow_exists():
    assert WORKFLOW_PATH.is_file()


def test_workflow_triggers_include_long_lived_branches():
    triggers = _triggers(_workflow_doc())
    push = triggers.get("push")
    assert isinstance(push, dict), "push 必须是带 branches 的映射（不能用通配说明不清的分支策略）"
    branches = push.get("branches") or []
    assert "main" in branches, "main 必须显式在 push trigger 里"
    assert "develop" in branches
    assert "mac_dev" in branches, "仓库存在的长期分支不能被静默丢出 CI"
    for prefix in ("feat/**", "fix/**", "chore/**"):
        assert prefix in branches


def test_workflow_runs_on_pull_request_and_manual_dispatch():
    triggers = _triggers(_workflow_doc())
    assert "pull_request" in triggers
    assert "workflow_dispatch" in triggers


def test_workflow_text_contains_expected_markers():
    text = _workflow_text()
    for marker in ("push:", "main", "develop", "pull_request:", "workflow_dispatch:"):
        assert marker in text


# ---------------------------------------------------------------------------
# Workflow steps contract
# ---------------------------------------------------------------------------


def _backend_steps() -> list[dict]:
    doc = _workflow_doc()
    jobs = doc.get("jobs") or {}
    backend = jobs.get("backend")
    assert isinstance(backend, dict), "必须有 backend job"
    steps = backend.get("steps") or []
    assert steps
    return steps


def _step_names() -> list[str]:
    return [str(step.get("name", "")) for step in _backend_steps()]


def _step_runs_joined() -> str:
    return "\n".join(str(step.get("run", "")) for step in _backend_steps())


def test_backend_runs_release_gate_in_ci():
    assert "interview_release_gate.py" in _step_runs_joined(), "CI 必须运行 Interview Release Gate"


def test_backend_runs_pytest_ruff_and_compile():
    joined = _step_runs_joined()
    assert "pytest -q" in joined
    assert "ruff check ." in joined
    assert "ruff format --check ." in joined
    assert "compileall" in joined


def test_release_gate_step_comes_after_pytest():
    names = _step_names()
    assert any("Release Gate" in name for name in names)
    pytest_index = next(index for index, name in enumerate(names) if name == "Pytest")
    gate_index = next(index for index, name in enumerate(names) if "Release Gate" in name)
    assert gate_index > pytest_index


def test_frontend_job_still_builds():
    doc = _workflow_doc()
    frontend = (doc.get("jobs") or {}).get("frontend") or {}
    runs = "\n".join(str(step.get("run", "")) for step in (frontend.get("steps") or []))
    assert "npm run build" in runs


def test_workflow_uses_only_allowlisted_actions():
    """供应链面收口：只允许使用已有的四个官方 action。"""
    allowed = {
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/setup-node@v4",
    }
    used = {
        str(step.get("uses")).strip()
        for step in _backend_steps() + ((_workflow_doc().get("jobs") or {}).get("frontend") or {}).get("steps", [])
        if step.get("uses")
    }
    assert used <= allowed, f"出现了白名单外的 action: {used - allowed}"


def test_ci_does_not_require_real_embedding_key():
    """deterministic eval 不得要求真实 AI_ZHIPU_API_KEY。"""
    doc = _workflow_doc()
    env = (doc.get("jobs") or {}).get("backend", {}).get("env") or {}
    assert "AI_ZHIPU_API_KEY" not in env
    assert env.get("AI_BAILIAN_API_KEY") == "dummy-key"


# ---------------------------------------------------------------------------
# quality_check.sh contract
# ---------------------------------------------------------------------------


def test_quality_check_runs_release_gate_before_frontend_build():
    assert QUALITY_CHECK_PATH.is_file()
    text = QUALITY_CHECK_PATH.read_text(encoding="utf-8")
    assert "interview_release_gate.py" in text
    assert text.index("interview_release_gate.py") < text.index("npm run build")


# ---------------------------------------------------------------------------
# Release Gate wrapper 语义
# ---------------------------------------------------------------------------


def test_release_gate_covers_expected_evals():
    assert gate_module.EVAL_SCRIPTS == (
        "tests/quality_baseline_eval.py",
        "tests/conversation_pipeline_eval.py",
        "tests/knowledge_grounding_eval.py",
    )


def test_release_gate_uses_current_python(monkeypatch):
    recorded: dict = {}

    def _fake_run(cmd, **_kwargs):
        recorded["argv0"] = cmd[0]
        return subprocess.CompletedProcess(cmd, 0, stdout="1/1", stderr="")

    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)
    assert gate_module.main(["tests/quality_baseline_eval.py"]) == 0
    assert recorded["argv0"] == sys.executable


def test_release_gate_passes_when_all_children_pass(monkeypatch, capsys):
    def _fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="Eval: 5/5 passed", stderr="")

    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)
    exit_code = gate_module.main(["a.py", "b.py"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "FINAL: PASS" in out
    assert out.count("PASS") >= 2


def test_release_gate_fails_when_any_child_fails(monkeypatch, capsys):
    def _fake_run(cmd, **_kwargs):
        code = 1 if cmd[1] == "bad.py" else 0
        return subprocess.CompletedProcess(cmd, code, stdout="Eval: 1/2 passed", stderr="boom")

    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)
    exit_code = gate_module.main(["good.py", "bad.py"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "FINAL: FAIL" in out
    assert "bad.py" in out
    assert "boom" in out, "失败时必须打印 stderr tail 便于诊断"


def test_release_gate_fails_on_timeout(monkeypatch, capsys):
    def _fake_run(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=gate_module.EVAL_TIMEOUT_SECONDS)

    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)
    exit_code = gate_module.main(["slow.py"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "TIMEOUT" in out
    assert "FINAL: FAIL" in out


def test_release_gate_does_not_leak_secrets(monkeypatch, capsys):
    secret = "0123456789abcdefSECRETKEY"

    def _fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=f"Authorization: Bearer {secret}", stderr="")

    monkeypatch.setenv("AI_ZHIPU_API_KEY", secret)
    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)
    gate_module.main(["leaky.py"])

    out = capsys.readouterr().out
    assert secret not in out
    assert "***" in out


def test_release_gate_passes_pythonpath_to_children(monkeypatch):
    recorded: dict = {}

    def _fake_run(cmd, **kwargs):
        recorded["env"] = kwargs.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(gate_module.subprocess, "run", _fake_run)
    gate_module.main(["a.py"])
    assert recorded["env"]["PYTHONPATH"].startswith(".")


@pytest.mark.parametrize("script", gate_module.EVAL_SCRIPTS)
def test_release_gate_scripts_exist(script):
    assert (REPO_ROOT / script).is_file()
