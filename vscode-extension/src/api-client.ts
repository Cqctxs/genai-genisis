import * as http from "http";
import * as https from "https";
import type { FileMap } from "./file-gatherer";

export interface AnalyzeResponse {
  job_id: string;
}

export interface JobResult {
  optimized_files: Record<string, string>;
  comparison?: {
    functions?: Array<{
      function_name: string;
      file: string;
      old_time_ms: number;
      new_time_ms: number;
      speedup_factor: number;
    }>;
    benchy_score?: {
      overall_before: number;
      overall_after: number;
    };
    summary?: string;
  };
  analysis?: {
    hotspots?: Array<{
      function_name: string;
      file: string;
      severity: string;
      category: string;
    }>;
  };
}

export type ProgressCallback = (message: string) => void;

function jsonRequest(
  url: string,
  method: string,
  body?: string,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const transport = parsed.protocol === "https:" ? https : http;

    const req = transport.request(
      {
        hostname: parsed.hostname,
        port: parsed.port,
        path: parsed.pathname + parsed.search,
        method,
        headers: {
          "Content-Type": "application/json",
          ...(body ? { "Content-Length": Buffer.byteLength(body) } : {}),
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          const data = Buffer.concat(chunks).toString("utf-8");
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 500)}`));
          } else {
            resolve(data);
          }
        });
      },
    );
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

export async function startLocalAnalysis(
  backendUrl: string,
  files: FileMap,
  language: string,
  optimizationBias: string,
): Promise<AnalyzeResponse> {
  const body = JSON.stringify({
    files,
    language,
    optimization_bias: optimizationBias,
  });

  const data = await jsonRequest(
    `${backendUrl}/api/analyze-local`,
    "POST",
    body,
  );
  return JSON.parse(data);
}

export async function getResults(
  backendUrl: string,
  jobId: string,
): Promise<JobResult> {
  const data = await jsonRequest(`${backendUrl}/api/results/${jobId}`, "GET");
  return JSON.parse(data);
}

export function streamJob(
  backendUrl: string,
  jobId: string,
  onProgress: ProgressCallback,
  onComplete: () => void,
  onError: (error: Error) => void,
): () => void {
  const parsed = new URL(`${backendUrl}/api/stream/${jobId}`);
  const transport = parsed.protocol === "https:" ? https : http;

  let buffer = "";
  let aborted = false;

  const req = transport.get(parsed.href, (res) => {
    res.setEncoding("utf-8");

    res.on("data", (chunk: string) => {
      if (aborted) return;
      buffer += chunk;

      // Parse SSE frames
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const lines = part.split("\n");
        let event = "message";
        let data = "";

        for (const line of lines) {
          if (line.startsWith("event:")) {
            event = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            data = line.slice(5).trim();
          }
        }

        if (event === "progress") {
          try {
            const parsed = JSON.parse(data);
            const msg =
              typeof parsed === "string"
                ? parsed
                : parsed.message || JSON.stringify(parsed);
            onProgress(msg);
          } catch {
            onProgress(data);
          }
        } else if (event === "complete") {
          onComplete();
          aborted = true;
          req.destroy();
          return;
        } else if (event === "error") {
          onError(new Error(data));
          aborted = true;
          req.destroy();
          return;
        }
      }
    });

    res.on("end", () => {
      if (!aborted) onComplete();
    });
  });

  req.on("error", (err) => {
    if (!aborted) onError(err);
  });

  return () => {
    aborted = true;
    req.destroy();
  };
}
