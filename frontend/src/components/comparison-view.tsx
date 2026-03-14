"use client";

import { useState } from "react";
import { DiffEditor } from "@monaco-editor/react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ComparisonViewProps {
  optimizedFiles: Record<string, string>;
  analysis: any;
}

export function ComparisonView({ optimizedFiles, analysis }: ComparisonViewProps) {
  const files = Object.keys(optimizedFiles);
  const [selectedFile, setSelectedFile] = useState(files[0] || "");

  const originalContent = analysis?.original_files?.[selectedFile] || "// Original file not available";
  const optimizedContent = optimizedFiles[selectedFile] || "";

  const language = selectedFile.endsWith(".py")
    ? "python"
    : selectedFile.endsWith(".ts") || selectedFile.endsWith(".tsx")
    ? "typescript"
    : "javascript";

  if (files.length === 0) {
    return (
      <Card className="bg-neutral-900 border-neutral-800">
        <CardContent className="py-12 text-center text-neutral-500">
          No optimized files to display
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* File selector */}
      <Card className="bg-neutral-900 border-neutral-800">
        <CardContent className="py-3">
          <div className="flex items-center gap-2 overflow-x-auto">
            {files.map((file) => (
              <button
                key={file}
                onClick={() => setSelectedFile(file)}
                className={`px-3 py-1 rounded text-xs font-mono whitespace-nowrap transition-colors ${
                  selectedFile === file
                    ? "bg-blue-600 text-white"
                    : "bg-neutral-800 text-neutral-400 hover:text-white"
                }`}
              >
                {file}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Diff editor */}
      <Card className="bg-neutral-900 border-neutral-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-neutral-400">
            Changes in {selectedFile}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[500px] rounded-lg overflow-hidden border border-neutral-800">
            <DiffEditor
              original={originalContent}
              modified={optimizedContent}
              language={language}
              theme="vs-dark"
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 12,
                scrollBeyondLastLine: false,
                renderSideBySide: true,
                lineNumbers: "on",
              }}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
