#!/usr/bin/env python
"""PR6：Interview Release Gate。

作用只有一个：把**已有的 deterministic eval** 串成一个可执行的发布门禁。

```text
tests/quality_baseline_eval.py      面试质量基线
tests/conversation_pipeline_eval.py 对话主链契约
tests/knowledge_grounding_eval.py   Knowledge Grounding 契约
```

判据（PR #11 review round 1 修复：原实现只看 returncode，导致 fail-open）
--------------------------------------------------------------------
每一个 eval 必须**同时**满足两件互相独立的事：

```text
1. 子脚本正常完成                 → returncode == 0
2. 子脚本真的跑了、且达到质量底线  → 解析出契约内的 summary 行，且 >= 冻结基线
```

只满足 (1) 是不够的：``quality_baseline_eval.py`` 只在 pass rate < 75% 时才 exit 1，
所以 105/107 与 85/107 都是 exit 0；完全不输出也可能是 exit 0。

summary 判定（fail closed）
---------------------------
```text
没有 summary 行                 → FAIL (NO_SUMMARY)
有锚点但格式不符                 → FAIL (MALFORMED_SUMMARY)
passed > total                  → FAIL (INVALID_SUMMARY)
total == 0                      → FAIL (INVALID_SUMMARY)
未登记契约的脚本                  → FAIL (UNKNOWN_CONTRACT)
低于冻结基线                     → FAIL (BELOW_BASELINE)
```

冻结基线见 ``scripts/release_baseline.json``（可版本管理、可进 PR diff）。三条约束
必须同时成立，才能同时挡住「质量退化」「删检查项粉饰」「加简单检查盖住回归」：

```text
total  >= min_total     防止删除检查项 / 删除失败样例
passed >= min_passed    防止质量本身退化
failed <= max_failed    防止新增简单检查掩盖已有基线回归
```

其他约束
--------
```text
- 全部使用 stub / fake，**不调用** 智谱 / DashScope / 真实 DB / Redis / 外网
- 子进程环境强制覆盖 AI 凭证（.env 里的真实 Key 不会进子进程）
- 用 sys.executable 调用（不写死 python / python3 / .venv/bin/python）
- 每个 eval 独立 timeout（默认 120s），超时按 FAIL 处理，不让 CI 永远挂住
- 失败时打印 script / exit code / stdout tail / stderr tail
- 打印前做脱敏：os.environ **和** 本地 .env 加载的敏感值都不会出现在输出里
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: 单个 eval 的超时上限（秒）
EVAL_TIMEOUT_SECONDS = 120

#: 失败时打印的尾部行数
TAIL_LINES = 30

#: release gate 覆盖的 deterministic eval（顺序即输出顺序）
EVAL_SCRIPTS: tuple[str, ...] = (
    "tests/quality_baseline_eval.py",
    "tests/conversation_pipeline_eval.py",
    "tests/knowledge_grounding_eval.py",
)

#: 冻结基线配置（可版本管理）
REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "scripts" / "release_baseline.json"

#: 允许测试用临时 .env 覆盖默认路径（只为脱敏来源可控，不改变读取优先级）
ENV_FILE_OVERRIDE_ENV = "INTERVIEW_RELEASE_GATE_ENV_FILE"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

#: 输出里需要掩掉的敏感配置名（只用于脱敏，不读取值以外的任何东西）
SENSITIVE_ENV_KEYS = (
    "AI_ZHIPU_API_KEY",
    "AI_BAILIAN_API_KEY",
    "AI_EMBEDDING_API_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "JWT_SECRET_KEY",
    "APP_STORAGE_SECRET_KEY",
)

#: 子进程强制覆盖的配置。环境变量优先级高于 .env，因此**本机 .env 里的真实
#: AI 凭证不会进入 deterministic eval 子进程**（deterministic eval 不应该需要它们）。
CHILD_ENV_OVERRIDES: dict[str, str] = {
    "AI_ZHIPU_API_KEY": "",
    "AI_EMBEDDING_API_KEY": "",
    "AI_BAILIAN_API_KEY": "dummy-key",
    "STRICT_CONFIG": "false",
}

#: 脱敏时替换成的占位符
REDACTION_PLACEHOLDER = "***"


# ---------------------------------------------------------------------------
# summary 契约
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalSpec:
    """一个 eval 的 summary 契约。

    ``anchor`` 用来区分「一行汇总都没输出」和「输出了但格式不对」，
    ``pattern`` 才是真正的解析规则 —— 只认这一条正式汇总行，
    不会去 stdout 里随便抓最后一个 ``X/Y``。
    """

    script: str
    anchor: str
    pattern: re.Pattern[str]


EVAL_SPECS: tuple[EvalSpec, ...] = (
    EvalSpec(
        script="tests/quality_baseline_eval.py",
        anchor="Overall:",
        pattern=re.compile(r"^Overall:\s*(?P<passed>\d+)\s*/\s*(?P<total>\d+)\s+passed\b", re.MULTILINE),
    ),
    EvalSpec(
        script="tests/conversation_pipeline_eval.py",
        anchor="Conversation Pipeline Contract Eval:",
        pattern=re.compile(
            r"^Conversation Pipeline Contract Eval:\s*(?P<passed>\d+)\s*/\s*(?P<total>\d+)\s+passed\b",
            re.MULTILINE,
        ),
    ),
    EvalSpec(
        script="tests/knowledge_grounding_eval.py",
        anchor="Knowledge Grounding Eval:",
        pattern=re.compile(
            r"^Knowledge Grounding Eval:\s*(?P<passed>\d+)\s*/\s*(?P<total>\d+)\s+passed\b",
            re.MULTILINE,
        ),
    ),
)

SPEC_BY_SCRIPT: dict[str, EvalSpec] = {spec.script: spec for spec in EVAL_SPECS}


@dataclass(frozen=True)
class SummaryCheck:
    """summary 解析结果（不含基线比较）。"""

    ok: bool
    counts: str = ""
    reason: str = ""
    passed: int = 0
    total: int = 0

    @property
    def failed(self) -> int:
        return max(0, self.total - self.passed)


def parse_summary(script: str, output: str) -> SummaryCheck:
    """从 eval 输出里解析该 eval 契约内的正式 summary 行。"""
    spec = SPEC_BY_SCRIPT.get(script)
    if spec is None:
        return SummaryCheck(False, reason=f"UNKNOWN_CONTRACT: {script} 没有登记 summary 契约")

    match = spec.pattern.search(output or "")
    if match is None:
        if spec.anchor in (output or ""):
            return SummaryCheck(False, reason=f"MALFORMED_SUMMARY: 出现 '{spec.anchor}' 但不符合契约格式")
        return SummaryCheck(False, reason=f"NO_SUMMARY: 未输出 '{spec.anchor}' 汇总行")

    passed = int(match.group("passed"))
    total = int(match.group("total"))
    counts = f"{passed}/{total}"

    if total == 0:
        return SummaryCheck(False, counts=counts, reason="INVALID_SUMMARY: total == 0", passed=passed, total=total)
    if passed > total:
        return SummaryCheck(False, counts=counts, reason="INVALID_SUMMARY: passed > total", passed=passed, total=total)

    return SummaryCheck(True, counts=counts, passed=passed, total=total)


# ---------------------------------------------------------------------------
# 冻结基线
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Baseline:
    """一个 eval 的冻结质量底线。"""

    label: str
    min_passed: int
    min_total: int
    max_failed: int

    def violations(self, passed: int, total: int) -> list[str]:
        """返回所有违反基线的理由（可能不止一条）。"""
        failed = max(0, total - passed)
        reasons: list[str] = []
        if total < self.min_total:
            reasons.append(f"total {total} < min_total {self.min_total}")
        if passed < self.min_passed:
            reasons.append(f"passed {passed} < min_passed {self.min_passed}")
        if failed > self.max_failed:
            reasons.append(f"failed {failed} > max_failed {self.max_failed}")
        return reasons


@dataclass
class BaselineConfig:
    baselines: dict[str, Baseline] = field(default_factory=dict)
    error: str | None = None

    def get(self, script: str) -> Baseline | None:
        return self.baselines.get(script)


def load_baseline(path: Path | None = None) -> BaselineConfig:
    """读取冻结基线。读不到 / 解析失败一律视为配置错误（fail closed）。"""
    target = path or BASELINE_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return BaselineConfig(error=f"baseline 配置不存在: {target}")
    except (OSError, json.JSONDecodeError) as exc:
        return BaselineConfig(error=f"baseline 配置无法解析: {target}: {exc.__class__.__name__}: {exc}")

    evals = raw.get("evals")
    if not isinstance(evals, dict) or not evals:
        return BaselineConfig(error=f"baseline 配置缺少非空 evals: {target}")

    baselines: dict[str, Baseline] = {}
    for script, payload in evals.items():
        if not isinstance(payload, dict):
            return BaselineConfig(error=f"baseline 条目不是对象: {script}")
        try:
            baselines[script] = Baseline(
                label=str(payload.get("label") or Path(script).name),
                min_passed=int(payload["min_passed"]),
                min_total=int(payload["min_total"]),
                max_failed=int(payload["max_failed"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return BaselineConfig(error=f"baseline 条目字段非法: {script}: {exc}")

    return BaselineConfig(baselines=baselines)


# ---------------------------------------------------------------------------
# 脱敏（os.environ + 本地 .env）
# ---------------------------------------------------------------------------


def _env_file_path() -> Path:
    override = os.environ.get(ENV_FILE_OVERRIDE_ENV)
    return Path(override) if override else DEFAULT_ENV_FILE


def _parse_env_file(path: Path) -> dict[str, str]:
    """极简 .env 解析：只为拿到脱敏用的值，不做变量展开。"""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def collect_secret_values() -> set[str]:
    """收集需要脱敏的敏感值：os.environ **和** 本地 .env 两处。

    只读 os.environ 是不够的：项目用 pydantic-settings 从 .env 读配置，
    本机真实 Key 完全可能只存在于 .env 而没有被 export 到进程环境里。
    """
    candidates: list[str] = []

    for key in SENSITIVE_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            candidates.append(value)

    env_file_values = _parse_env_file(_env_file_path())
    for key in SENSITIVE_ENV_KEYS:
        value = env_file_values.get(key)
        if value:
            candidates.append(value)

    return {value for value in candidates if len(value) >= 4}


def _secret_variants(value: str) -> set[str]:
    """同一个 secret 的原始形态与 JSON 转义形态。

    只替换原始形态是不够的：中文 / 特殊字符被 ``json.dumps`` 序列化后会变成
    ``\\uXXXX`` 转义形态，``in`` 断言会假阳性通过（PR6 sabotage S6 的教训）。
    """
    variants = {value}
    escaped = json.dumps(value, ensure_ascii=True)[1:-1]
    if escaped and escaped != value:
        variants.add(escaped)
    return variants


def redact(text: str) -> str:
    """把输出里可能出现的敏感值替换掉（防御性，正常情况不该出现）。"""
    if not text:
        return text

    secrets = collect_secret_values()
    # 长 secret 优先替换，避免短 secret 是长 secret 子串时留下残留
    for secret in sorted(secrets, key=len, reverse=True):
        for variant in _secret_variants(secret):
            if variant and variant in text:
                text = text.replace(variant, REDACTION_PLACEHOLDER)
    return text


# ---------------------------------------------------------------------------
# 子进程执行
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    script: str
    passed: bool
    returncode: int
    counts: str
    reasons: list[str]
    stdout_tail: str
    stderr_tail: str
    summary: SummaryCheck | None = None


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    stripped = [line for line in (text or "").splitlines() if line.strip()]
    return "\n".join(stripped[-lines:])


def _decode(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def build_child_env() -> dict[str, str]:
    """构造子进程环境：保留当前环境，但强制覆盖 AI 凭证。"""
    env = dict(os.environ)
    env.update(CHILD_ENV_OVERRIDES)
    # 保证 `import app...` 可用（与 CI / 本地手动跑法一致）
    env["PYTHONPATH"] = "." if not env.get("PYTHONPATH") else f".:{env['PYTHONPATH']}"
    return env


def _evaluate(script: str, returncode: int, stdout: str, baseline: BaselineConfig) -> EvalResult:
    """returncode + summary + 基线，三件事互相独立地判定。"""
    reasons: list[str] = []
    summary = parse_summary(script, stdout)

    if returncode != 0:
        reasons.append(f"CHILD_EXIT_NONZERO: exit={returncode}")

    if not summary.ok:
        reasons.append(summary.reason)
    else:
        entry = baseline.get(script)
        if entry is None:
            reasons.append(f"MISSING_BASELINE: {script} 未在 release_baseline.json 登记")
        else:
            reasons.extend(f"BELOW_BASELINE: {item}" for item in entry.violations(summary.passed, summary.total))

    return EvalResult(
        script=script,
        passed=not reasons,
        returncode=returncode,
        counts=summary.counts,
        reasons=reasons,
        stdout_tail=_tail(redact(stdout)),
        stderr_tail="",
        summary=summary,
    )


def run_eval(script: str, *, timeout: int = EVAL_TIMEOUT_SECONDS, baseline: BaselineConfig | None = None) -> EvalResult:
    """在独立子进程里跑一个 eval，并按「returncode + summary + 基线」判定。"""
    config = baseline or load_baseline()

    try:
        completed = subprocess.run(  # noqa: S603 - 固定脚本列表，非用户输入
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=build_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return EvalResult(
            script=script,
            passed=False,
            returncode=-1,
            counts="",
            reasons=[f"TIMEOUT after {timeout}s"],
            stdout_tail=_tail(redact(_decode(exc.stdout))),
            stderr_tail=f"TIMEOUT after {timeout}s",
        )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    result = _evaluate(script, completed.returncode, stdout, config)
    result.stderr_tail = _tail(redact(stderr))
    return result


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _label_for(script: str, baseline: BaselineConfig) -> str:
    entry = baseline.get(script)
    return entry.label if entry else Path(script).name


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    scripts = tuple(argv) if argv else EVAL_SCRIPTS

    print("Interview Release Gate")
    print("")

    baseline = load_baseline()
    if baseline.error:
        # 基线读不到 = 门禁本身不可信 → 一律 FAIL，绝不静默放行
        print(f"baseline: ERROR - {baseline.error}")
        print("")
        print("FINAL: FAIL")
        return 1

    results: list[EvalResult] = []
    for script in scripts:
        result = run_eval(script, baseline=baseline)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        detail = f" {result.counts}" if result.counts else ""
        print(f"{_label_for(script, baseline):<28} {status}{detail}")

    failures = [item for item in results if not item.passed]
    for item in failures:
        print("")
        print(f"--- FAILED: {item.script} (exit={item.returncode}) ---")
        for reason in item.reasons:
            print(f"reason: {reason}")
        if item.stdout_tail:
            print("[stdout tail]")
            print(item.stdout_tail)
        if item.stderr_tail:
            print("[stderr tail]")
            print(item.stderr_tail)

    print("")
    print(f"FINAL: {'PASS' if not failures else 'FAIL'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
