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

interface RepoInputProps {
  onAnalyze: (repoUrl: string) => void;
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
    onAnalyze(selectedRepo.html_url);
  };

  const handleUrlSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim().replace(/\/+$/, "");
    if (!GITHUB_URL_REGEX.test(trimmed)) {
      setUrlError("Please enter a valid GitHub repository URL (e.g., https://github.com/owner/repo)");
      return;
    }
    setUrlError("");
    onAnalyze(trimmed);
  };

  return (
    <Card className="bg-neutral-900 border-neutral-800">
      <CardContent className="pt-5 pb-4 space-y-4">
        {/* Mode tabs */}
        <div className="flex items-center gap-1 bg-neutral-950 rounded-lg p-1 w-fit">
          <button
            type="button"
            onClick={() => setMode("browse")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              mode === "browse"
                ? "bg-neutral-800 text-white"
                : "text-neutral-500 hover:text-neutral-300"
            }`}
          >
            My Repositories
          </button>
          <button
            type="button"
            onClick={() => setMode("url")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              mode === "url"
                ? "bg-neutral-800 text-white"
                : "text-neutral-500 hover:text-neutral-300"
            }`}
          >
            Enter URL
          </button>
        </div>

        {mode === "browse" && (
          <div className="space-y-3">
            {/* Search */}
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search repositories..."
              className="bg-neutral-950 border-neutral-700 placeholder:text-neutral-600"
              disabled={isLoading}
            />

            {/* Repo list */}
            <div className="max-h-72 overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-950 scrollbar-thin">
              {fetchState === "loading" && (
                <div className="p-3 space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="flex items-start gap-3 p-3">
                      <Skeleton className="w-8 h-8 rounded-full shrink-0 bg-neutral-800" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-48 bg-neutral-800" />
                        <Skeleton className="h-3 w-72 bg-neutral-800" />
                        <div className="flex gap-3">
                          <Skeleton className="h-3 w-16 bg-neutral-800" />
                          <Skeleton className="h-3 w-12 bg-neutral-800" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {fetchState === "error" && (
                <div className="p-6 text-center">
                  <p className="text-sm text-red-400">{fetchError}</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-2 text-neutral-400"
                    onClick={() => setFetchState("idle")}
                  >
                    Retry
                  </Button>
                </div>
              )}

              {fetchState === "loaded" && filtered.length === 0 && (
                <div className="p-6 text-center text-sm text-neutral-500">
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
                      className={`w-full text-left px-4 py-3 flex items-start gap-3 border-b border-neutral-800/50 last:border-b-0 transition-colors ${
                        isSelected
                          ? "bg-blue-600/10 border-l-2 border-l-blue-500"
                          : "hover:bg-neutral-800/50"
                      }`}
                    >
                      <img
                        src={repo.owner_avatar}
                        alt={repo.owner}
                        className="w-8 h-8 rounded-full shrink-0 mt-0.5"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-neutral-200 truncate">
                            {repo.full_name}
                          </span>
                          {repo.private && (
                            <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 border-neutral-700 text-neutral-400">
                              Private
                            </Badge>
                          )}
                          {repo.fork && (
                            <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 border-neutral-700 text-neutral-500">
                              Fork
                            </Badge>
                          )}
                        </div>
                        {repo.description && (
                          <p className="text-xs text-neutral-500 mt-0.5 truncate">
                            {repo.description}
                          </p>
                        )}
                        <div className="flex items-center gap-3 mt-1.5">
                          {repo.language && (
                            <span className="flex items-center gap-1 text-xs text-neutral-500">
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
                            <span className="text-xs text-neutral-500">
                              &#9733; {repo.stargazers_count.toLocaleString()}
                            </span>
                          )}
                          {repo.updated_at && (
                            <span className="text-xs text-neutral-600">
                              {formatRelativeTime(repo.updated_at)}
                            </span>
                          )}
                        </div>
                      </div>
                      {isSelected && (
                        <div className="shrink-0 mt-1">
                          <svg className="w-5 h-5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        </div>
                      )}
                    </button>
                  );
                })}
            </div>

            {/* Analyze button */}
            <div className="flex justify-end">
              <Button
                onClick={handleBrowseAnalyze}
                disabled={isLoading || !selectedRepo}
                className="bg-blue-600 hover:bg-blue-700 text-white px-6"
              >
                {isLoading ? (
                  <span className="flex items-center gap-2">
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
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
                className="bg-neutral-950 border-neutral-700 placeholder:text-neutral-600"
                disabled={isLoading}
              />
              {urlError && <p className="text-xs text-red-400">{urlError}</p>}
            </div>
            <Button
              type="submit"
              disabled={isLoading || !url.trim()}
              className="bg-blue-600 hover:bg-blue-700 text-white px-6"
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
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
