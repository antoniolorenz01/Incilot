"""El corpus del RAG, cortado en fragmentos útiles con metadatos.

    runbooks/*.md              un fragmento por runbook               kind=runbook
    docs/**/*.md               un fragmento por sección (## …)        kind=doc
    repo: services/*/*.py      un fragmento por función               kind=code
    repo: config/*.env         un fragmento por archivo               kind=config
    repo: el resto (texto)     un fragmento por archivo               kind=file

El id de cada fragmento es un hash de su origen y su contenido: si el contenido no
cambia, su embedding se reutiliza.
"""

import ast
import hashlib
import re
from pathlib import Path

from langchain_core.documents import Document

from incilot_agent import config

SECTION = re.compile(r"^## ", re.MULTILINE)
TEXT_SUFFIXES = {".md", ".py", ".env", ".sql", ".yml", ".yaml", ".toml", ".txt"}


def _doc(source: str, content: str, kind: str, **metadata) -> Document:
    digest = hashlib.sha256(f"{source}\n{content}".encode()).hexdigest()[:32]
    return Document(
        id=digest, page_content=content, metadata={"source": source, "kind": kind, **metadata}
    )


def _service(path: Path) -> str | None:
    parts = path.parts
    if "services" in parts and parts.index("services") + 1 < len(parts) - 1:
        return parts[parts.index("services") + 1]
    if path.suffix == ".env":
        return path.stem
    return None


def runbooks(root: Path) -> list[Document]:
    return [_doc(f"runbooks/{p.name}", p.read_text(), "runbook") for p in sorted(root.glob("*.md"))]


def docs(root: Path) -> list[Document]:
    chunks = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        text = path.read_text()
        title = text.splitlines()[0].lstrip("# ") if text else relative.stem
        for section in SECTION.split(text):
            if not section.strip():
                continue
            heading = section.splitlines()[0].lstrip("# ")
            content = section if section.startswith("#") else f"## {section}"
            chunks.append(
                _doc(
                    f"docs/{relative}#{heading}",
                    f"{title}\n\n{content}".strip(),
                    "doc",
                    service=relative.stem if relative.parent.name == "services" else None,
                )
            )
    return chunks


def python_functions(path: Path, source: str) -> list[Document]:
    """Una función por fragmento, con el docstring del módulo como contexto."""
    text = path.read_text()
    tree = ast.parse(text)
    header = ast.get_docstring(tree) or ""
    chunks = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            body = ast.get_source_segment(text, node)
            chunks.append(
                _doc(
                    f"{source}::{node.name}",
                    f"# {source} — {header}\n{body}",
                    "code",
                    service=_service(path),
                    function=node.name,
                )
            )
    return chunks or [_doc(source, text, "code", service=_service(path))]


def company_repo(root: Path) -> list[Document]:
    chunks = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if ".git" in relative.parts or path.suffix not in TEXT_SUFFIXES:
            continue
        source = str(relative)
        if path.suffix == ".py":
            chunks += python_functions(path, source)
        elif path.suffix == ".env":
            chunks.append(_doc(source, path.read_text(), "config", service=_service(relative)))
        else:
            chunks.append(_doc(source, path.read_text(), "file", service=_service(relative)))
    return chunks


def load() -> list[Document]:
    return (
        runbooks(config.RUNBOOKS_DIR)
        + (docs(config.DOCS_DIR) if config.DOCS_DIR.exists() else [])
        + company_repo(config.COMPANY_REPO)
    )
