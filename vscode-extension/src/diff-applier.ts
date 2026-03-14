import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";

export interface FileDiff {
  relativePath: string;
  originalContent: string;
  optimizedContent: string;
}

export async function applyDiffs(
  workspaceRoot: string,
  optimizedFiles: Record<string, string>,
): Promise<void> {
  const diffs: FileDiff[] = [];

  for (const [relPath, optimized] of Object.entries(optimizedFiles)) {
    const fullPath = path.join(workspaceRoot, relPath);

    let original: string;
    try {
      original = await fs.promises.readFile(fullPath, "utf-8");
    } catch {
      // File doesn't exist locally (shouldn't happen for local analysis)
      continue;
    }

    // Skip files with no changes
    if (original === optimized) continue;

    diffs.push({
      relativePath: relPath,
      originalContent: original,
      optimizedContent: optimized,
    });
  }

  if (diffs.length === 0) {
    vscode.window.showInformationMessage(
      "CodeMark: No optimizations to apply.",
    );
    return;
  }

  // Show diffs one at a time, letting the user accept or reject each
  for (const diff of diffs) {
    const accepted = await showDiffAndPrompt(workspaceRoot, diff);
    if (accepted) {
      const fullPath = path.join(workspaceRoot, diff.relativePath);
      await fs.promises.writeFile(fullPath, diff.optimizedContent, "utf-8");
      vscode.window.showInformationMessage(
        `CodeMark: Applied optimization to ${diff.relativePath}`,
      );
    }
  }
}

async function showDiffAndPrompt(
  workspaceRoot: string,
  diff: FileDiff,
): Promise<boolean> {
  // Write the optimized version to a temp file for the diff view
  const originalUri = vscode.Uri.file(
    path.join(workspaceRoot, diff.relativePath),
  );

  const tmpDir = path.join(workspaceRoot, ".codemark-tmp");
  await fs.promises.mkdir(tmpDir, { recursive: true });

  const tmpPath = path.join(tmpDir, diff.relativePath);
  await fs.promises.mkdir(path.dirname(tmpPath), { recursive: true });
  await fs.promises.writeFile(tmpPath, diff.optimizedContent, "utf-8");
  const optimizedUri = vscode.Uri.file(tmpPath);

  // Open VS Code's built-in diff editor
  await vscode.commands.executeCommand(
    "vscode.diff",
    originalUri,
    optimizedUri,
    `CodeMark: ${diff.relativePath} (original ↔ optimized)`,
  );

  // Ask the user via quick pick
  const choice = await vscode.window.showInformationMessage(
    `Apply optimization to ${diff.relativePath}?`,
    { modal: true },
    "Accept",
    "Skip",
  );

  // Clean up temp file
  try {
    await fs.promises.unlink(tmpPath);
  } catch {
    // ignore
  }

  return choice === "Accept";
}

export async function cleanupTempDir(workspaceRoot: string): Promise<void> {
  const tmpDir = path.join(workspaceRoot, ".codemark-tmp");
  try {
    await fs.promises.rm(tmpDir, { recursive: true, force: true });
  } catch {
    // ignore
  }
}
