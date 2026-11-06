"""Static analysis scanner for CodeCompass.

The scanner walks a local directory and extracts the module-level dependency
graph of every supported source file:

* ``.py`` — parsed with the standard library ``ast`` module (never
  ``exec``/``import``, so untrusted code is only ever read as text) and stored
  with ``dependency_type='import'``.
* ``.cs`` — scanned with a line-oriented regex for ``using`` directives and
  stored with ``dependency_type='using'``.
* ``.js`` / ``.jsx`` / ``.ts`` / ``.tsx`` — scanned with a regex for ES module
  ``import``/``export ... from`` and CommonJS ``require()`` and stored with
  ``dependency_type='import'``.

Findings become :class:`CodeDependency` rows, and oversized files (either
language) become :class:`TechnicalDebtItem` rows.

Design notes:
* Paths are stored **relative to the scanned root** in POSIX form. That keeps the
  ``(project_id, source_file, target_file)`` unique constraint stable when the
  same repository is scanned from a different mount point or CI workspace.
* Inserts are idempotent: dependencies use PostgreSQL ``ON CONFLICT DO NOTHING``
  against the existing unique constraint, and debt items are de-duplicated per
  ``(project_id, category, file_path)`` before insert. Re-scanning a project is
  therefore safe and cheap.
* A single transaction covers the whole scan, so a crash mid-way leaves no
  half-written graph.
"""

from __future__ import annotations

import ast
import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import CodeDependency, Severity, TechnicalDebtItem

#: Files longer than this (physical lines) are reported as high complexity.
LOC_THRESHOLD = 300

#: Hard cap so a scan pointed at ``/`` cannot run forever or exhaust memory.
MAX_FILES = 20_000

#: Files above this size are almost certainly generated/vendored; skip them.
MAX_FILE_BYTES = 2 * 1024 * 1024

#: Rows per INSERT statement, kept well under PostgreSQL's 65,535 bind-parameter cap.
_INSERT_CHUNK_SIZE = 1_000

#: Directories that never contain first-party source worth analysing.
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        ".next",      # <-- Added: Next.js build output
        "out",        # <-- Added: Next.js static export output
        "bin",
        "build",
        "dist",
        "node_modules",
        "obj",
        "site-packages",
        "venv",
    }
)

#: Extensions the scanner understands, mapped to the dependency_type they emit.
SOURCE_SUFFIXES: dict[str, str] = {
    ".py": "import",
    ".cs": "using",
    ".js": "import",
    ".jsx": "import",
    ".ts": "import",
    ".tsx": "import",
}

#: ``import ... from 'mod'`` / ``import 'mod'`` / ``export ... from 'mod'``.
#: Matched against comment/string-blanked code, so the specifier itself is
#: blanked out; the ``from``/``import`` keyword offsets are used to read the
#: real specifier from the original text. Dynamic ``import('mod')`` is
#: intentionally excluded — it is a runtime call, not a static edge.
JS_IMPORT_RE = re.compile(
    r"""\b(?:import|export)\b[^;]*?\bfrom\b"""
    r"""|(?<![\w$.])import\s*(?=['"`])""",
)

#: ``require('mod')`` / ``require("mod")`` — CommonJS. The lookbehind rejects
#: member calls such as ``obj.require('x')``.
JS_REQUIRE_RE = re.compile(r"""(?<![\w$.])require\s*\(\s*(?=['"`])""")

#: Reads the quoted module specifier starting at a given offset.
JS_SPECIFIER_RE = re.compile(r"""\s*(?P<quote>['"`])(?P<specifier>[^'"`\n]+)(?P=quote)""")

#: Comments and string/template literals, matched in one left-to-right pass so
#: that a ``//`` inside a string is not mistaken for a comment (and vice versa).
#: Each match is replaced by a sentinel quote plus spaces (newlines preserved),
#: which hides commented-out and string-embedded imports while keeping offsets
#: aligned with the original text.
JS_NOISE_RE = re.compile(
    r"""//[^\n]*"""
    r"""|/\*.*?\*/"""
    r"""|"(?:\\.|[^"\\\n])*\""""
    r"""|'(?:\\.|[^'\\\n])*'"""
    r"""|`(?:\\.|[^`\\])*`""",
    re.DOTALL,
)

#: ``using System.Data;`` / ``using Microsoft.EntityFrameworkCore;``
#: The optional ``global`` modifier (C# 10+) is accepted. Aliases
#: (``using X = Y;``), ``using static`` and ``using (var x = ...)`` statements
#: contain ``=``, ``static`` or ``(`` and therefore never match.
CSHARP_USING_RE = re.compile(
    r"^[ \t]*(?:global[ \t]+)?using[ \t]+"
    r"(?P<namespace>[A-Za-z_]\w*(?:[ \t]*\.[ \t]*[A-Za-z_]\w*)*)[ \t]*;",
    re.MULTILINE,
)

DEBT_CATEGORY = "high_complexity"
DEBT_DESCRIPTION = "File exceeds 300 lines of code"
DEBT_PROPOSED_FIX = "Consider refactoring into smaller modules"


@dataclass(slots=True)
class ScanResult:
    """Outcome of one scan, shaped to match the API response."""

    files_scanned: int = 0
    dependencies_found: int = 0
    debt_items_found: int = 0
    files_skipped: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.files_skipped += 1
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield supported source files under *root*, pruning vendored/cache dirs.

    ``os.walk`` is used with ``followlinks=False`` so a symlink cycle cannot make
    the traversal unbounded. C# build output (``obj/``, ``bin/``) is pruned via
    :data:`EXCLUDED_DIRS` so generated ``.cs`` files never enter the graph.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # In-place mutation prunes the traversal before descending.
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for filename in sorted(filenames):
            if Path(filename).suffix.lower() in SOURCE_SUFFIXES:
                yield Path(dirpath) / filename


def extract_imports(tree: ast.AST) -> list[str]:
    """Return the top-level imported module names of a parsed module.

    Only ``tree.body`` is inspected, so imports nested inside functions, classes
    or ``try`` blocks are deliberately ignored — the MVP models the module-level
    dependency graph. Order is preserved and duplicates are collapsed.
    """
    targets: dict[str, None] = {}  # insertion-ordered set

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets[alias.name] = None
        elif isinstance(node, ast.ImportFrom):
            # ``from . import x`` has module=None; keep the relative depth so the
            # edge is still distinguishable from an absolute import.
            prefix = "." * node.level
            module = f"{prefix}{node.module}" if node.module else prefix
            if module:
                targets[module] = None

    return list(targets)


def extract_csharp_usings(file_content: str) -> list[str]:
    """Return the namespaces imported by ``using`` directives in C# source.

    Regex-based on purpose: a full C# grammar is out of scope for the MVP, and
    ``using`` directives are line-oriented. Aliases (``using X = Y;``) are
    skipped so the graph only contains real namespace edges. Order is preserved
    and duplicates are collapsed.
    """
    targets: dict[str, None] = {}  # insertion-ordered set
    for match in CSHARP_USING_RE.finditer(file_content):
        # Normalise ``System . Data`` -> ``System.Data``.
        namespace = re.sub(r"\s+", "", match.group("namespace"))
        targets[namespace] = None
    return list(targets)


def extract_javascript_imports(file_content: str) -> list[str]:
    """Return the module specifiers imported by JS/TS source.

    Covers ES module syntax (``import x from 'mod'``, ``import 'mod'``,
    ``export { x } from 'mod'``) and CommonJS ``require('mod')``. Only the
    specifier is kept, so ``react``, ``@/components/Button`` and ``../utils``
    are stored verbatim. Order is preserved and duplicates are collapsed.
    """
    targets: dict[str, None] = {}  # insertion-ordered set

    # Comments and literals are blanked before matching, so a commented-out
    # import or an import quoted inside a string never becomes an edge. The
    # opening quote is kept as a sentinel (``"``) so the regexes can still see
    # that a specifier follows; the real specifier is then read from the
    # original text at the match end.
    code = JS_NOISE_RE.sub(
        lambda m: '"' + re.sub(r"[^\n]", " ", m.group(0)[1:]),
        file_content,
    )

    def specifier_at(offset: int) -> str | None:
        match = JS_SPECIFIER_RE.match(file_content, offset)
        return match.group("specifier").strip() if match else None

    for match in JS_IMPORT_RE.finditer(code):
        specifier = specifier_at(match.end())
        if specifier:
            targets[specifier] = None

    for match in JS_REQUIRE_RE.finditer(code):
        specifier = specifier_at(match.end())
        if specifier:
            targets[specifier] = None

    return list(targets)

def _insert_dependencies(db: Session, rows: list[dict[str, object]]) -> int:
    """Insert dependency rows, ignoring ones that already exist.

    Returns the number of rows actually created, which is what makes a re-scan
    report ``0`` instead of double-counting.
    """
    if not rows:
        return 0

    if db.get_bind().dialect.name == "postgresql":
        inserted = 0
        # Chunked: PostgreSQL caps a statement at 65,535 bind parameters, and a
        # large repository can easily produce more edges than that.
        for start in range(0, len(rows), _INSERT_CHUNK_SIZE):
            chunk = rows[start : start + _INSERT_CHUNK_SIZE]
            statement = (
                pg_insert(CodeDependency)
                .values(chunk)
                .on_conflict_do_nothing(
                    index_elements=["project_id", "source_file", "target_file"],
                )
            )
            inserted += db.execute(statement).rowcount or 0
        return inserted

    # Portable fallback (e.g. SQLite in tests): savepoint per row so one
    # conflict does not poison the surrounding transaction.
    inserted = 0
    for row in rows:
        try:
            with db.begin_nested():
                db.add(CodeDependency(**row))
            inserted += 1
        except IntegrityError:
            continue
    return inserted


def _existing_debt_paths(db: Session, project_id: uuid.UUID) -> set[str]:
    """File paths already flagged for this project, to keep re-scans idempotent."""
    statement = select(TechnicalDebtItem.file_path).where(
        TechnicalDebtItem.project_id == project_id,
        TechnicalDebtItem.category == DEBT_CATEGORY,
    )
    return {path for path in db.scalars(statement) if path is not None}


def scan_directory(
    project_id: uuid.UUID,
    directory_path: str,
    db: Session,
) -> ScanResult:
    """Analyse *directory_path* and persist the results for *project_id*.

    The caller owns the transaction boundary: this function flushes but does not
    commit, so the endpoint can roll back cleanly on failure.
    """
    root = Path(directory_path).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")

    result = ScanResult()
    dependency_rows: list[dict[str, object]] = []
    debt_items: list[TechnicalDebtItem] = []
    already_flagged = _existing_debt_paths(db, project_id)

    for file_path in iter_source_files(root):
        if result.files_scanned + result.files_skipped >= MAX_FILES:
            raise ValueError(f"scan aborted: more than {MAX_FILES} source files found")

        dependency_type = SOURCE_SUFFIXES.get(file_path.suffix.lower())
        if dependency_type is None:  # defensive: iterator already filters
            continue

        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                result.skip("too_large")
                continue
            source = file_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            result.skip("unreadable")
            continue

        if dependency_type == "import" and file_path.suffix.lower() == ".py":
            try:
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError):
                # Python 2 files, templates and generated stubs land here.
                result.skip("syntax_error")
                continue
            modules = extract_imports(tree)
        elif dependency_type == "using":
            # C# needs no parse step: the regex either matches or it does not.
            modules = extract_csharp_usings(source)
        else:
            # JS/TS: regex-based, no parse step either.
            modules = extract_javascript_imports(source)

        result.files_scanned += 1
        relative = file_path.relative_to(root).as_posix()

        for module in modules:
            dependency_rows.append(
                {
                    "project_id": project_id,
                    "source_file": relative,
                    "target_file": module,
                    "dependency_type": dependency_type,
                }
            )

        line_count = len(source.splitlines())
        if line_count > LOC_THRESHOLD and relative not in already_flagged:
            already_flagged.add(relative)
            debt_items.append(
                TechnicalDebtItem(
                    project_id=project_id,
                    title=f"High complexity: {relative}",
                    description=DEBT_DESCRIPTION,
                    severity=Severity.MEDIUM,
                    category=DEBT_CATEGORY,
                    file_path=relative,
                    line_number=line_count,
                    proposed_fix=DEBT_PROPOSED_FIX,
                )
            )

    result.dependencies_found = _insert_dependencies(db, dependency_rows)

    if debt_items:
        db.add_all(debt_items)
    result.debt_items_found = len(debt_items)

    db.flush()
    return result
