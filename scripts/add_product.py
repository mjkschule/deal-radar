"""Wird vom Workflow add-product.yml aufgerufen: Issue-Text -> products.yaml.

Liest den Issue-Text aus der Umgebungsvariable ISSUE_BODY und schreibt die neue
Produkt-ID nach $GITHUB_OUTPUT (id=...).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dealradar.config import ROOT, ConfigError  # noqa: E402
from dealradar.products_edit import append_product, parse_issue_form  # noqa: E402


def main() -> int:
    try:
        product = parse_issue_form(os.environ.get("ISSUE_BODY", ""))
        entry = append_product(ROOT / "products.yaml", product, comment="per GitHub-Issue hinzugefügt")
    except ConfigError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1
    print(f"Hinzugefügt: {entry}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"id={entry['id']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
