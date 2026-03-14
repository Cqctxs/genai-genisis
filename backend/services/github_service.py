import asyncio
import os
import shutil
import tempfile

import httpx
import structlog
from git import Repo

log = structlog.get_logger()


async def list_user_repos(github_token: str) -> list[dict]:
    """Fetch the authenticated user's repositories from GitHub, sorted by last push."""
    repos: list[dict] = []
    url = "https://api.github.com/user/repos"
    params = {
        "sort": "pushed",
        "direction": "desc",
        "per_page": 100,
        "affiliation": "owner,collaborator,organization_member",
    }
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        page = 1
        while True:
            params["page"] = page
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 401:
                raise PermissionError("GitHub token is invalid or expired")
            resp.raise_for_status()

            batch = resp.json()
            if not batch:
                break

            for r in batch:
                repos.append({
                    "id": r["id"],
                    "full_name": r["full_name"],
                    "name": r["name"],
                    "owner": r["owner"]["login"],
                    "owner_avatar": r["owner"]["avatar_url"],
                    "html_url": r["html_url"],
                    "description": r.get("description") or "",
                    "language": r.get("language") or "",
                    "stargazers_count": r.get("stargazers_count", 0),
                    "private": r["private"],
                    "fork": r.get("fork", False),
                    "updated_at": r.get("pushed_at") or r.get("updated_at", ""),
                })

            if len(batch) < 100:
                break
            page += 1

    log.info("repos_fetched", count=len(repos))
    return repos


async def clone_repo(repo_url: str, github_token: str) -> str:
    """Clone a GitHub repository and return the local path."""
    temp_dir = tempfile.mkdtemp(prefix="codemark_")
    clone_url = _inject_token(repo_url, github_token)

    log.info("cloning_repo", repo_url=repo_url, dest=temp_dir)
    try:
        await asyncio.to_thread(Repo.clone_from, clone_url, temp_dir, depth=1)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"Failed to clone repository: {e}") from e

    log.info("clone_complete", path=temp_dir)
    return temp_dir


def _inject_token(repo_url: str, token: str) -> str:
    """Insert the GitHub token into the clone URL for private repo access."""
    url = str(repo_url)
    if url.startswith("https://github.com/"):
        return url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
    return url


def get_file_tree(repo_path: str, extensions: set[str] | None = None) -> list[str]:
    """Walk the repo and return relative file paths, filtered by extension."""
    if extensions is None:
        extensions = {".py", ".js", ".ts", ".jsx", ".tsx"}

    files: list[str] = []
    skip_dirs = {"node_modules", ".git", "__pycache__", ".next", "venv", ".venv", "dist", "build"}

    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in filenames:
            if any(fname.endswith(ext) for ext in extensions):
                rel_path = os.path.relpath(os.path.join(root, fname), repo_path)
                files.append(rel_path.replace("\\", "/"))

    return sorted(files)


def read_file(repo_path: str, rel_path: str) -> str:
    """Read a file's contents from the cloned repo."""
    full_path = os.path.join(repo_path, rel_path)
    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def cleanup_repo(repo_path: str) -> None:
    """Remove a cloned repository from disk."""
    shutil.rmtree(repo_path, ignore_errors=True)
    log.info("repo_cleaned_up", path=repo_path)
