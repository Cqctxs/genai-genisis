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
import { MarkdownContent } from "@/components/markdown-content";

interface ScoreDashboardProps {
  comparison: ComparisonReport;
}

function AnimatedScore({
  target,
  duration = 2,
  decimals = 0,
}: {
  target: number;
  duration?: number;
  decimals?: number;
}) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const factor = Math.pow(10, decimals);
    const animate = () => {
      const elapsed = (Date.now() - start) / 1000;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(target * eased * factor) / factor);
      if (progress < 1) requestAnimationFrame(animate);
    };
    animate();
  }, [target, duration, decimals]);

  return <span>{value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</span>;
}

function SubScoreBar({
  label,
  before,
  value,
  max,
  color,
}: {
  label: string;
  before: number;
  value: number;
  max: number;
  color: string;
}) {
  const pct = Math.min((value / max) * 100, 100);
  const beforePct = Math.min((before / max) * 100, 100);
  const improved = value >= before;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-light/60">{label}</span>
        <span className="text-light/40 tabular-nums">
          <span className="text-light/25 line-through mr-1">
            {Math.round(before).toLocaleString()}
          </span>
          <span className={improved ? "text-accent-green" : "text-accent-red"}>
            {Math.round(value).toLocaleString()}
          </span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-light/10 overflow-hidden relative">
        {/* before marker */}
        <div
          className="absolute top-0 h-full rounded-full bg-light/20"
          style={{ width: `${beforePct}%` }}
        />
        <motion.div
          className="absolute top-0 h-full rounded-full"
          style={{ backgroundColor: color, opacity: improved ? 1 : 0.5 }}
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
  isNegative,
}: {
  label: string;
  before: string;
  after: string;
  unit: string;
  improvement: string;
  isNegative?: boolean;
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
        <p
          className={`text-xs font-medium ${isNegative ? "text-accent-red" : "text-accent-green"}`}
        >
          {improvement}
        </p>
      </CardContent>
    </Card>
  );
}


/** Format a number with appropriate sig figs — no trailing zeros, commas for large values */
function fmt(n: number): string {
  if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString();
  if (Math.abs(n) >= 10) return n.toFixed(1);
  if (Math.abs(n) >= 1) return parseFloat(n.toFixed(2)).toString();
  return parseFloat(n.toFixed(2)).toString();
}

export function ScoreDashboard({ comparison }: ScoreDashboardProps) {
  const { benchy_score, functions, summary, sandbox_specs } = comparison;

  const totalOldMem = functions.reduce((acc, f) => acc + f.old_memory_mb, 0);
  const totalNewMem = functions.reduce((acc, f) => acc + f.new_memory_mb, 0);

  // Geometric mean of relative speedups — balances small/large function improvements
  const speedups = functions.map((f) => Math.max(f.speedup_factor, 0.01));
  const geomeanSpeedup =
    speedups.length > 0
      ? Math.exp(
          speedups.reduce((acc, val) => acc + Math.log(val), 0) /
            speedups.length,
        )
      : 1;

  return (
    <div className="space-y-6">
      <Card className="bg-light/5">
        <CardContent className="py-8">
          <div className="text-center space-y-4">
            <p className="text-xs font-semibold uppercase tracking-widest text-accent-blue/80">
              Overall Speedup
            </p>
            <motion.div
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.5, duration: 0.5 }}
              className={`text-5xl font-bold flex items-baseline justify-center gap-2 ${
                geomeanSpeedup >= 1.05
                  ? "text-accent-green"
                  : geomeanSpeedup < 1.0
                    ? "text-accent-red"
                    : "text-light"
              }`}
            >
              <AnimatedScore target={geomeanSpeedup} decimals={2} />
              <span className="text-2xl font-medium opacity-60">x</span>
            </motion.div>
            <p className="text-xs text-light/40">
              Geometric mean of per-function speedups
            </p>

            <p className="text-xs font-semibold uppercase tracking-widest text-accent-green/80 mt-6">
              Total Peak Memory
            </p>
            <div className="flex items-center justify-center gap-4">
              <div className="text-2xl text-light/40 flex items-baseline gap-1">
                <AnimatedScore target={totalOldMem} duration={1} decimals={1} />
                <span className="text-sm">MB</span>
              </div>
              <svg
                className="w-6 h-6 text-light/20"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={2}
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"
                />
              </svg>
              <motion.div
                initial={{ scale: 0.5, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ delay: 0.5, duration: 0.5 }}
                className="text-5xl font-bold text-accent-green flex items-baseline gap-2"
              >
                <AnimatedScore target={totalNewMem} decimals={1} />
                <span className="text-2xl font-medium opacity-60">MB</span>
              </motion.div>
            </div>

            <div className="max-w-xs mx-auto space-y-2 pt-6">
              <SubScoreBar
                label="Time"
                before={benchy_score.time_score_before}
                value={benchy_score.time_score}
                max={10000}
                color="var(--color-accent-blue)"
              />
              <SubScoreBar
                label="Memory"
                before={benchy_score.memory_score_before}
                value={benchy_score.memory_score}
                max={10000}
                color="var(--color-accent-green)"
              />
              <SubScoreBar
                label="API Efficiency"
                before={benchy_score.api_score_before}
                value={benchy_score.api_score}
                max={10000}
                color="var(--color-accent-purple)"
              />
            </div>
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
                    tick={{
                      fill: "var(--color-light)",
                      fillOpacity: 0.5,
                      fontSize: 11,
                    }}
                  />
                  <PolarRadiusAxis
                    angle={30}
                    domain={[0, 100]}
                    tick={false}
                    axisLine={false}
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
                    wrapperStyle={{
                      fontSize: "11px",
                      color: "var(--color-light)",
                      opacity: 0.5,
                    }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-3">
          <MetricCard
            label="Overall Speedup"
            before="1.0"
            after={fmt(geomeanSpeedup)}
            unit="x"
            isNegative={geomeanSpeedup < 1}
            improvement={
              geomeanSpeedup >= 1
                ? `${fmt(geomeanSpeedup)}x faster (geometric mean)`
                : `${fmt(1 / geomeanSpeedup)}x slower (geometric mean)`
            }
          />
          <MetricCard
            label="Memory Peak"
            before={fmt(totalOldMem)}
            after={fmt(totalNewMem)}
            unit=" MB"
            isNegative={totalNewMem > totalOldMem}
            improvement={(() => {
              const diff = totalOldMem - totalNewMem;
              return diff >= 0
                ? `-${fmt(diff)} MB`
                : `+${fmt(Math.abs(diff))} MB`;
            })()}
          />
        </div>
      </div>

      <Card className="bg-light/5">
        <CardContent className="py-4">
          <p className="text-sm text-light/70"><MarkdownContent>{summary}</MarkdownContent></p>
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
                        <div className="font-mono text-xs">
                          {f.function_name}
                        </div>
                        <div className="text-[10px] text-light/30">
                          {f.file}
                        </div>
                      </td>
                      <td className="text-right py-2 px-3 text-light/40">
                        {fmt(f.old_time_ms)} ms
                      </td>
                      <td className="text-right py-2 px-3 text-light">
                        {fmt(f.new_time_ms)} ms
                      </td>
                      <td
                        className={`text-right py-2 px-3 font-medium ${f.speedup_factor >= 1 ? "text-accent-green" : "text-accent-red"}`}
                      >
                        {f.speedup_factor >= 1
                          ? `${fmt(f.speedup_factor)}x`
                          : `${fmt(1 / f.speedup_factor)}x slower`}
                      </td>
                      <td
                        className={`text-right py-2 pl-3 ${f.memory_reduction_pct >= 0 ? "text-accent-green" : "text-accent-red"}`}
                      >
                        {f.memory_reduction_pct >= 0
                          ? `-${Math.round(f.memory_reduction_pct)}%`
                          : `+${Math.round(Math.abs(f.memory_reduction_pct))}%`}
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
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z"
                />
              </svg>
              <div className="space-y-1">
                <p className="text-[11px] text-light/40 font-medium">
                  Benchmark Environment
                </p>
                <p className="text-[10px] text-light/25 leading-relaxed">
                  {sandbox_specs}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
