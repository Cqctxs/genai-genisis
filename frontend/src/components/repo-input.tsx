"use client";

import { useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { listRepos, type GitHubRepo } from "@/lib/api";

const GITHUB_URL_REGEX = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;

const LANGUAGE_COLORS: Record<string, string> = {
  TypeScript: "#3178c6",
  JavaScript: "#f1e05a",
  Python: "#3572A5",
  Go: "#00ADD8",
  Rust: "#dea584",
  Java: "#b07219",
  "C++": "#f34b7d",
  C: "#555555",
  Ruby: "#701516",
  PHP: "#4F5D95",
  Swift: "#F05138",
  Kotlin: "#A97BFF",
  Dart: "#00B4AB",
  Shell: "#89e051",
  HTML: "#e34c26",
  CSS: "#563d7c",
};

function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

type Mode = "browse" | "url";
type OptimizationBias = "speed" | "balanced" | "memory";

const BIAS_OPTIONS: { value: OptimizationBias; label: string; description: string }[] = [
  { value: "speed", label: "Speed", description: "Maximize execution speed" },
  { value: "balanced", label: "Balanced", description: "Balance speed and memory" },
  { value: "memory", label: "Memory", description: "Minimize memory usage" },
];

interface RepoInputProps {
  onAnalyze: (repoUrl: string, optimizationBias: string, fastMode: boolean) => void;
  isLoading: boolean;
  accessToken: string | null;
}

export function RepoInput({ onAnalyze, isLoading, accessToken }: RepoInputProps) {
  const [mode, setMode] = useState<Mode>("browse");
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [fetchState, setFetchState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [fetchError, setFetchError] = useState("");
  const [search, setSearch] = useState("");
  const [selectedRepo, setSelectedRepo] = useState<GitHubRepo | null>(null);

  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState("");
  const [optimizationBias, setOptimizationBias] = useState<OptimizationBias>("balanced");
  const [fastMode, setFastMode] = useState(false);

  useEffect(() => {
    if (!accessToken || fetchState !== "idle") return;

    setFetchState("loading");
    listRepos(accessToken)
      .then((data) => {
        setRepos(data);
        setFetchState("loaded");
      })
      .catch((err) => {
        setFetchError(err.message);
        setFetchState("error");
      });
  }, [accessToken, fetchState]);

  const filtered = useMemo(() => {
    if (!search.trim()) return repos;
    const q = search.toLowerCase();
    return repos.filter(
      (r) =>
        r.full_name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.language.toLowerCase().includes(q)
    );
  }, [repos, search]);

  const handleBrowseAnalyze = () => {
    if (!selectedRepo) return;
    onAnalyze(selectedRepo.html_url, optimizationBias, fastMode);
  };

  const handleUrlSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim().replace(/\/+$/, "");
    if (!GITHUB_URL_REGEX.test(trimmed)) {
      setUrlError("Please enter a valid GitHub repository URL (e.g., https://github.com/owner/repo)");
      return;
    }
    setUrlError("");
    onAnalyze(trimmed, optimizationBias, fastMode);
  };

  return (
    <Card className="bg-light/5">
      <CardContent className="pt-5 pb-4 space-y-4">
        <div className="flex items-center gap-1 bg-dark rounded-lg p-1 w-fit">
          <button
            type="button"
            onClick={() => setMode("browse")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              mode === "browse"
                ? "bg-light/15 text-light"
                : "text-light/40 hover:text-light/70"
            }`}
          >
            My Repositories
          </button>
          <button
            type="button"
            onClick={() => setMode("url")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              mode === "url"
                ? "bg-light/15 text-light"
                : "text-light/40 hover:text-light/70"
            }`}
          >
            Enter URL
          </button>
        </div>

        <div className="space-y-2">
          <label className="text-xs font-mono text-light/50 uppercase tracking-wider">
            Optimization Priority
          </label>
          <div className="flex items-center gap-1 bg-dark rounded-lg p-1 w-fit">
            {BIAS_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={isLoading}
                onClick={() => setOptimizationBias(opt.value)}
                className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                  optimizationBias === opt.value
                    ? "bg-light/15 text-light"
                    : "text-light/40 hover:text-light/70"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-light/30">
            {BIAS_OPTIONS.find((o) => o.value === optimizationBias)?.description}
          </p>
        </div>

        <div className="space-y-2">
          <label className="text-xs font-mono text-light/50 uppercase tracking-wider">
            Analysis Mode
          </label>
          <div className="flex items-center gap-1 bg-dark rounded-lg p-1 w-fit">
            <button
              type="button"
              disabled={isLoading}
              onClick={() => setFastMode(false)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                !fastMode
                  ? "bg-light/15 text-light"
                  : "text-light/40 hover:text-light/70"
              }`}
            >
              Detailed
            </button>
            <button
              type="button"
              disabled={isLoading}
              onClick={() => setFastMode(true)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                fastMode
                  ? "bg-light/15 text-light"
                  : "text-light/40 hover:text-light/70"
              }`}
            >
              Fast (Skip Review)
            </button>
          </div>
          <p className="text-xs text-light/30">
            {fastMode ? "Skips the reviewer verification node for faster results." : "Uses an AI reviewer to double-check AI optimizations."}
          </p>
        </div>

        {mode === "browse" && (
          <div className="space-y-3">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search repositories..."
              className="bg-dark border-light/15 placeholder:text-light/30"
              disabled={isLoading}
            />

            <div className="max-h-72 overflow-y-auto rounded-lg border border-light/10 bg-dark scrollbar-thin">
              {fetchState === "loading" && (
                <div className="p-3 space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="flex items-start gap-3 p-3">
                      <Skeleton className="w-8 h-8 rounded-full shrink-0 bg-light/10" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-48 bg-light/10" />
                        <Skeleton className="h-3 w-72 bg-light/10" />
                        <div className="flex gap-3">
                          <Skeleton className="h-3 w-16 bg-light/10" />
                          <Skeleton className="h-3 w-12 bg-light/10" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {fetchState === "error" && (
                <div className="p-6 text-center">
                  <p className="text-sm text-accent-red">{fetchError}</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-2 text-light/50"
                    onClick={() => setFetchState("idle")}
                  >
                    Retry
                  </Button>
                </div>
              )}

              {fetchState === "loaded" && filtered.length === 0 && (
                <div className="p-6 text-center text-sm text-light/40">
                  {search ? "No repositories match your search" : "No repositories found"}
                </div>
              )}

              {fetchState === "loaded" &&
                filtered.map((repo) => {
                  const isSelected = selectedRepo?.id === repo.id;
                  return (
                    <button
                      key={repo.id}
                      type="button"
                      disabled={isLoading}
                      onClick={() => setSelectedRepo(isSelected ? null : repo)}
                      className={`w-full text-left px-4 py-3 flex items-start gap-3 border-b border-light/5 last:border-b-0 transition-colors ${
                        isSelected
                          ? "bg-accent-blue/10 border-l-2 border-l-accent-blue"
                          : "hover:bg-light/5"
                      }`}
                    >
                      <img
                        src={repo.owner_avatar}
                        alt={repo.owner}
                        className="w-8 h-8 rounded-full shrink-0 mt-0.5"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-light/80 truncate">
                            {repo.full_name}
                          </span>
                          {repo.private && (
                            <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 border-light/15 text-light/50">
                              Private
                            </Badge>
                          )}
                          {repo.fork && (
                            <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 border-light/15 text-light/40">
                              Fork
                            </Badge>
                          )}
                        </div>
                        {repo.description && (
                          <p className="text-xs text-light/40 mt-0.5 truncate">
                            {repo.description}
                          </p>
                        )}
                        <div className="flex items-center gap-3 mt-1.5">
                          {repo.language && (
                            <span className="flex items-center gap-1 text-xs text-light/40">
                              <span
                                className="w-2.5 h-2.5 rounded-full inline-block"
                                style={{
                                  backgroundColor: LANGUAGE_COLORS[repo.language] || "#8b8b8b",
                                }}
                              />
                              {repo.language}
                            </span>
                          )}
                          {repo.stargazers_count > 0 && (
                            <span className="text-xs text-light/40">
                              &#9733; {repo.stargazers_count.toLocaleString()}
                            </span>
                          )}
                          {repo.updated_at && (
                            <span className="text-xs text-light/30">
                              {formatRelativeTime(repo.updated_at)}
                            </span>
                          )}
                        </div>
                      </div>
                      {isSelected && (
                        <div className="shrink-0 mt-1">
                          <svg className="w-5 h-5 text-accent-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        </div>
                      )}
                    </button>
                  );
                })}
            </div>

            <div className="flex justify-end">
              <Button
                onClick={handleBrowseAnalyze}
                disabled={isLoading || !selectedRepo}
                className="bg-accent-blue hover:bg-accent-blue/80 text-light px-6"
              >
                {isLoading ? (
                  <span className="flex items-center gap-2">
                    <span className="w-4 h-4 border-2 border-light/30 border-t-light rounded-full animate-spin" />
                    Analyzing...
                  </span>
                ) : (
                  "Analyze"
                )}
              </Button>
            </div>
          </div>
        )}

        {mode === "url" && (
          <form onSubmit={handleUrlSubmit} className="flex gap-3">
            <div className="flex-1 space-y-1">
              <Input
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  if (urlError) setUrlError("");
                }}
                placeholder="https://github.com/owner/repository"
                className="bg-dark border-light/15 placeholder:text-light/30"
                disabled={isLoading}
              />
              {urlError && <p className="text-xs text-accent-red">{urlError}</p>}
            </div>
            <Button
              type="submit"
              disabled={isLoading || !url.trim()}
              className="bg-accent-blue hover:bg-accent-blue/80 text-light px-6"
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-light/30 border-t-light rounded-full animate-spin" />
                  Analyzing...
                </span>
              ) : (
                "Analyze"
              )}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
