import React, { useState } from 'react';
import {
  PixelDatabase,
  PixelShield,
  PixelTerminal,
  PixelSparkles
} from '../ui/PixelIcons';
import { Search, Copy, Check, ExternalLink, Cpu } from 'lucide-react';
import { Stats, SearchResult } from '../../types';
import { searchMemory } from '../../api';
import { CategoryBadge, AgentBadge, RenderPill } from '../ui/Badge';
import { MemoryChart } from '../ui/MemoryChart';

interface OverviewTabProps {
  stats: Stats | null;
  onNavigateTab: (tab: any) => void;
}

export const OverviewTab: React.FC<OverviewTabProps> = ({ stats, onNavigateTab }) => {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setIsSearching(true);
    const results = await searchMemory(query.trim(), undefined, undefined, 5);
    setSearchResults(results);
    setIsSearching(false);
  };

  const handleCopy = (text: string, fieldName: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const sseUrl = `${window.location.origin}/sse`;
  const openApiUrl = `${window.location.origin}/openapi.json`;
  const sourceCounts = stats?.source_distribution || {};

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* SERVICE HEADER */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-[#8a8f9e] text-xs">
            <span className="uppercase tracking-wider font-semibold text-[11px] text-[#ff6b00]">
              SINGLE SOURCE OF TRUTH
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold text-white tracking-tight">GigaMind Service Overview</h1>
            <RenderPill label="Python 3" variant="orange" />
            <RenderPill label="FastMCP SSE" variant="amber" />
            <RenderPill label="v2.0.0" variant="orangeFilled" />
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-[#8a8f9e]">
            <div className="flex items-center gap-1.5">
              <span>MCP SSE:</span>
              <span className="font-mono text-[#c1c5d0]">{sseUrl}</span>
              <button
                onClick={() => handleCopy(sseUrl, 'sse')}
                className="hover:text-white transition-colors btn-press"
                title="Copy SSE Endpoint"
              >
                {copiedField === 'sse' ? <Check className="w-3 h-3 text-amber-400" /> : <Copy className="w-3 h-3" />}
              </button>
            </div>

            <div className="flex items-center gap-1.5">
              <span>OpenAPI:</span>
              <a href={openApiUrl} target="_blank" rel="noreferrer" className="font-mono text-[#c1c5d0] hover:underline flex items-center gap-1">
                /openapi.json <ExternalLink className="w-3 h-3 text-[#8a8f9e]" />
              </a>
            </div>

            <div className="flex items-center gap-1.5">
              <span>Connect AI Guide:</span>
              <a
                href="https://github.com/Wizhill05/GigaMind#connecting-gigamind-to-ai-services--coding-harnesses"
                target="_blank"
                rel="noreferrer"
                className="font-mono text-[#ff6b00] hover:underline flex items-center gap-1 font-semibold"
              >
                Docs <ExternalLink className="w-3 h-3 text-[#ff6b00]" />
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* METRICS CARDS WITH CARD-HOVER LIFTS */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div
          onClick={() => onNavigateTab('memories')}
          className="bg-[#13151c] border border-[#1e2029] p-4 rounded-none cursor-pointer card-hover space-y-2 group"
        >
          <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
            <span>Memories</span>
            <PixelDatabase className="w-4 h-4 text-[#ff6b00] group-hover:text-white transition-colors" />
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            {stats?.total_memories ?? 0}
          </div>
          <div className="text-[11px] text-[#8a8f9e] group-hover:text-[#ff6b00] transition-colors">
            Manage repository →
          </div>
        </div>

        <div
          onClick={() => onNavigateTab('rules')}
          className="bg-[#13151c] border border-[#1e2029] p-4 rounded-none cursor-pointer card-hover space-y-2 group"
        >
          <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
            <span>Profile Rules</span>
            <PixelShield className="w-4 h-4 text-[#ff8800] group-hover:text-white transition-colors" />
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            {stats?.total_profile_rules ?? 0}
          </div>
          <div className="text-[11px] text-[#8a8f9e] group-hover:text-[#ff8800] transition-colors">
            View profile directives →
          </div>
        </div>

        <div
          onClick={() => onNavigateTab('transcripts')}
          className="bg-[#13151c] border border-[#1e2029] p-4 rounded-none cursor-pointer card-hover space-y-2 group"
        >
          <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
            <span>Chat Transcripts</span>
            <PixelTerminal className="w-4 h-4 text-amber-400 group-hover:text-white transition-colors" />
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            {stats?.total_chat_logs ?? 0}
          </div>
          <div className="text-[11px] text-[#8a8f9e] group-hover:text-amber-400 transition-colors">
            Inspect conversation logs →
          </div>
        </div>

        <div className="bg-[#13151c] border border-[#1e2029] p-4 rounded-none space-y-2 card-hover">
          <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
            <span>Task Sessions</span>
            <Cpu className="w-4 h-4 text-[#06b6d4]" />
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            {stats?.total_task_sessions ?? 0}
          </div>
          <div className="text-[11px] text-amber-400 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-none bg-amber-400 animate-pulse" />
            <span>Service Live</span>
          </div>
        </div>
      </div>

      {/* QUICK SEARCH BAR SECTION - EXACT UNIFORM h-10 HEIGHT FOR INPUT AND BUTTON */}
      <div className="bg-[#13151c] border border-[#1e2029] p-5 rounded-none space-y-4">
        <div className="flex items-center gap-2 text-white font-semibold">
          <PixelSparkles className="w-4 h-4 text-[#ff6b00]" />
          <span>Semantic Memory Search</span>
        </div>

        <form onSubmit={handleSearch} className="flex items-center gap-2">
          <div className="relative flex-1 flex items-center h-10">
            <Search className="w-4 h-4 text-[#8a8f9e] absolute left-3" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Query memory database using natural language (e.g. tech stack preferences)..."
              className="h-10 w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#ff6b00] pl-9 pr-3 text-xs text-white placeholder-[#8a8f9e] outline-none rounded-none transition-all font-sans"
            />
          </div>
          <button
            type="submit"
            disabled={isSearching}
            className="h-10 bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium px-5 rounded-none transition-all flex items-center justify-center gap-2 shadow-sm btn-press flex-shrink-0"
          >
            <span>{isSearching ? 'Searching...' : 'Search'}</span>
          </button>
        </form>

        {/* SEARCH RESULTS PREVIEW */}
        {searchResults && (
          <div className="pt-3 border-t border-[#1e2029] space-y-3 animate-fade-in">
            <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
              <span>Found {searchResults.length} relevant results</span>
              <button onClick={() => setSearchResults(null)} className="text-rose-400 hover:underline btn-press">
                Clear
              </button>
            </div>

            {searchResults.length === 0 ? (
              <div className="p-4 text-center text-[#8a8f9e] bg-[#0a0b0e] border border-[#1e2029] rounded-none">
                No semantic matches found
              </div>
            ) : (
              <div className="space-y-2">
                {searchResults.map((res) => (
                  <div
                    key={res.id}
                    className="bg-[#0a0b0e] border border-[#1e2029] hover:border-[#ff6b00]/40 p-3 rounded-none flex justify-between items-center gap-4 transition-all card-hover"
                  >
                    <div className="space-y-1 flex-1">
                      <div className="flex items-center gap-2">
                        <CategoryBadge category={res.category} />
                        <AgentBadge agent={res.source_agent} />
                      </div>
                      <p className="text-white text-xs">{res.content}</p>
                    </div>
                    <span className="text-[#ff6b00] font-semibold text-xs bg-[#ff6b00]/15 border border-[#ff6b00]/30 px-2.5 py-1 rounded-none">
                      {(res.score * 100).toFixed(1)}% match
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* DATA VISUALIZATION CHART (REPLACING TEXT BREAKDOWN) */}
      <MemoryChart
        sourceDistribution={sourceCounts}
        totalMemories={stats?.total_memories || 0}
      />
    </div>
  );
};
