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
    <Card className="bg-neutral-900 border-neutral-800">
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-xs text-neutral-500 uppercase tracking-wide">{label}</p>
        <div className="flex items-baseline gap-2">
          <span className="text-neutral-500 line-through text-sm">
            {before}
            {unit}
          </span>
          <span className="text-xl font-semibold text-white">
            {after}
            {unit}
          </span>
        </div>
        <p className="text-xs font-medium text-green-400">{improvement}</p>
      </CardContent>
    </Card>
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
      {/* Benchy Score */}
      <Card className="bg-neutral-900 border-neutral-800">
        <CardContent className="py-8">
          <div className="text-center space-y-4">
            <p className="text-xs uppercase tracking-widest text-neutral-500">
              Benchy Score
            </p>
            <div className="flex items-center justify-center gap-6">
              <div className="text-2xl text-neutral-500">
                <AnimatedScore target={benchy_score.overall_before} duration={1} />
              </div>
              <svg
                className="w-6 h-6 text-neutral-600"
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
                className="text-5xl font-bold text-blue-400"
              >
                <AnimatedScore target={benchy_score.overall_after} />
              </motion.div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Radar Chart */}
        <Card className="bg-neutral-900 border-neutral-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-neutral-400">
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
                  <PolarGrid stroke="#404040" />
                  <PolarAngleAxis
                    dataKey="axis"
                    tick={{ fill: "#a3a3a3", fontSize: 11 }}
                  />
                  <PolarRadiusAxis
                    angle={30}
                    domain={[0, 100]}
                    tick={{ fill: "#525252", fontSize: 9 }}
                  />
                  <Radar
                    name="Before"
                    dataKey="before"
                    stroke="#ef4444"
                    fill="#ef4444"
                    fillOpacity={0.15}
                  />
                  <Radar
                    name="After"
                    dataKey="after"
                    stroke="#3b82f6"
                    fill="#3b82f6"
                    fillOpacity={0.25}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: "11px", color: "#a3a3a3" }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Metrics Cards */}
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

      {/* Summary */}
      <Card className="bg-neutral-900 border-neutral-800">
        <CardContent className="py-4">
          <p className="text-sm text-neutral-300">{summary}</p>
        </CardContent>
      </Card>

      {/* Per-function breakdown */}
      {functions.length > 0 && (
        <Card className="bg-neutral-900 border-neutral-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-neutral-400">
              Function Breakdown
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-neutral-500 text-xs border-b border-neutral-800">
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
                      className="border-b border-neutral-800/50"
                    >
                      <td className="py-2 pr-4">
                        <div className="font-mono text-xs">{f.function_name}</div>
                        <div className="text-[10px] text-neutral-600">{f.file}</div>
                      </td>
                      <td className="text-right py-2 px-3 text-neutral-500">
                        {f.old_time_ms.toFixed(1)}ms
                      </td>
                      <td className="text-right py-2 px-3 text-white">
                        {f.new_time_ms.toFixed(1)}ms
                      </td>
                      <td className="text-right py-2 px-3 text-green-400 font-medium">
                        {f.speedup_factor.toFixed(1)}x
                      </td>
                      <td className="text-right py-2 pl-3 text-green-400">
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

      {/* Sandbox specs */}
      {sandbox_specs && (
        <p className="text-[10px] text-neutral-600 text-center">
          Benchmarked on {sandbox_specs}
        </p>
      )}
    </div>
  );
}
