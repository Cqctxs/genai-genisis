import * as vscode from "vscode";
import {
  gatherWorkspaceFiles,
  gatherSingleFile,
  detectLanguage,
} from "./file-gatherer";
import {
  startLocalAnalysis,
  streamJob,
  getResults,
  type JobResult,
} from "./api-client";
import { applyDiffs, cleanupTempDir } from "./diff-applier";

export function activate(context: vscode.ExtensionContext) {
  const optimizeWorkspace = vscode.commands.registerCommand(
    "codemark.optimize",
    () => runOptimization("workspace"),
  );

  const optimizeFile = vscode.commands.registerCommand(
    "codemark.optimizeFile",
    () => runOptimization("file"),
  );

  context.subscriptions.push(optimizeWorkspace, optimizeFile);
}

export function deactivate() {}

async function runOptimization(scope: "workspace" | "file") {
  const config = vscode.workspace.getConfiguration("codemark");
  const backendUrl = config.get<string>("backendUrl", "http://localhost:8000");
  const bias = config.get<string>("optimizationBias", "balanced");

  // Get workspace root
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    vscode.window.showErrorMessage("CodeMark: Open a workspace folder first.");
    return;
  }
  const workspaceRoot = workspaceFolders[0].uri.fsPath;

  // Gather files
  let files: Record<string, string>;
  try {
    if (scope === "file") {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showErrorMessage("CodeMark: No active file to optimize.");
        return;
      }
      files = await gatherSingleFile(editor.document.uri.fsPath, workspaceRoot);
    } else {
      files = await gatherWorkspaceFiles(workspaceRoot);
    }
  } catch (err: any) {
    vscode.window.showErrorMessage(
      `CodeMark: Failed to read files — ${err.message}`,
    );
    return;
  }

  const fileCount = Object.keys(files).length;
  if (fileCount === 0) {
    vscode.window.showWarningMessage(
      "CodeMark: No supported files found (.py, .js, .ts, .jsx, .tsx).",
    );
    return;
  }

  const language = detectLanguage(files);

  // Run with progress
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "CodeMark",
      cancellable: true,
    },
    async (progress, token) => {
      progress.report({ message: `Sending ${fileCount} files to backend...` });

      // Start analysis
      let jobId: string;
      try {
        const resp = await startLocalAnalysis(
          backendUrl,
          files,
          language,
          bias,
        );
        jobId = resp.job_id;
      } catch (err: any) {
        vscode.window.showErrorMessage(
          `CodeMark: Backend connection failed — ${err.message}\n\nMake sure the backend is running at ${backendUrl}`,
        );
        return;
      }

      // Stream progress
      const result = await new Promise<JobResult | null>((resolve) => {
        let cancelStream: (() => void) | null = null;

        token.onCancellationRequested(() => {
          cancelStream?.();
          resolve(null);
        });

        cancelStream = streamJob(
          backendUrl,
          jobId,
          (msg) => {
            progress.report({ message: msg });
          },
          async () => {
            // Stream complete — fetch full results
            try {
              progress.report({ message: "Fetching results..." });
              const jobResult = await getResults(backendUrl, jobId);
              resolve(jobResult);
            } catch (err: any) {
              vscode.window.showErrorMessage(
                `CodeMark: Failed to fetch results — ${err.message}`,
              );
              resolve(null);
            }
          },
          (err) => {
            vscode.window.showErrorMessage(
              `CodeMark: Stream error — ${err.message}`,
            );
            resolve(null);
          },
        );
      });

      if (!result) return;

      // Show summary
      const optimizedCount = Object.keys(result.optimized_files || {}).length;
      if (optimizedCount === 0) {
        vscode.window.showInformationMessage(
          "CodeMark: Analysis complete — no optimizations found.",
        );
        return;
      }

      const score = result.comparison?.benchy_score;
      const summary = score
        ? `Score: ${score.overall_before} → ${score.overall_after} | ${optimizedCount} file(s) optimized`
        : `${optimizedCount} file(s) optimized`;

      progress.report({ message: `Done! ${summary}` });

      // Show hotspot summary in output channel
      const output = vscode.window.createOutputChannel("CodeMark");
      output.clear();
      output.appendLine("═══ CodeMark Optimization Results ═══\n");

      if (result.comparison?.summary) {
        output.appendLine(result.comparison.summary);
        output.appendLine("");
      }

      if (result.comparison?.functions) {
        output.appendLine("Per-function results:");
        for (const fn of result.comparison.functions) {
          const speedup =
            fn.speedup_factor > 1
              ? `${fn.speedup_factor.toFixed(1)}x faster`
              : "no change";
          output.appendLine(
            `  ${fn.file}:${fn.function_name} — ${fn.old_time_ms.toFixed(2)}ms → ${fn.new_time_ms.toFixed(2)}ms (${speedup})`,
          );
        }
        output.appendLine("");
      }

      if (score) {
        output.appendLine(
          `CodeMark Score: ${score.overall_before} → ${score.overall_after}`,
        );
      }

      output.show(true);

      // Apply diffs
      await applyDiffs(workspaceRoot, result.optimized_files);
      await cleanupTempDir(workspaceRoot);
    },
  );
}
