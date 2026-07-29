import React, { useState } from 'react';
import {
  Brain,
  Database,
  Shield,
  MessageSquare,
  Cpu,
  Search,
  Sparkles,
  Copy,
  Check,
  ExternalLink,
  Code
} from 'lucide-react';
import { Stats, SearchResult } from '../../types';
import { searchMemory } from '../../api';
import { AgentBadge, CategoryBadge, RenderPill } from '../ui/Badge';

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
            <Brain className="w-3.5 h-3.5 text-[#a855f7]" />
            <span className="uppercase tracking-wider font-medium text-[11px]">SINGLE SOURCE OF TRUTH</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold text-white tracking-tight">GigaMind Service Overview</h1>
            <RenderPill label="Python 3" variant="purple" />
            <RenderPill label="FastMCP SSE" variant="emerald" />
            <RenderPill label="v2.0.0" variant="purpleFilled" />
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-[#8a8f9e]">
            <div className="flex items-center gap-1.5">
              <span>MCP SSE:</span>
              <span className="font-mono text-[#c1c5d0]">{sseUrl}</span>
              <button
                onClick={() => handleCopy(sseUrl, 'sse')}
                className="hover:text-white transition-colors"
                title="Copy SSE Endpoint"
              >
                {copiedField === 'sse' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
              </button>
            </div>

            <div className="flex items-center gap-1.5">
              <span>OpenAPI:</span>
              <a href={openApiUrl} target="_blank" rel="noreferrer" className="font-mono text-[#c1c5d0] hover:underline flex items-center gap-1">
                /openapi.json <ExternalLink className="w-3 h-3 text-[#8a8f9e]" />
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* METRICS CARDS */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div
          onClick={() => onNavigateTab('memories')}
          className="bg-[#13151c] border border-[#1e2029] hover:border-[#262936] p-4 rounded-lg cursor-pointer transition-all space-y-2 group"
        >
          <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
            <span>Memories</span>
            <Database className="w-4 h-4 text-[#a855f7] group-hover:text-white transition-colors" />
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            {stats?.total_memories ?? 0}
          </div>
          <div className="text-[11px] text-[#8a8f9e] group-hover:text-[#a855f7] transition-colors">
            Manage repository →
          </div>
        </div>

        <div
          onClick={() => onNavigateTab('rules')}
          className="bg-[#13151c] border border-[#1e2029] hover:border-[#262936] p-4 rounded-lg cursor-pointer transition-all space-y-2 group"
        >
          <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
            <span>Profile Rules</span>
            <Shield className="w-4 h-4 text-[#a855f7] group-hover:text-white transition-colors" />
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            {stats?.total_profile_rules ?? 0}
          </div>
          <div className="text-[11px] text-[#8a8f9e] group-hover:text-[#a855f7] transition-colors">
            View profile directives →
          </div>
        </div>

        <div
          onClick={() => onNavigateTab('transcripts')}
          className="bg-[#13151c] border border-[#1e2029] hover:border-[#262936] p-4 rounded-lg cursor-pointer transition-all space-y-2 group"
        >
          <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
            <span>Chat Transcripts</span>
            <MessageSquare className="w-4 h-4 text-emerald-400 group-hover:text-white transition-colors" />
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            {stats?.total_chat_logs ?? 0}
          </div>
          <div className="text-[11px] text-[#8a8f9e] group-hover:text-emerald-400 transition-colors">
            Inspect conversation logs →
          </div>
        </div>

        <div className="bg-[#13151c] border border-[#1e2029] p-4 rounded-lg space-y-2">
          <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
            <span>Task Sessions</span>
            <Cpu className="w-4 h-4 text-[#06b6d4]" />
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            {stats?.total_task_sessions ?? 0}
          </div>
          <div className="text-[11px] text-emerald-400 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Service Live</span>
          </div>
        </div>
      </div>

      {/* QUICK SEARCH BAR SECTION */}
      <div className="bg-[#13151c] border border-[#1e2029] p-5 rounded-lg space-y-4">
        <div className="flex items-center gap-2 text-white font-semibold">
          <Sparkles className="w-4 h-4 text-[#a855f7]" />
          <span>Semantic Memory Search</span>
        </div>

        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-[#8a8f9e] absolute left-3 top-3" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Query memory database using natural language (e.g. tech stack preferences)..."
              className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#5b0e89] pl-9 pr-3 py-2.5 text-xs text-white placeholder-[#8a8f9e] outline-none rounded-md transition-colors"
            />
          </div>
          <button
            type="submit"
            disabled={isSearching}
            className="bg-[#5b0e89] hover:bg-[#6d10a3] text-white font-medium px-5 py-2.5 rounded-md transition-colors flex items-center gap-2"
          >
            <span>{isSearching ? 'Searching...' : 'Search'}</span>
          </button>
        </form>

        {/* SEARCH RESULTS PREVIEW */}
        {searchResults && (
          <div className="pt-3 border-t border-[#1e2029] space-y-3">
            <div className="flex justify-between items-center text-[#8a8f9e] text-xs">
              <span>Found {searchResults.length} relevant results</span>
              <button onClick={() => setSearchResults(null)} className="text-rose-400 hover:underline">
                Clear
              </button>
            </div>

            {searchResults.length === 0 ? (
              <div className="p-4 text-center text-[#8a8f9e] bg-[#0a0b0e] border border-[#1e2029] rounded-md">
                No semantic matches found
              </div>
            ) : (
              <div className="space-y-2">
                {searchResults.map((res) => (
                  <div
                    key={res.id}
                    className="bg-[#0a0b0e] border border-[#1e2029] hover:border-[#262936] p-3 rounded-md flex justify-between items-center gap-4 transition-colors"
                  >
                    <div className="space-y-1 flex-1">
                      <div className="flex items-center gap-2">
                        <CategoryBadge category={res.category} />
                        <AgentBadge agent={res.source_agent} />
                      </div>
                      <p className="text-white text-xs">{res.content}</p>
                    </div>
                    <span className="text-[#a855f7] font-medium text-xs bg-[#5b0e89]/20 border border-[#5b0e89]/30 px-2.5 py-1 rounded-md">
                      {(res.score * 100).toFixed(1)}% match
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* SOURCE CREATOR BREAKDOWN */}
      <div className="bg-[#13151c] border border-[#1e2029] rounded-lg overflow-hidden">
        <div className="p-4 border-b border-[#1e2029] flex justify-between items-center">
          <h2 className="font-semibold text-white text-xs">Memory Creator Breakdown</h2>
          <span className="text-[#8a8f9e] text-xs">Tracked Source Agents</span>
        </div>

        <div className="divide-y divide-[#1e2029]">
          {['claude', 'gpt', 'gemini', 'user', 'system'].map((agentKey) => {
            const count = sourceCounts[agentKey] || 0;
            const total = stats?.total_memories || 1;
            const pct = Math.round((count / total) * 100);

            return (
              <div key={agentKey} className="p-4 flex items-center justify-between hover:bg-[#181a24] transition-colors">
                <div className="flex items-center gap-3">
                  <div className="w-2 h-2 rounded-full bg-emerald-400" />
                  <AgentBadge agent={agentKey} />
                </div>
                <div className="flex items-center gap-4 text-xs">
                  <span className="text-white font-medium">{count} memories</span>
                  <span className="text-[#8a8f9e] w-12 text-right">{pct}%</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
