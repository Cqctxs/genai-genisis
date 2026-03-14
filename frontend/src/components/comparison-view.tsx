"use client";

import { ExternalLink, GitPullRequest, FileCode, AlertCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { ComparisonReport } from "@/lib/api";

interface PullRequestViewProps {
  prUrl: string;
  optimizedFiles: Record<string, string>;
  comparison: ComparisonReport | null;
}

export function PullRequestView({
  prUrl,
  optimizedFiles,
  comparison,
}: PullRequestViewProps) {
  const files = Object.keys(optimizedFiles);
  const score = comparison?.codemark_score;

  if (!prUrl && files.length === 0) {
    return (
      <Card className="bg-neutral-900 border-neutral-800">
        <CardContent className="py-12 text-center text-neutral-500">
          <AlertCircle className="mx-auto mb-3 h-8 w-8 text-neutral-600" />
          No optimizations were generated for this repository.
        </CardContent>
      </Card>
    );
  }

  if (!prUrl) {
    return (
      <Card className="bg-neutral-900 border-neutral-800">
        <CardContent className="py-12 text-center text-neutral-500">
          <AlertCircle className="mx-auto mb-3 h-8 w-8 text-yellow-500/70" />
          <p className="text-sm">
            PR creation was skipped or failed. The optimized code is still
            available in the results.
          </p>
        </CardContent>
      </Card>
    );
  }

  const prNumber = prUrl.split("/").pop();

  return (
    <div className="space-y-4">
      {/* PR link card */}
      <Card className="bg-neutral-900 border-neutral-800">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <GitPullRequest className="h-5 w-5 text-green-500" />
            Pull Request Created
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between rounded-lg bg-neutral-800/60 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-sm text-neutral-200">
                perf: CodeMark automated optimizations
              </p>
              <p className="mt-0.5 text-xs text-neutral-500">
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

          {/* Score summary */}
          {score && (
            <div className="grid grid-cols-3 gap-3">
              <ScoreChip
                label="Time"
                value={score.time_score}
              />
              <ScoreChip
                label="Memory"
                value={score.memory_score}
              />
              <ScoreChip
                label="Complexity"
                value={score.complexity_score}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Changed files */}
      <Card className="bg-neutral-900 border-neutral-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-neutral-400">
            Changed Files
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-1">
            {files.map((file) => (
              <li
                key={file}
                className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-neutral-800/50"
              >
                <FileCode className="h-4 w-4 shrink-0 text-blue-400" />
                <span className="truncate font-mono text-neutral-300">
                  {file}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {/* PR description preview */}
      {comparison && (
        <Card className="bg-neutral-900 border-neutral-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-neutral-400">
              PR Description Preview
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 text-sm text-neutral-300">
              {score && (
                <p>
                  <span className="font-medium text-neutral-200">
                    CodeMark Score:
                  </span>{" "}
                  {score.overall_before.toFixed(0)} →{" "}
                  {score.overall_after.toFixed(0)}
                </p>
              )}

              {comparison.functions.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-neutral-800 text-neutral-500">
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
                          className="border-b border-neutral-800/50"
                        >
                          <td className="py-1.5 pr-4 font-mono">
                            {fn.function_name}
                          </td>
                          <td className="py-1.5 pr-4 font-mono text-neutral-500">
                            {fn.file}
                          </td>
                          <td className="py-1.5 pr-4 text-right tabular-nums">
                            {fn.old_time_ms.toFixed(2)}ms
                          </td>
                          <td className="py-1.5 pr-4 text-right tabular-nums">
                            {fn.new_time_ms.toFixed(2)}ms
                          </td>
                          <td className="py-1.5 text-right tabular-nums text-green-400">
                            {fn.speedup_factor.toFixed(1)}x
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {comparison.summary && (
                <p className="text-neutral-400">{comparison.summary}</p>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ScoreChip({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-neutral-800/60 px-3 py-2 text-center">
      <p className="text-xs text-neutral-500">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-neutral-200">
        {value.toFixed(0)}
      </p>
    </div>
  );
}
