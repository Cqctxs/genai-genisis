"use client";

import { useEffect, useState } from "react";
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ComparisonReport } from "@/lib/api";

interface ScoreDashboardProps {
  comparison: ComparisonReport;
}

function AnimatedScore({ target, duration = 2 }: { target: number; duration?: number }) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const animate = () => {
      const elapsed = (Date.now() - start) / 1000;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(target * eased));
      if (progress < 1) requestAnimationFrame(animate);
    };
    animate();
  }, [target, duration]);

  return <span>{value.toLocaleString()}</span>;
}

function SubScoreBar({
  label,
  value,
  max,
  weight,
  color,
}: {
  label: string;
  value: number;
  max: number;
  weight: string;
  color: string;
}) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-light/60">{label}</span>
        <span className="text-light/40 tabular-nums">
          {value.toLocaleString()} <span className="text-light/25">· {weight}</span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-light/10 overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: color }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 1.2, ease: "easeOut", delay: 0.3 }}
        />
      </div>
    </div>
  );
}

function MetricCard({
  label,
  before,
  after,
  unit,
  improvement,
}: {
  label: string;
  before: string;
  after: string;
  unit: string;
  improvement: string;
}) {
  return (
    <Card className="bg-light/5">
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-xs text-light/40 uppercase tracking-wide">{label}</p>
        <div className="flex items-baseline gap-2">
          <span className="text-light/40 line-through text-sm">
            {before}
            {unit}
          </span>
          <span className="text-xl font-semibold text-light">
            {after}
            {unit}
          </span>
        </div>
        <p className="text-xs font-medium text-accent-green">{improvement}</p>
      </CardContent>
    </Card>
  );
}

function ScoreExplanation() {
  const [open, setOpen] = useState(false);

  return (
    <div className="text-center">
      <button
        onClick={() => setOpen(!open)}
        className="text-[11px] text-light/30 hover:text-light/50 transition-colors inline-flex items-center gap-1"
      >
        How is this score calculated?
        <svg
          className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>
      {open && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          className="mt-3 text-left max-w-lg mx-auto space-y-2 text-[11px] text-light/40 leading-relaxed"
        >
          <p>
            The <span className="text-light/60 font-medium">CodeMark Score</span> ranges
            from <span className="text-light/60">0 to 20,000</span>. A typical unoptimized
            project scores between 5,000 and 8,000. Higher is better.
          </p>
          <p>The score is composed of three weighted sub-scores:</p>
          <ul className="list-none space-y-1 pl-0">
            <li>
              <span className="text-accent-blue font-medium">Time (40%)</span> — Faster
              function execution produces a higher score.
            </li>
            <li>
              <span className="text-accent-green font-medium">Memory (30%)</span> — Lower
              peak memory usage produces a higher score.
            </li>
            <li>
              <span className="text-accent-purple font-medium">Complexity (30%)</span> — Better
              algorithmic complexity (e.g. O(n) vs O(n²)) produces a higher score.
            </li>
          </ul>
          <p>
            Benchmarks run inside isolated cloud containers with fixed hardware,
            ensuring reproducible measurements across runs.
          </p>
        </motion.div>
      )}
    </div>
  );
}

export function ScoreDashboard({ comparison }: ScoreDashboardProps) {
  const { benchy_score, functions, summary, sandbox_specs } = comparison;

  const totalOldTime = functions.reduce((acc, f) => acc + f.old_time_ms, 0);
  const totalNewTime = functions.reduce((acc, f) => acc + f.new_time_ms, 0);
  const totalOldMem = functions.reduce((acc, f) => acc + f.old_memory_mb, 0);
  const totalNewMem = functions.reduce((acc, f) => acc + f.new_memory_mb, 0);
  const avgSpeedup =
    functions.length > 0
      ? functions.reduce((acc, f) => acc + f.speedup_factor, 0) / functions.length
      : 0;

  return (
    <div className="space-y-6">
      <Card className="bg-light/5">
        <CardContent className="py-8">
          <div className="text-center space-y-4">
            <p className="text-xs uppercase tracking-widest text-light/40">
              CodeMark Score
            </p>
            <div className="flex items-center justify-center gap-6">
              <div className="text-2xl text-light/40">
                <AnimatedScore target={benchy_score.overall_before} duration={1} />
              </div>
              <svg
                className="w-6 h-6 text-light/20"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={2}
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
              </svg>
              <motion.div
                initial={{ scale: 0.5, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ delay: 0.5, duration: 0.5 }}
                className="text-5xl font-bold text-accent-purple"
              >
                <AnimatedScore target={benchy_score.overall_after} />
              </motion.div>
            </div>

            <div className="max-w-xs mx-auto space-y-2 pt-2">
              <SubScoreBar
                label="Time"
                value={benchy_score.time_score}
                max={20000}
                weight="40%"
                color="var(--color-accent-blue)"
              />
              <SubScoreBar
                label="Memory"
                value={benchy_score.memory_score}
                max={20000}
                weight="30%"
                color="var(--color-accent-green)"
              />
              <SubScoreBar
                label="Complexity"
                value={benchy_score.complexity_score}
                max={20000}
                weight="30%"
                color="var(--color-accent-purple)"
              />
            </div>

            <ScoreExplanation />
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-light/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-light/50">
              Performance Radar
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart
                  data={benchy_score.radar_data}
                  margin={{ top: 10, right: 30, bottom: 10, left: 30 }}
                >
                  <PolarGrid stroke="var(--color-light)" strokeOpacity={0.1} />
                  <PolarAngleAxis
                    dataKey="axis"
                    tick={{ fill: "var(--color-light)", fillOpacity: 0.5, fontSize: 11 }}
                  />
                  <PolarRadiusAxis
                    angle={30}
                    domain={[0, 100]}
                    tick={{ fill: "var(--color-light)", fillOpacity: 0.25, fontSize: 9 }}
                  />
                  <Radar
                    name="Before"
                    dataKey="before"
                    stroke="var(--color-accent-red)"
                    fill="var(--color-accent-red)"
                    fillOpacity={0.15}
                  />
                  <Radar
                    name="After"
                    dataKey="after"
                    stroke="var(--color-accent-blue)"
                    fill="var(--color-accent-blue)"
                    fillOpacity={0.25}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: "11px", color: "var(--color-light)", opacity: 0.5 }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-3">
          <MetricCard
            label="Execution Time"
            before={totalOldTime.toFixed(1)}
            after={totalNewTime.toFixed(1)}
            unit="ms"
            improvement={`+${((1 - totalNewTime / totalOldTime) * 100).toFixed(0)}% faster`}
          />
          <MetricCard
            label="Memory Peak"
            before={totalOldMem.toFixed(1)}
            after={totalNewMem.toFixed(1)}
            unit=" MB"
            improvement={`-${((1 - totalNewMem / totalOldMem) * 100).toFixed(0)}% memory`}
          />
          <MetricCard
            label="Avg Speedup"
            before="1.0"
            after={avgSpeedup.toFixed(1)}
            unit="x"
            improvement={`${avgSpeedup.toFixed(1)}x faster on average`}
          />
        </div>
      </div>

      <Card className="bg-light/5">
        <CardContent className="py-4">
          <p className="text-sm text-light/70">{summary}</p>
        </CardContent>
      </Card>

      {functions.length > 0 && (
        <Card className="bg-light/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-light/50">
              Function Breakdown
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-light/40 text-xs border-b border-light/10">
                    <th className="text-left py-2 pr-4">Function</th>
                    <th className="text-right py-2 px-3">Before</th>
                    <th className="text-right py-2 px-3">After</th>
                    <th className="text-right py-2 px-3">Speedup</th>
                    <th className="text-right py-2 pl-3">Memory</th>
                  </tr>
                </thead>
                <tbody>
                  {functions.map((f) => (
                    <tr
                      key={`${f.file}-${f.function_name}`}
                      className="border-b border-light/5"
                    >
                      <td className="py-2 pr-4">
                        <div className="font-mono text-xs">{f.function_name}</div>
                        <div className="text-[10px] text-light/30">{f.file}</div>
                      </td>
                      <td className="text-right py-2 px-3 text-light/40">
                        {f.old_time_ms.toFixed(1)}ms
                      </td>
                      <td className="text-right py-2 px-3 text-light">
                        {f.new_time_ms.toFixed(1)}ms
                      </td>
                      <td className="text-right py-2 px-3 text-accent-green font-medium">
                        {f.speedup_factor.toFixed(1)}x
                      </td>
                      <td className="text-right py-2 pl-3 text-accent-green">
                        -{f.memory_reduction_pct.toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {sandbox_specs && (
        <Card className="bg-light/5">
          <CardContent className="py-3">
            <div className="flex items-start gap-2">
              <svg
                className="w-3.5 h-3.5 text-light/25 mt-0.5 shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
              </svg>
              <div className="space-y-1">
                <p className="text-[11px] text-light/40 font-medium">Benchmark Environment</p>
                <p className="text-[10px] text-light/25 leading-relaxed">{sandbox_specs}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
