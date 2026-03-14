import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";

const SUPPORTED_EXTENSIONS = new Set([".py", ".js", ".ts", ".jsx", ".tsx"]);

const SKIP_DIRS = new Set([
  "node_modules",
  ".git",
  "__pycache__",
  ".next",
  "venv",
  ".venv",
  "dist",
  "build",
  ".mypy_cache",
  ".pytest_cache",
  "coverage",
  ".tox",
  "egg-info",
]);

const MAX_FILE_SIZE = 100 * 1024; // 100KB per file
const MAX_FILES = 50;

export interface FileMap {
  [relativePath: string]: string;
}

export function detectLanguage(files: FileMap): string {
  let pyCount = 0;
  let jsCount = 0;

  for (const filePath of Object.keys(files)) {
    const ext = path.extname(filePath).toLowerCase();
    if (ext === ".py") pyCount++;
    if ([".js", ".ts", ".jsx", ".tsx"].includes(ext)) jsCount++;
  }

  return pyCount >= jsCount ? "python" : "javascript";
}

export async function gatherWorkspaceFiles(
  workspaceRoot: string,
): Promise<FileMap> {
  const files: FileMap = {};
  await walkDir(workspaceRoot, workspaceRoot, files);
  return files;
}

export async function gatherSingleFile(
  filePath: string,
  workspaceRoot: string,
): Promise<FileMap> {
  const content = await fs.promises.readFile(filePath, "utf-8");
  const relPath = path.relative(workspaceRoot, filePath).replace(/\\/g, "/");
  return { [relPath]: content };
}

async function walkDir(
  dir: string,
  root: string,
  files: FileMap,
): Promise<void> {
  if (Object.keys(files).length >= MAX_FILES) return;

  let entries: fs.Dirent[];
  try {
    entries = await fs.promises.readdir(dir, { withFileTypes: true });
  } catch {
    return;
  }

  for (const entry of entries) {
    if (Object.keys(files).length >= MAX_FILES) return;

    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name) || entry.name.startsWith(".")) continue;
      await walkDir(path.join(dir, entry.name), root, files);
    } else if (entry.isFile()) {
      const ext = path.extname(entry.name).toLowerCase();
      if (!SUPPORTED_EXTENSIONS.has(ext)) continue;

      const fullPath = path.join(dir, entry.name);
      try {
        const stat = await fs.promises.stat(fullPath);
        if (stat.size > MAX_FILE_SIZE) continue;

        const content = await fs.promises.readFile(fullPath, "utf-8");
        const relPath = path.relative(root, fullPath).replace(/\\/g, "/");
        files[relPath] = content;
      } catch {
        // skip unreadable files
      }
    }
  }
}
