import React, { useState } from 'react';

interface MemoryChartProps {
  sourceDistribution: Record<string, number>;
  totalMemories: number;
}

export const MemoryChart: React.FC<MemoryChartProps> = ({ sourceDistribution, totalMemories }) => {
  const [hoveredSeries, setHoveredSeries] = useState<string | null>(null);

  const seriesData = [
    { key: 'claude', label: 'Claude', color: '#ff6b00', bgHover: 'bg-[#ff6b00]/20' },
    { key: 'gpt', label: 'GPT / OpenAI', color: '#f59e0b', bgHover: 'bg-[#f59e0b]/20' },
    { key: 'gemini', label: 'Gemini', color: '#06b6d4', bgHover: 'bg-[#06b6d4]/20' },
    { key: 'user', label: 'User', color: '#ff8800', bgHover: 'bg-[#ff8800]/20' },
    { key: 'system', label: 'System', color: '#10b981', bgHover: 'bg-[#10b981]/20' },
  ];

  const total = totalMemories > 0 ? totalMemories : 1;
  const maxCount = Math.max(1, ...seriesData.map(s => sourceDistribution[s.key] || 0));

  return (
    <div className="bg-[#13151c] border border-[#1e2029] rounded-none p-5 space-y-5 font-sans select-none">
      {/* CHART HEADER */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-2 border-b border-[#1e2029] pb-4">
        <div>
          <h2 className="text-sm font-semibold text-white tracking-tight flex items-center gap-2">
            <span>Memory Distribution & Origin Analytics</span>
          </h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Real-time memory volume breakdown by source creator
          </p>
        </div>

        {/* SERIES LEGEND */}
        <div className="flex flex-wrap items-center gap-3 text-xs text-[#8a8f9e]">
          {seriesData.map(s => {
            const count = sourceDistribution[s.key] || 0;
            const isHovered = hoveredSeries === s.key;
            return (
              <div
                key={s.key}
                onMouseEnter={() => setHoveredSeries(s.key)}
                onMouseLeave={() => setHoveredSeries(null)}
                className={`flex items-center gap-1.5 cursor-pointer px-2 py-1 rounded-none transition-all ${
                  isHovered ? 'bg-[#181a24] text-white' : 'hover:text-white'
                }`}
              >
                <span className="w-2.5 h-2.5 rounded-none flex-shrink-0" style={{ backgroundColor: s.color }} />
                <span>{s.label}:</span>
                <span className="font-semibold text-white">{count}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* SVG BAR CHART GRAPH */}
      <div className="space-y-4">
        <div className="h-44 w-full relative flex items-end justify-between gap-4 pt-6 pb-2 px-2 border-b border-[#1e2029]">
          {/* GRID BACKGROUND LINES */}
          <div className="absolute inset-0 flex flex-col justify-between pointer-events-none opacity-20">
            <div className="border-b border-dashed border-[#8a8f9e]" />
            <div className="border-b border-dashed border-[#8a8f9e]" />
            <div className="border-b border-dashed border-[#8a8f9e]" />
            <div className="border-b border-dashed border-[#8a8f9e]" />
          </div>

          {/* BARS */}
          {seriesData.map(s => {
            const count = sourceDistribution[s.key] || 0;
            const heightPct = Math.max(8, Math.round((count / maxCount) * 100));
            const sharePct = Math.round((count / total) * 100);
            const isHovered = hoveredSeries === s.key;

            return (
              <div
                key={s.key}
                onMouseEnter={() => setHoveredSeries(s.key)}
                onMouseLeave={() => setHoveredSeries(null)}
                className="flex-1 h-full flex flex-col justify-end items-center group relative cursor-pointer"
              >
                {/* INTERACTIVE TOOLTIP */}
                {isHovered && (
                  <div className="absolute -top-10 bg-[#0a0b0e] border border-[#262936] text-white px-2.5 py-1 text-[11px] font-mono rounded-none shadow-xl z-20 whitespace-nowrap animate-fade-in pointer-events-none">
                    <span style={{ color: s.color }} className="font-semibold">{s.label}</span>: {count} memories ({sharePct}%)
                  </div>
                )}

                {/* BAR */}
                <div
                  className="w-full max-w-[48px] rounded-none transition-all duration-300 relative overflow-hidden"
                  style={{
                    height: `${heightPct}%`,
                    backgroundColor: s.color,
                    opacity: hoveredSeries === null || isHovered ? 1 : 0.4,
                    transform: isHovered ? 'scaleY(1.04)' : 'scaleY(1)',
                    transformOrigin: 'bottom',
                  }}
                >
                  {/* INNER GRADIENT OVERLAY */}
                  <div className="absolute inset-0 bg-gradient-to-t from-black/30 to-transparent pointer-events-none" />
                </div>

                <span className="text-[11px] font-medium text-[#8a8f9e] group-hover:text-white transition-colors mt-2">
                  {s.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* STACKED VOLUME DISTRIBUTION BAR */}
        <div className="space-y-1.5">
          <div className="flex justify-between items-center text-[11px] text-[#8a8f9e]">
            <span>Volume Share Ratio</span>
            <span>Total: {totalMemories} records</span>
          </div>

          <div className="w-full h-3 bg-[#0a0b0e] border border-[#1e2029] flex overflow-hidden rounded-none">
            {seriesData.map(s => {
              const count = sourceDistribution[s.key] || 0;
              const pct = (count / total) * 100;
              if (pct <= 0) return null;

              return (
                <div
                  key={s.key}
                  onMouseEnter={() => setHoveredSeries(s.key)}
                  onMouseLeave={() => setHoveredSeries(null)}
                  style={{ width: `${pct}%`, backgroundColor: s.color }}
                  className="h-full transition-all duration-300 hover:brightness-125 cursor-pointer relative"
                  title={`${s.label}: ${count} (${Math.round(pct)}%)`}
                />
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
