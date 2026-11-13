import base64
import hashlib
import json
import logging
import re
from http.client import HTTPException as HTTPProtocolError
from time import sleep
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
from urllib.request import Request as URLRequest

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import AppError

logger = logging.getLogger(__name__)


class RepositoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    github_id: int = Field(gt=0)
    full_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$")
    default_branch: str = Field(max_length=255)
    private: bool
    owner_type: Literal["User", "Organization"] = "User"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def valid_branch_name(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 255
        and value != "@"
        and not (
            value.startswith("/")
            or value.endswith(("/", "."))
            or ".." in value
            or "@{" in value
            or any(ord(c) <= 32 or ord(c) == 127 or c in "~^:?*[\\" for c in value)
            or any(
                not part or part.startswith(".") or part.endswith(".lock")
                for part in value.split("/")
            )
        )
    )


def github_get(
    token: str,
    operation: str,
    *,
    page: int = 1,
    repository_id: int = 0,
    full_name: str = "",
    branch: str = "",
    sha: str = "",
) -> object:
    """Closed operation list: no caller-controlled URL, method, body or redirects."""
    if operation == "identity":
        path = "/user"
    elif operation == "repositories" and 1 <= page <= 1000:
        path = (
            "/user/repos?affiliation=owner,collaborator,organization_member&per_page=100"
            f"&page={page}&sort=full_name"
        )
    elif operation == "repository" and repository_id > 0:
        path = f"/repositories/{repository_id}"
    elif (
        operation in {"branches", "tags", "commits"}
        and 1 <= page <= 1000
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", full_name)
        and full_name.split("/")[1] not in (".", "..")
        and (not branch or operation == "commits" and valid_branch_name(branch))
    ):
        path = f"/repos/{full_name}/{operation}?per_page=50&page={page}"
        if branch:
            path += f"&sha={quote(branch, safe='')}"
    elif (
        operation == "branch"
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", full_name)
        and full_name.split("/")[1] not in (".", "..")
        and valid_branch_name(branch)
    ):
        path = f"/repos/{full_name}/branches/{quote(branch, safe='')}"
    elif (
        operation in {"git_commit", "tree", "tree_shallow", "blob"}
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", full_name)
        and full_name.split("/")[1] not in (".", "..")
        and re.fullmatch(r"[0-9a-f]{40}", sha)
    ):
        path = (
            f"/repos/{full_name}/git/blobs/{sha}"
            if operation == "blob"
            else (
                f"/repos/{full_name}/git/commits/{sha}"
                if operation == "git_commit"
                else f"/repos/{full_name}/git/trees/{sha}"
                + ("?recursive=1" if operation == "tree" else "")
            )
        )
    else:
        raise AppError(400, "github_operation_not_allowed")
    request = URLRequest(
        "https://api.github.com" + path,
        method="GET",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "Test-Verity",
        },
    )
    for attempt in range(3):
        status, retryable = 502, True
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=15) as response:
                if operation in {"git_commit", "tree", "tree_shallow", "blob"}:
                    return json.load(response)
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise AppError(502, "github_invalid_response")
            return json.loads(raw)
        except HTTPError as exc:
            limited = exc.code == 429 or (
                exc.code == 403
                and (
                    exc.headers.get("X-RateLimit-Remaining") == "0"
                    or exc.headers.get("Retry-After")
                )
            )
            code = (
                "github_rate_limited"
                if limited
                else {
                    401: "github_token_invalid",
                    403: "github_access_denied",
                    404: "github_repository_unavailable",
                    409: "github_empty_repository",
                    422: "github_request_rejected",
                }.get(exc.code, "github_upstream_error")
            )
            retryable = (
                not limited
                and exc.code in {500, 502, 503, 504}
                and not exc.headers.get("Retry-After")
            )
            exc.close()
        except TimeoutError:
            status, code = 504, "github_timeout"
        except (URLError, ConnectionError, HTTPProtocolError):
            code = "github_connection_failed"
        except (ValueError, UnicodeError, OSError):
            raise AppError(502, "github_invalid_response") from None
        logger.warning(
            "github_read_failed operation=%s attempt=%s code=%s retry=%s",
            operation,
            attempt + 1,
            code,
            retryable and attempt < 2,
        )
        if not retryable or attempt == 2:
            raise AppError(status, code) from None
        sleep(2**attempt)


def code_scope(token: str, repository_id: int, ref: str, *, include_presence: bool = False) -> dict:
    """Resolve a code branch/commit and list regular text files through the GET whitelist."""
    if not valid_branch_name(ref):
        raise AppError(422, "code_ref_invalid")
    repo = repository_view(github_get(token, "repository", repository_id=repository_id))
    if repo.github_id != repository_id:
        raise AppError(502, "github_invalid_response")
    try:
        sha = (
            ref
            if re.fullmatch(r"[0-9a-f]{40}", ref)
            else github_get(token, "branch", full_name=repo.full_name, branch=ref)["commit"]["sha"]
        )
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError()
        commit = github_get(token, "git_commit", full_name=repo.full_name, sha=sha)
        tree_sha = commit["tree"]["sha"]
        if commit["sha"] != sha or not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
            raise ValueError()
        extensions = {
            "java",
            "kt",
            "kts",
            "py",
            "go",
            "rs",
            "cs",
            "c",
            "h",
            "cpp",
            "hpp",
            "dart",
            "swift",
            "m",
            "mm",
            "php",
            "rb",
            "js",
            "jsx",
            "ts",
            "tsx",
            "vue",
            "svelte",
            "html",
            "htm",
            "css",
            "scss",
            "json",
            "xml",
            "sql",
            "yaml",
            "yml",
            "toml",
            "properties",
            "md",
            "txt",
            "gradle",
        }
        found, present = [], []
        for entry in prototype_tree(token, repo.full_name, tree_sha, ""):
            path = entry["path"]
            if include_presence:
                if not isinstance(path, str):
                    raise ValueError()
                present.append(path)
            if entry.get("type") != "blob" or entry.get("mode") not in {"100644", "100755"}:
                continue
            if path.rsplit(".", 1)[-1].lower() not in extensions:
                continue
            if (
                not valid_material_path(path)
                or not re.fullmatch(r"[0-9a-f]{40}", entry["sha"])
                or type(entry.get("size")) is not int
            ):
                raise ValueError()
            found.append({"path": path, "sha": entry["sha"], "size": entry["size"]})
        return {
            "commit": sha,
            "full_name": repo.full_name,
            "files": sorted(found, key=lambda f: f["path"]),
            **({"present_paths": present} if include_presence else {}),
        }
    except (KeyError, TypeError, ValueError):
        raise AppError(502, "github_invalid_response") from None


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def prototype_content(token: str, full_name: str, sha: str) -> bytes:
    value = github_get(token, "blob", full_name=full_name, sha=sha)
    try:
        if value["sha"] != sha or value["encoding"] != "base64":
            raise ValueError()
        content = base64.b64decode("".join(value["content"].split()), validate=True)
        actual = blob_sha(content)
        if actual != sha or value["size"] != len(content):
            raise ValueError()
        return content
    except (TypeError, KeyError, ValueError):
        raise AppError(502, "github_invalid_response") from None


def repository_view(
    raw: object, owner: str | None = None, kind: str | None = None
) -> RepositoryView:
    try:
        if not isinstance(raw, dict) or not isinstance(raw.get("owner"), dict):
            raise ValueError("invalid_repository")
        actual_owner = raw["owner"].get("login", "")
        if not isinstance(actual_owner, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", actual_owner
        ):
            raise ValueError("invalid_owner")
        if owner is not None and (
            actual_owner.lower() != owner.lower()
            or raw["owner"].get("type") != ("User" if kind == "personal" else "Organization")
        ):
            raise AppError(403, "github_repository_not_allowed")
        value = RepositoryView(
            github_id=raw["id"],
            full_name=raw["full_name"],
            default_branch=raw.get("default_branch") or "",
            private=raw["private"],
            owner_type=raw["owner"]["type"],
        )
        if value.full_name.split("/")[0].lower() != actual_owner.lower():
            raise ValueError("invalid_owner")
        return value
    except (KeyError, ValueError, TypeError, AttributeError, ValidationError):
        raise AppError(502, "github_invalid_response") from None


def check_repository(
    token: str,
    repository_id: int,
    owner: str | None = None,
    kind: str | None = None,
    branch: str | None = None,
) -> RepositoryView:
    repo = repository_view(
        github_get(token, "repository", repository_id=repository_id), owner, kind
    )
    if repo.github_id != repository_id:
        raise AppError(502, "github_invalid_response")
    ref = branch if branch is not None else repo.default_branch
    if not ref:
        raise AppError(422, "github_empty_repository")
    result = github_get(token, "branch", full_name=repo.full_name, branch=ref)
    if (
        not isinstance(result, dict)
        or result.get("name") != ref
        or not isinstance(result.get("commit"), dict)
        or not re.fullmatch(r"[0-9a-f]{40}", str(result["commit"].get("sha", "")))
    ):
        raise AppError(502, "github_invalid_response")
    return repo


def valid_material_path(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 500
        and not any(ord(c) < 32 or ord(c) == 127 or c == "\\" for c in value)
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def prototype_tree(token: str, full_name: str, root_sha: str, path: str) -> list[dict]:
    def entries(raw: object, expected_sha: str) -> tuple[list[dict], bool]:
        if (
            not isinstance(raw, dict)
            or raw.get("sha") != expected_sha
            or not isinstance(raw.get("tree"), list)
            or type(raw.get("truncated")) is not bool
            or any(not isinstance(entry, dict) for entry in raw["tree"])
        ):
            raise AppError(502, "github_invalid_response")
        return raw["tree"], raw["truncated"]

    rows, truncated = entries(
        github_get(token, "tree", full_name=full_name, sha=root_sha), root_sha
    )
    if not truncated:
        return rows
    # Ignore the partial recursive result; walk complete directories at the same commit.
    found = []
    pending = [(root_sha, "", frozenset())]
    while pending:
        tree_sha, prefix, ancestors = pending.pop()
        if tree_sha in ancestors:
            raise AppError(502, "github_invalid_response")
        children, partial = entries(
            github_get(token, "tree_shallow", full_name=full_name, sha=tree_sha), tree_sha
        )
        if partial:
            raise AppError(422, "prototype_tree_incomplete")
        for child in children:
            name = child.get("path")
            if not isinstance(name, str) or "/" in name or not valid_material_path(name):
                raise AppError(502, "github_invalid_response")
            filename = f"{prefix}/{name}" if prefix else name
            if path and not (
                filename == path
                or filename.startswith(path + "/")
                or path.startswith(filename + "/")
            ):
                continue
            if child.get("type") == "tree":
                child_sha = child.get("sha")
                if not isinstance(child_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", child_sha):
                    raise AppError(502, "github_invalid_response")
                pending.append((child_sha, filename, ancestors | {tree_sha}))
            else:
                found.append({**child, "path": filename})
    return found


def repository_versions(token: str, repository_id: int, kind: str, ref: str, page: int) -> dict:
    if kind not in {"branches", "tags", "commits"} or not 1 <= page <= 1000:
        raise AppError(422, "github_version_query_invalid")
    if ref and (kind != "commits" or not valid_branch_name(ref)):
        raise AppError(422, "github_version_query_invalid")
    repo = repository_view(github_get(token, "repository", repository_id=repository_id))
    if repo.github_id != repository_id:
        raise AppError(502, "github_invalid_response")
    rows = github_get(token, kind, full_name=repo.full_name, branch=ref, page=page)
    if not isinstance(rows, list) or len(rows) > 50:
        raise AppError(502, "github_invalid_response")
    items = []
    try:
        for row in rows:
            sha = row["sha"] if kind == "commits" else row["commit"]["sha"]
            name = sha[:12] if kind == "commits" else row["name"]
            message = row["commit"]["message"] if kind == "commits" else ""
            author = (
                row["commit"].get("author") or row["commit"].get("committer") or {}
                if kind == "commits"
                else {}
            )
            date = author.get("date", "")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError()
            if not isinstance(name, str) or not valid_branch_name(name):
                raise ValueError()
            if not isinstance(message, str) or not isinstance(date, str) or len(date) > 80:
                raise ValueError()
            items.append(
                {
                    "name": name,
                    "sha": sha,
                    "message": message.splitlines()[0][:300] if message else "",
                    "date": date,
                }
            )
    except (KeyError, TypeError, AttributeError, ValueError):
        raise AppError(502, "github_invalid_response") from None
    return {
        "items": items,
        "has_more": len(rows) == 50,
        "page": page,
        "kind": kind,
        "repository_id": repository_id,
        "ref": ref,
    }


def prototype_scope(
    token: str,
    repository_id: int,
    branch: str,
    path: str,
    *,
    include_presence: bool = False,
    allow_empty: bool = False,
) -> dict:
    """Resolve once, then read the tree at that exact commit; never execute repository data."""
    if not valid_branch_name(branch) or (path and not valid_material_path(path)):
        raise AppError(422, "prototype_scope_invalid")
    repo = repository_view(github_get(token, "repository", repository_id=repository_id))
    if repo.github_id != repository_id:
        raise AppError(502, "github_invalid_response")
    try:
        if re.fullmatch(r"[0-9a-f]{40}", branch):
            sha = branch
        else:
            branch_data = github_get(token, "branch", full_name=repo.full_name, branch=branch)
            sha = branch_data["commit"]["sha"]
            if branch_data["name"] != branch or not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError()
        commit = github_get(token, "git_commit", full_name=repo.full_name, sha=sha)
        tree_sha = commit["tree"]["sha"]
        if commit["sha"] != sha or not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
            raise ValueError()
        found, present = [], []
        for entry in prototype_tree(token, repo.full_name, tree_sha, path):
            filename = entry["path"]
            if not isinstance(filename, str):
                raise ValueError()
            if path and not (filename == path or filename.startswith(path + "/")):
                continue
            if include_presence:
                present.append(filename)
            if entry.get("type") != "blob" or entry.get("mode") not in {"100644", "100755"}:
                continue
            if filename.rsplit(".", 1)[-1].lower() not in {
                "html",
                "htm",
                "css",
                "js",
                "jsx",
                "ts",
                "tsx",
                "vue",
                "json",
                "md",
                "svg",
            }:
                continue
            if not valid_material_path(filename) or not re.fullmatch(r"[0-9a-f]{40}", entry["sha"]):
                raise ValueError()
            if type(entry.get("size")) is not int or entry["size"] < 0:
                raise ValueError()
            found.append({"path": filename, "sha": entry["sha"], "size": entry["size"]})
    except (KeyError, TypeError, ValueError):
        raise AppError(502, "github_invalid_response") from None
    if not found and not allow_empty:
        raise AppError(422, "prototype_scope_empty")
    return {
        "commit": sha,
        "full_name": repo.full_name,
        "files": sorted(found, key=lambda f: f["path"]),
        **({"present_paths": present} if include_presence else {}),
    }
