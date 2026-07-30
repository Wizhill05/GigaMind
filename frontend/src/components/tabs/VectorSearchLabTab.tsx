import React, { useState } from 'react';
import { Search, Code } from 'lucide-react';
import { PixelSparkles, PixelTerminal } from '../ui/PixelIcons';
import { SearchResult } from '../../types';
import { searchMemory } from '../../api';
import { AgentBadge, CategoryBadge } from '../ui/Badge';

export const VectorSearchLabTab: React.FC = () => {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [sourceAgent, setSourceAgent] = useState('');
  const [limit, setLimit] = useState(5);

  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [showRawJson, setShowRawJson] = useState(false);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setIsLoading(true);
    const res = await searchMemory(
      query.trim(),
      category || undefined,
      sourceAgent || undefined,
      limit
    );
    setResults(res);
    setIsLoading(false);
  };

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-semibold text-white tracking-tight">Semantic Vector Search Lab</h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Test hybrid cosine similarity vector search and relevance ranking
          </p>
        </div>

        <button
          onClick={() => setShowRawJson(!showRawJson)}
          className={`px-3 py-1.5 text-xs font-medium border rounded-none transition-colors flex items-center gap-1.5 ${
            showRawJson
              ? 'bg-[#ff6b00] text-white border-transparent'
              : 'bg-[#161616] text-[#8a8f9e] border-[#333333] hover:text-white'
          }`}
        >
          <Code className="w-3.5 h-3.5" />
          <span>{showRawJson ? 'Hide Raw JSON' : 'Show Raw JSON'}</span>
        </button>
      </div>

      {/* SEARCH CONTROLS FORM */}
      <div className="bg-[#181818] border border-[#262626] p-5 rounded-none space-y-4">
        <form onSubmit={handleSearch} className="space-y-4">
          <div className="relative">
            <Search className="w-4 h-4 text-[#8a8f9e] absolute left-3.5 top-3" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Enter prompt query or context statement to test embedding relevance..."
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 pl-10 text-xs text-white placeholder-[#8a8f9e] outline-none rounded-none transition-colors font-sans"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#8a8f9e] mb-1">
                Category Filter
              </label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2 text-xs text-white outline-none rounded-none cursor-pointer"
              >
                <option value="" className="bg-[#0f0f0f]">All Categories</option>
                <option value="general" className="bg-[#0f0f0f]">general</option>
                <option value="coding" className="bg-[#0f0f0f]">coding</option>
                <option value="personal" className="bg-[#0f0f0f]">personal</option>
                <option value="project" className="bg-[#0f0f0f]">project</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-[#8a8f9e] mb-1">
                Source Agent Filter
              </label>
              <select
                value={sourceAgent}
                onChange={(e) => setSourceAgent(e.target.value)}
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2 text-xs text-white outline-none rounded-none cursor-pointer"
              >
                <option value="" className="bg-[#0f0f0f]">All Source Agents</option>
                <option value="claude" className="bg-[#0f0f0f]">Claude</option>
                <option value="gpt" className="bg-[#0f0f0f]">GPT</option>
                <option value="gemini" className="bg-[#0f0f0f]">Gemini</option>
                <option value="user" className="bg-[#0f0f0f]">User</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-[#8a8f9e] mb-1">
                Max Results (Limit)
              </label>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2 text-xs text-white outline-none rounded-none cursor-pointer"
              >
                <option value={3} className="bg-[#0f0f0f]">3 Results</option>
                <option value={5} className="bg-[#0f0f0f]">5 Results</option>
                <option value={10} className="bg-[#0f0f0f]">10 Results</option>
                <option value={20} className="bg-[#0f0f0f]">20 Results</option>
              </select>
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium py-2.5 rounded-none transition-all flex items-center justify-center gap-2 shadow-sm"
          >
            <PixelTerminal className="w-4 h-4 text-white" />
            <span>{isLoading ? 'Calculating similarity...' : 'Run Vector Search'}</span>
          </button>
        </form>
      </div>

      {/* RESULTS DISPLAY CARD */}
      {results !== null && (
        <div className="bg-[#181818] border border-[#262626] rounded-none overflow-hidden space-y-0">
          <div className="p-4 border-b border-[#262626] bg-[#161616] flex justify-between items-center text-xs text-[#8a8f9e]">
            <span>Vector relevance matches ({results.length})</span>
            <span>Hybrid score threshold: &gt; 0.10</span>
          </div>

          {showRawJson ? (
            <pre className="bg-[#0f0f0f] p-4 text-xs font-mono text-[#ff8800] overflow-x-auto">
              {JSON.stringify(results, null, 2)}
            </pre>
          ) : results.length === 0 ? (
            <div className="p-12 text-center text-[#8a8f9e]">
              No vector matches found above threshold
            </div>
          ) : (
            <div className="divide-y divide-[#262626]">
              {results.map((res, idx) => (
                <div key={res.id || idx} className="p-4 space-y-2 hover:bg-[#222222] transition-colors">
                  <div className="flex justify-between items-center gap-4">
                    <div className="flex flex-wrap items-center gap-2 min-w-0">
                      <span className="bg-[#ff6b00]/15 text-[#ff6b00] border border-[#ff6b00]/30 px-2 py-0.5 rounded-none text-[11px] font-medium uppercase flex-shrink-0">
                        {res.source}
                      </span>
                      <CategoryBadge category={res.category} />
                      <AgentBadge agent={res.source_agent} />
                      <span className="font-mono text-[11px] text-[#8a8f9e] truncate">id: {res.id}</span>
                    </div>

                    <span className="text-[#ff6b00] font-semibold text-xs bg-[#ff6b00]/15 border border-[#ff6b00]/30 px-2.5 py-1 rounded-none flex-shrink-0">
                      {(res.score * 100).toFixed(1)}% match
                    </span>
                  </div>

                  <p className="text-white text-xs leading-relaxed break-words break-all">{res.content}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
