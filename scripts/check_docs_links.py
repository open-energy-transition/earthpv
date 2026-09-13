"""Check raw-HTML relative URLs in the docs.

`mkdocs build --strict` validates Markdown links and rewrites them for
`use_directory_urls`, but it does neither for URLs written inside raw HTML tags --
an `<iframe src="assets/...">` is copied through verbatim. A page at
`docs/data-registry.md` is served at `/data-registry/`, so such a URL resolved
against the page and 404'd silently in the browser while CI stayed green. That is
what this guard exists to catch.

Rules, for a page `docs/<parts>/<name>.md` served at `/<parts>/<name>/`:
  - a raw relative URL needs exactly `len(parts) + 1` levels of `../`
  - `index.md` is served at its directory's own URL, so it needs `len(parts)`
  - the resolved target must exist under `docs/`

Run: `python scripts/check_docs_links.py` (exit 1 on any finding).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
TAG = re.compile(r'<(?:iframe|img|a|script|source|embed|video|audio)\b[^>]*?\b(?:src|href)="([^"]+)"')
ABSOLUTE = ("http://", "https://", "//", "/", "#", "data:", "mailto:", "{{")


def _resolves(rel: str) -> bool:
    """True if `rel` names a file under docs/ or another page's directory URL."""
    target = DOCS / rel
    if target.exists():
        return True
    # A directory URL like "../atlas-germany/" is a page, not a file: it is served
    # from the Markdown source of the same name (or that directory's index.md).
    stem = rel.rstrip("/")
    return (DOCS / f"{stem}.md").exists() or (DOCS / stem / "index.md").exists()


def main() -> int:
    problems: list[str] = []
    for page in sorted(DOCS.rglob("*.md")):
        parts = page.relative_to(DOCS).parts[:-1]
        depth = len(parts) + (0 if page.name == "index.md" else 1)
        prefix = "../" * depth
        for lineno, line in enumerate(page.read_text().splitlines(), 1):
            for url in TAG.findall(line):
                if url.startswith(ABSOLUTE):
                    continue
                path, _, _ = url.partition("#")
                if not path:
                    continue
                if not path.startswith(prefix) or path[len(prefix):].startswith("../"):
                    problems.append(
                        f"{page}:{lineno}: raw HTML url {url!r} needs the prefix {prefix!r} "
                        f"(the page is served at /{'/'.join([*parts, page.stem])}/)"
                    )
                    continue
                rel = path[len(prefix):]
                if not _resolves(rel):
                    problems.append(f"{page}:{lineno}: raw HTML url {url!r} points at nothing")

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} raw-HTML link problem(s); mkdocs --strict cannot see these.", file=sys.stderr)
        return 1
    print("raw HTML links in docs/: all prefixed correctly and all targets present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
