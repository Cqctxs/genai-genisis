import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";

const SCHEME = "codemark-optimized";

export interface FileDiff {
  relativePath: string;
  originalContent: string;
  optimizedContent: string;
}

class OptimizedContentProvider implements vscode.TextDocumentContentProvider {
  private contents = new Map<string, string>();

  setContent(uri: string, content: string) {
    this.contents.set(uri, content);
  }

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.contents.get(uri.toString()) || "";
  }
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
      continue;
    }

    // Normalize line endings to LF before comparing
    const normOriginal = original.replace(/\r\n/g, "\n");
    const normOptimized = optimized.replace(/\r\n/g, "\n");

    // Skip files with no semantic changes
    if (normOriginal === normOptimized) continue;

    const isCRLF = original.includes("\r\n");
    const matchedOptimized = isCRLF
      ? normOptimized.replace(/\n/g, "\r\n")
      : normOptimized;

    diffs.push({
      relativePath: relPath,
      originalContent: original,
      optimizedContent: matchedOptimized,
    });
  }

  if (diffs.length === 0) {
    vscode.window.showInformationMessage(
      "CodeMark: No optimizations to apply.",
    );
    return;
  }

  // Register a virtual content provider so VS Code reads optimized
  // content directly from memory — no temp files needed.
  const provider = new OptimizedContentProvider();
  const registration = vscode.workspace.registerTextDocumentContentProvider(
    SCHEME,
    provider,
  );

  try {
    // Open a diff tab for every changed file
    for (const diff of diffs) {
      const originalUri = vscode.Uri.file(
        path.join(workspaceRoot, diff.relativePath),
      );
      const optimizedUri = vscode.Uri.parse(`${SCHEME}:/${diff.relativePath}`);
      provider.setContent(optimizedUri.toString(), diff.optimizedContent);

      await vscode.commands.executeCommand(
        "vscode.diff",
        originalUri,
        optimizedUri,
        `CodeMark: ${diff.relativePath} (original ↔ optimized)`,
      );
    }

    // Persistent prompt — re-shows when dismissed so the user can
    // freely click around diff tabs and come back when ready.
    let decided = false;
    while (!decided) {
      const choice = await vscode.window.showInformationMessage(
        `CodeMark: ${diffs.length} file(s) optimized — review the diffs, then choose.`,
        "Accept All",
        "Pick Files",
        "Skip All",
      );

      if (choice === "Accept All") {
        for (const diff of diffs) {
          const fullPath = path.join(workspaceRoot, diff.relativePath);
          await fs.promises.writeFile(
            fullPath,
            diff.optimizedContent,
            "utf-8",
          );
        }
        vscode.window.showInformationMessage(
          `CodeMark: Applied optimizations to ${diffs.length} file(s).`,
        );
        decided = true;
      } else if (choice === "Pick Files") {
        const items = diffs.map((d) => ({
          label: d.relativePath,
          picked: true,
        }));
        const selected = await vscode.window.showQuickPick(items, {
          canPickMany: true,
          placeHolder: "Select files to apply (Esc to go back)",
        });
        if (selected) {
          const selectedPaths = new Set(selected.map((s) => s.label));
          for (const diff of diffs) {
            if (selectedPaths.has(diff.relativePath)) {
              const fullPath = path.join(workspaceRoot, diff.relativePath);
              await fs.promises.writeFile(
                fullPath,
                diff.optimizedContent,
                "utf-8",
              );
            }
          }
          vscode.window.showInformationMessage(
            selected.length > 0
              ? `CodeMark: Applied optimizations to ${selected.length} file(s).`
              : "CodeMark: No optimizations applied.",
          );
          decided = true;
        }
        // QuickPick dismissed (Esc) → loop back to main prompt
      } else if (choice === "Skip All") {
        vscode.window.showInformationMessage(
          "CodeMark: No optimizations applied.",
        );
        decided = true;
      }
      // choice === undefined (clicked away) → loop and re-show
    }

    // Close all CodeMark diff tabs
    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        if (tab.input instanceof vscode.TabInputTextDiff) {
          const modified = (tab.input as vscode.TabInputTextDiff).modified;
          if (modified.scheme === SCHEME) {
            await vscode.window.tabGroups.close(tab);
          }
        }
      }
    }
  } finally {
    registration.dispose();
  }
}

export async function cleanupTempDir(workspaceRoot: string): Promise<void> {
  const tmpDir = path.join(workspaceRoot, ".codemark-tmp");
  try {
    await fs.promises.rm(tmpDir, { recursive: true, force: true });
  } catch {
    // ignore — dir may not exist if virtual provider was used
  }
}
