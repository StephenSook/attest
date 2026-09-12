"""The config template must name every variable the shipped code reads.

A template that omits what the code reads is a template that drifts, and the
drift is invisible: nobody re-reads .env.example, so a judge copying it gets a
stack whose behavior is configured by defaults they were never shown. One of
these variables decides whether attestation certificates are signed at all, so
the gap is not cosmetic.

The reverse direction is the one that costs credibility. A template still
advertising a variable nothing reads is a claim the code contradicts, which is
exactly what a reviewer diffing the template against the README would find.

This test is the enforcement, in both directions, on the commit that causes it.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_ENV_EXAMPLE = _ROOT / ".env.example"

# Where a variable is actually read: Python env reads, and the compose file's
# own environment block. Comments and prose are deliberately not scanned, so a
# name only mentioned in a docstring does not count as used.
_PY_SOURCES = ("backend", "mock_calle", "scripts", "eval")
_PY_READ = re.compile(
    r"""(?:os\.environ\.get|os\.getenv)\(\s*["'](?P<a>[A-Z][A-Z0-9_]+)["']"""
    r"""|os\.environ\[\s*["'](?P<b>[A-Z][A-Z0-9_]+)["']"""
)
_COMPOSE_KEY = re.compile(r"^\s{6,}(?P<name>(?:ATTEST|CALLE)_[A-Z0-9_]+)\s*:")
_OURS = re.compile(r"^(?:ATTEST|CALLE)_")


def _declared() -> set[str]:
    names = set()
    for line in _ENV_EXAMPLE.read_text().splitlines():
        declaration = re.match(r"^(?P<name>[A-Z][A-Z0-9_]*)=", line)
        if declaration:
            names.add(declaration.group("name"))
    return names


def _read_by_the_code() -> set[str]:
    names = set()
    for folder in _PY_SOURCES:
        for path in (_ROOT / folder).rglob("*.py"):
            for read in _PY_READ.finditer(path.read_text()):
                name = read.group("a") or read.group("b")
                if _OURS.match(name):
                    names.add(name)
    for line in (_ROOT / "compose.yml").read_text().splitlines():
        key = _COMPOSE_KEY.match(line)
        if key:
            names.add(key.group("name"))
    return names


def test_the_template_names_every_variable_the_code_reads() -> None:
    missing = sorted(_read_by_the_code() - _declared())
    assert not missing, f"read by the code but absent from .env.example: {missing}"


def test_the_template_advertises_nothing_the_code_ignores() -> None:
    stale = sorted({n for n in _declared() if _OURS.match(n)} - _read_by_the_code())
    assert not stale, f"declared in .env.example but read nowhere: {stale}"


def test_the_template_carries_no_real_phone_number() -> None:
    """The only long digit run may be the reserved fictional number."""
    digits = set(re.findall(r"[0-9]{10,}", _ENV_EXAMPLE.read_text()))
    assert digits <= {"15550101234"}, digits
