from pathlib import Path

from jinja2 import Environment, FileSystemLoader, BaseLoader


_env = Environment(loader=FileSystemLoader("."))


def render_template_from_file(template_path: str | Path, **variables: object) -> str:
    path = Path(template_path)
    template = _env.get_template(str(path))
    return template.render(**variables)


def render_template_from_string(template_str: str, **variables: object) -> str:
    template = _env.from_string(template_str)
    return template.render(**variables)
