"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";

const GITHUB_URL_REGEX = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;

interface RepoInputProps {
  onAnalyze: (repoUrl: string) => void;
  isLoading: boolean;
}

export function RepoInput({ onAnalyze, isLoading }: RepoInputProps) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim().replace(/\/+$/, "");

    if (!GITHUB_URL_REGEX.test(trimmed)) {
      setError("Please enter a valid GitHub repository URL (e.g., https://github.com/owner/repo)");
      return;
    }

    setError("");
    onAnalyze(trimmed);
  };

  return (
    <Card className="bg-neutral-900 border-neutral-800">
      <CardContent className="pt-6">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <div className="flex-1 space-y-1">
            <Input
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (error) setError("");
              }}
              placeholder="https://github.com/owner/repository"
              className="bg-neutral-950 border-neutral-700 placeholder:text-neutral-600"
              disabled={isLoading}
            />
            {error && (
              <p className="text-xs text-red-400">{error}</p>
            )}
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
      </CardContent>
    </Card>
  );
}
