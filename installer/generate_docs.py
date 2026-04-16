"""Generate API reference + tutorial docs from the OpenForge codebase.

Walks each Python package under ``packages/*/src``, extracts module and
class docstrings via the ``ast`` module, and renders them to
``docs/api/*.md``. Also walks ``openforge.tutorials.library.TUTORIALS``
and emits one markdown file per tutorial under ``docs/tutorials/``.

Run:
    python installer/generate_docs.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
API_DIR = DOCS / "api"
TUT_DIR = DOCS / "tutorials"

PACKAGES = [
    ("openforge", ROOT / "packages" / "core" / "src" / "openforge"),
    ("openforge_cli", ROOT / "packages" / "cli" / "src" / "openforge_cli"),
    ("openforge_api", ROOT / "packages" / "api" / "src" / "openforge_api"),
    ("openforge_desktop", ROOT / "packages" / "desktop" / "src" / "openforge_desktop"),
    ("openforge_crypto", ROOT / "packages" / "crypto" / "src" / "openforge_crypto"),
]


def _module_docs(path: Path) -> dict:
    """Return {module_doc, classes: [{name, doc, methods: [...]}]}."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        return {"error": str(exc), "module_doc": "", "classes": []}

    module_doc = ast.get_docstring(tree) or ""
    classes = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            methods = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("_"):
                        continue
                    try:
                        sig = ast.unparse(sub.args)
                    except Exception:  # noqa: BLE001
                        sig = "..."
                    methods.append({
                        "name": sub.name,
                        "signature": f"{sub.name}({sig})",
                        "doc": ast.get_docstring(sub) or "",
                    })
            classes.append({
                "name": node.name,
                "doc": ast.get_docstring(node) or "",
                "methods": methods,
            })
    return {"module_doc": module_doc, "classes": classes}


def _render_module(relpath: str, info: dict) -> str:
    """Render a single module's docs as MkDocs-compatible Markdown.

    Uses admonitions for parse errors and proper heading hierarchy
    for integration with MkDocs Material theme.
    """
    out = [f"# `{relpath}`", ""]
    if info.get("error"):
        out.append(f'!!! warning "Parse error"')
        out.append(f"    {info['error']}")
        return "\n".join(out)
    if info["module_doc"]:
        out.append(info["module_doc"])
        out.append("")
    for cls in info["classes"]:
        out.append(f"## class `{cls['name']}`")
        out.append("")
        if cls["doc"]:
            out.append(cls["doc"])
            out.append("")
        for m in cls["methods"]:
            out.append(f"### `{m['signature']}`")
            if m["doc"]:
                out.append("")
                out.append(m["doc"])
            out.append("")
    return "\n".join(out)


def generate_api_docs() -> list[Path]:
    API_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index_lines = ["# OpenForge API Reference", ""]

    for pkg_name, src in PACKAGES:
        if not src.exists():
            continue
        index_lines.append(f"## `{pkg_name}`")
        for py in sorted(src.rglob("*.py")):
            if py.name.startswith("_") and py.name != "__init__.py":
                continue
            rel = py.relative_to(src).with_suffix("")
            mod = ".".join([pkg_name, *rel.parts]).removesuffix(".__init__")
            info = _module_docs(py)
            if not info.get("module_doc") and not info.get("classes"):
                continue
            out_path = API_DIR / pkg_name / (mod.replace(".", "_") + ".md")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(_render_module(mod, info), encoding="utf-8")
            written.append(out_path)
            index_lines.append(f"- [{mod}]({out_path.relative_to(API_DIR).as_posix()})")
        index_lines.append("")

    # Write the auto-generated module listing (separate from the hand-written
    # docs/api/index.md so MkDocs can include both).
    (API_DIR / "modules.md").write_text("\n".join(index_lines), encoding="utf-8")
    return written


def generate_tutorial_docs() -> list[Path]:
    TUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))
        from openforge.tutorials.library import TUTORIALS  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] tutorials unavailable: {exc}")
        return []

    written: list[Path] = []
    index = ["# Tutorials", ""]
    by_persona: dict[str, list] = {}
    for t in TUTORIALS.values():
        by_persona.setdefault(t.persona, []).append(t)

    for persona in sorted(by_persona):
        index.append(f"## {persona.title()}")
        for t in by_persona[persona]:
            md = [
                f"# {t.title}",
                "",
                f"*{t.description}*",
                "",
                f"- **Persona**: {t.persona}",
                f"- **Duration**: {t.duration_minutes} min",
                f"- **Difficulty**: {t.difficulty}",
                f"- **Prerequisites**: {', '.join(t.prerequisites) or 'none'}",
                "",
                "## Steps",
                "",
            ]
            for i, step in enumerate(t.steps, 1):
                md.append(f"### {i}. {step.title}")
                md.append("")
                md.append(step.content)
                if step.hint:
                    md.append("")
                    md.append(f"> Hint: {step.hint}")
                md.append("")
            out = TUT_DIR / f"{t.id}.md"
            out.write_text("\n".join(md), encoding="utf-8")
            written.append(out)
            index.append(f"- [{t.title}]({t.id}.md) - {t.duration_minutes} min, {t.difficulty}")
        index.append("")

    (TUT_DIR / "index.md").write_text("\n".join(index), encoding="utf-8")
    return written


def main() -> int:
    print("[docs] generating API reference...")
    api_files = generate_api_docs()
    print(f"[docs] wrote {len(api_files)} API files")
    print("[docs] generating tutorial docs...")
    tut_files = generate_tutorial_docs()
    print(f"[docs] wrote {len(tut_files)} tutorial files")
    print("[done]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
