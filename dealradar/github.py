"""Eine Datei per GitHub-API committen (für Änderungen an products.yaml per Telegram).

In GitHub Actions stehen GITHUB_TOKEN, GITHUB_REPOSITORY und GITHUB_REF_NAME bereit.
Lokal fehlen sie – dann wird nur die Datei geändert und nichts hochgeladen.
"""

from __future__ import annotations

import base64
import json
import urllib.parse

from .http import Http

API = "https://api.github.com"


class GitHubError(Exception):
    pass


def commit_file(http: Http, token: str, repo: str, branch: str, path: str, content: str, message: str) -> str | None:
    """Speichert `content` als `path` im Repo. Gibt die Commit-ID zurück (None = keine Änderung)."""
    url = f"{API}/repos/{repo}/contents/{urllib.parse.quote(path)}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    status, text = http.request(f"{url}?ref={urllib.parse.quote(branch)}", headers=headers)
    if status != 200:
        raise GitHubError(f"Datei {path} nicht lesbar (HTTP {status})")
    current = json.loads(text)
    encoded = base64.b64encode(content.encode("utf-8")).decode()
    if base64.b64decode(current.get("content", "")) == content.encode("utf-8"):
        return None  # schon auf dem Stand
    body = json.dumps({"message": message, "content": encoded, "sha": current["sha"], "branch": branch}).encode()
    status, text = http.request(url, data=body, method="PUT",
                                headers={**headers, "Content-Type": "application/json"})
    if status not in (200, 201):
        try:
            detail = json.loads(text).get("message", "")
        except json.JSONDecodeError:
            detail = text[:200]
        raise GitHubError(f"Commit fehlgeschlagen (HTTP {status}): {detail}")
    return json.loads(text)["commit"]["sha"]
