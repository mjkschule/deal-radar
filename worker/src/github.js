// GitHub-API: Dateien lesen/schreiben (Commit) und einen Suchlauf auslösen (repository_dispatch).
// Benötigt das Secret GITHUB_TOKEN (Fine-grained Token, nur für das Repo deal-radar,
// Berechtigung "Contents: Read and write").

export class GitHubError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function b64decodeUtf8(b64) {
  const bin = atob(b64.replace(/\n/g, ""));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

function b64encodeUtf8(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

export function makeGitHub(env, fetchImpl = fetch) {
  const repo = env.GITHUB_REPO;
  const branch = env.GITHUB_BRANCH || "main";
  const base = `https://api.github.com/repos/${repo}`;
  const headers = {
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "deal-radar-bot",
  };

  async function call(method, path, body) {
    const res = await fetchImpl(base + path, {
      method,
      headers: body ? { ...headers, "Content-Type": "application/json" } : headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    if (!res.ok) throw new GitHubError(`GitHub ${method} ${path}: HTTP ${res.status} ${data?.message || ""}`.trim(), res.status);
    return data;
  }

  return {
    /** { text, sha } – oder null, wenn die Datei (noch) nicht existiert. */
    async getFile(path) {
      try {
        const d = await call("GET", `/contents/${path}?ref=${encodeURIComponent(branch)}`);
        return { text: b64decodeUtf8(d.content || ""), sha: d.sha };
      } catch (e) {
        if (e.status === 404) return null;
        throw e;
      }
    },
    async putFile(path, text, sha, message) {
      const body = { message, content: b64encodeUtf8(text), branch };
      if (sha) body.sha = sha;
      const d = await call("PUT", `/contents/${path}`, body);
      return d.commit.sha;
    },
    /** Startet radar.yml (on: repository_dispatch, types: [radar]). */
    async dispatch(grund) {
      await call("POST", "/dispatches", { event_type: "radar", client_payload: { grund } });
    },
  };
}

/**
 * Liest eine Datei, wendet `change(text)` an und committet das Ergebnis.
 * Hat sich die Datei zwischendurch geändert (HTTP 409), wird einmal neu versucht.
 * `change` gibt { text, ... } zurück; das ganze Ergebnis wird weitergereicht.
 */
export async function editFile(gh, path, message, change) {
  for (let attempt = 0; ; attempt++) {
    const file = await gh.getFile(path);
    if (!file) throw new GitHubError(`${path} nicht gefunden`, 404);
    const result = change(file.text);
    if (result.text === file.text) return result;
    try {
      result.commit = await gh.putFile(path, result.text, file.sha, message);
      return result;
    } catch (e) {
      if ((e.status === 409 || e.status === 422) && attempt === 0) continue;
      throw e;
    }
  }
}
