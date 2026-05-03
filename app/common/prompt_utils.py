from pathlib import Path


def load_prompt(prompts_dir: Path, filename: str) -> str:
    """从 prompts 目录加载 prompt 文件内容。"""
    path = prompts_dir / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def render_template(template: str, variables: dict) -> str:
    """渲染 {{ key }} 格式的模板变量。"""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{ {key} }}}}", str(value))
    return result
