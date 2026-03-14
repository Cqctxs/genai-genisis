"use client";

import { ExternalLink, GitPullRequest, FileCode, AlertCircle, ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { ComparisonReport } from "@/lib/api";

interface PullRequestViewProps {
  prUrl: string;
  optimizedFiles: Record<string, string>;
  comparison: ComparisonReport | null;
  prStatus?: string;
  prError?: string | null;
}

export function PullRequestView({
  prUrl,
  optimizedFiles,
  comparison,
  prStatus,
  prError,
}: PullRequestViewProps) {
  const files = Object.keys(optimizedFiles);
  const score = comparison?.benchy_score;

  if (!prUrl && files.length === 0) {
    return (
      <Card className="bg-light/5">
        <CardContent className="py-12 text-center text-light/40">
          <AlertCircle className="mx-auto mb-3 h-8 w-8 text-light/30" />
          No optimizations were generated for this repository.
        </CardContent>
      </Card>
    );
  }

  if (!prUrl) {
    const isPermissionError = prStatus === "permission_denied" || prStatus === "repo_not_found";
    return (
      <Card className="bg-light/5">
        <CardContent className="py-12 text-center text-light/40">
          {isPermissionError ? (
            <>
              <ShieldAlert className="mx-auto mb-3 h-8 w-8 text-red-500/70" />
              <p className="text-sm font-medium text-red-400 mb-1">
                {prStatus === "permission_denied"
                  ? "Write permission denied"
                  : "Repository not found"}
              </p>
              <p className="text-sm text-neutral-400">
                {prError || "Could not create pull request. Check your GitHub token permissions."}
              </p>
              <p className="text-xs text-neutral-600 mt-3">
                The optimized code is still available in the results.
              </p>
            </>
          ) : (
            <>
              <AlertCircle className="mx-auto mb-3 h-8 w-8 text-accent-orange/70" />
              <p className="text-sm">
                {prError || "PR creation was skipped or failed. The optimized code is still available in the results."}
              </p>
            </>
          )}
        </CardContent>
      </Card>
    );
  }

  const prNumber = prUrl.split("/").pop();

  return (
    <div className="space-y-4">
      <Card className="bg-light/5">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <GitPullRequest className="h-5 w-5 text-accent-green" />
            Pull Request Created
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between rounded-lg bg-light/10 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-sm text-light/80">
                perf: Benchy automated optimizations
              </p>
              <p className="mt-0.5 text-xs text-light/40">
                #{prNumber} &middot; {files.length} file
                {files.length !== 1 ? "s" : ""} changed
              </p>
            </div>
            <Button
              size="sm"
              className="ml-4 shrink-0 gap-1.5"
              onClick={() => window.open(prUrl, "_blank", "noopener")}
            >
              View on GitHub
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
          </div>

          {score && (
            <div className="grid grid-cols-3 gap-3">
              <ScoreChip label="Time" value={score.time_score} color="text-accent-blue" />
              <ScoreChip label="Memory" value={score.memory_score} color="text-accent-purple" />
              <ScoreChip label="Complexity" value={score.complexity_score} color="text-accent-orange" />
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="bg-light/5">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-light/50">
            Changed Files
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-1">
            {files.map((file) => (
              <li
                key={file}
                className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-light/5"
              >
                <FileCode className="h-4 w-4 shrink-0 text-accent-blue" />
                <span className="truncate font-mono text-light/70">
                  {file}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {comparison && (
        <Card className="bg-light/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-light/50">
              PR Description Preview
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 text-sm text-light/70">
              {score && (
                <p>
                  <span className="font-medium text-light/80">
                    Benchy Score:
                  </span>{" "}
                  {score.overall_before.toFixed(0)} →{" "}
                  {score.overall_after.toFixed(0)}
                </p>
              )}

              {comparison.functions.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-light/10 text-light/40">
                        <th className="pb-2 pr-4 font-medium">Function</th>
                        <th className="pb-2 pr-4 font-medium">File</th>
                        <th className="pb-2 pr-4 font-medium text-right">
                          Before
                        </th>
                        <th className="pb-2 pr-4 font-medium text-right">
                          After
                        </th>
                        <th className="pb-2 font-medium text-right">
                          Speedup
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.functions.map((fn) => (
                        <tr
                          key={`${fn.file}-${fn.function_name}`}
                          className="border-b border-light/5"
                        >
                          <td className="py-1.5 pr-4 font-mono">
                            {fn.function_name}
                          </td>
                          <td className="py-1.5 pr-4 font-mono text-light/40">
                            {fn.file}
                          </td>
                          <td className="py-1.5 pr-4 text-right tabular-nums">
                            {fn.old_time_ms.toFixed(2)}ms
                          </td>
                          <td className="py-1.5 pr-4 text-right tabular-nums">
                            {fn.new_time_ms.toFixed(2)}ms
                          </td>
                          <td className="py-1.5 text-right tabular-nums text-accent-green">
                            {fn.speedup_factor.toFixed(1)}x
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {comparison.summary && (
                <p className="text-light/50">{comparison.summary}</p>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ScoreChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="rounded-lg bg-light/10 px-3 py-2 text-center">
      <p className="text-xs text-light/40">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold tabular-nums ${color}`}>
        {value.toFixed(0)}
      </p>
    </div>
  );
}
