import os
import shutil
import tempfile

import structlog
from git import Repo

log = structlog.get_logger()


async def clone_repo(repo_url: str, github_token: str) -> str:
    """Clone a GitHub repository and return the local path."""
    temp_dir = tempfile.mkdtemp(prefix="codemark_")
    clone_url = _inject_token(repo_url, github_token)

    log.info("cloning_repo", repo_url=repo_url, dest=temp_dir)
    try:
        Repo.clone_from(clone_url, temp_dir, depth=1)
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
