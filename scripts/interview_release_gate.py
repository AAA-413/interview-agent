#!/usr/bin/env python
"""PR6：Interview Release Gate。

作用只有一个：把**已有的 deterministic eval** 串成一个可执行的发布门禁。

它不是新的评分算法，也不做任何新的事：

```text
tests/quality_baseline_eval.py      面试质量基线
tests/conversation_pipeline_eval.py 对话主链契约
tests/knowledge_grounding_eval.py   Knowledge Grounding 契约
```

约束：

```text
- 全部使用 stub / fake，**不调用** 智谱 / DashScope / 真实 DB / Redis / 外网
- 用 sys.executable 调用（不写死 python / python3 / .venv/bin/python）
- 每个 eval 独立 timeout（默认 120s），超时按 FAIL 处理，不让 CI 永远挂住
- 任一 eval 非 0 → 本脚本 exit 1；全部通过 → exit 0
- 失败时打印 script / exit code / stdout tail / stderr tail，且绝不打印 env secrets
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass

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

#: 从输出里提取 `X/Y` 形式的计数
COUNT_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+)")

#: 输出里需要掩掉的敏感环境变量名（只用于脱敏打印，不读取值以外的东西）
SENSITIVE_ENV_KEYS = (
    "AI_ZHIPU_API_KEY",
    "AI_BAILIAN_API_KEY",
    "AI_EMBEDDING_API_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "JWT_SECRET_KEY",
    "APP_STORAGE_SECRET_KEY",
)


@dataclass
class EvalResult:
    script: str
    passed: bool
    returncode: int
    counts: str
    stdout_tail: str
    stderr_tail: str


def redact(text: str) -> str:
    """把输出里可能出现的密钥值替换掉（防御性，正常情况不该出现）。"""
    redacted = text
    for key in SENSITIVE_ENV_KEYS:
        value = os.environ.get(key)
        if value and len(value) >= 4 and value in redacted:
            redacted = redacted.replace(value, "***")
    return redacted


def extract_counts(output: str) -> str:
    """从 eval 输出里抓 `x/y` 计数（不写死具体数字）。"""
    matches = COUNT_PATTERN.findall(output)
    if not matches:
        return ""
    passed, total = matches[-1]
    return f"{passed}/{total}"


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    stripped = [line for line in (text or "").splitlines() if line.strip()]
    return "\n".join(stripped[-lines:])


def run_eval(script: str, *, timeout: int = EVAL_TIMEOUT_SECONDS) -> EvalResult:
    """在独立子进程里跑一个 eval。"""
    env = dict(os.environ)
    # 保证 `import app...` 可用（与 CI / 本地手动跑法一致）
    env["PYTHONPATH"] = "." if not env.get("PYTHONPATH") else f".:{env['PYTHONPATH']}"

    try:
        completed = subprocess.run(  # noqa: S603 - 固定脚本列表，非用户输入
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return EvalResult(
            script=script,
            passed=False,
            returncode=-1,
            counts="",
            stdout_tail=_tail(redact(_decode(exc.stdout))),
            stderr_tail=f"TIMEOUT after {timeout}s",
        )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return EvalResult(
        script=script,
        passed=completed.returncode == 0,
        returncode=completed.returncode,
        counts=extract_counts(stdout),
        stdout_tail=_tail(redact(stdout)),
        stderr_tail=_tail(redact(stderr)),
    )


def _decode(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    scripts = EVAL_SCRIPTS
    if argv:
        # 允许传参覆盖（调试用），但默认永远是上面这三个
        scripts = tuple(argv)

    print("Interview Release Gate")
    print("")

    results: list[EvalResult] = []
    for script in scripts:
        result = run_eval(script)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        detail = f" {result.counts}" if result.counts else ""
        print(f"{script.split('/')[-1]:<28} {status}{detail}")

    failures = [item for item in results if not item.passed]
    if failures:
        for item in failures:
            print("")
            print(f"--- FAILED: {item.script} (exit={item.returncode}) ---")
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
