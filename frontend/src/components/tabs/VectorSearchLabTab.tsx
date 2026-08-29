import React, { useState } from 'react';
import { Search, Code, Paperclip, ExternalLink, ImageIcon, X } from 'lucide-react';
import { PixelSparkles, PixelTerminal } from '../ui/PixelIcons';
import { SearchResult } from '../../types';
import { searchMemory } from '../../api';
import { AgentBadge, CategoryBadge } from '../ui/Badge';

export const VectorSearchLabTab: React.FC = () => {
  const [query, setQuery] = useState('');
  const [queryImageBase64, setQueryImageBase64] = useState<string | null>(null);
  const [queryImageName, setQueryImageName] = useState<string | null>(null);
  const [scope, setScope] = useState<'all' | 'memories' | 'files'>('all');
  const [category, setCategory] = useState('');
  const [sourceAgent, setSourceAgent] = useState('');
  const [limit, setLimit] = useState(5);

  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [showRawJson, setShowRawJson] = useState(false);
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() && !queryImageBase64) return;

    setIsLoading(true);
    const res = await searchMemory(
      query.trim() || undefined,
      category || undefined,
      sourceAgent || undefined,
      limit,
      scope,
      queryImageBase64 || undefined
    );
    setResults(res);
    setIsLoading(false);
  };

  const handleImageQuerySelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const b64 = (reader.result as string).split(',')[1];
      setQueryImageBase64(b64);
      setQueryImageName(file.name);
    };
    reader.readAsDataURL(file);
    e.target.value = '';
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
          {/* SEARCH SCOPE TOGGLE */}
          <div className="flex items-center gap-2 border-b border-[#262626] pb-3">
            <span className="text-[#8a8f9e] text-xs font-medium">Search Domain:</span>
            <div className="flex items-center gap-1 bg-[#101010] p-1 border border-[#262626]">
              <button
                type="button"
                onClick={() => setScope('all')}
                className={`px-3 py-1 text-xs font-medium transition-all ${
                  scope === 'all'
                    ? 'bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white shadow-sm'
                    : 'text-[#8a8f9e] hover:text-white'
                }`}
              >
                All Knowledge (Memories + Files)
              </button>
              <button
                type="button"
                onClick={() => setScope('memories')}
                className={`px-3 py-1 text-xs font-medium transition-all ${
                  scope === 'memories'
                    ? 'bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white shadow-sm'
                    : 'text-[#8a8f9e] hover:text-white'
                }`}
              >
                Memories Only
              </button>
              <button
                type="button"
                onClick={() => setScope('files')}
                className={`px-3 py-1 text-xs font-medium transition-all ${
                  scope === 'files'
                    ? 'bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white shadow-sm'
                    : 'text-[#8a8f9e] hover:text-white'
                }`}
              >
                Files / R2 Storage Only
              </button>
            </div>
          </div>


          {/* QUERY INPUT ROW WITH VISUAL QUERY UPLOAD */}
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-[#8a8f9e] absolute left-3.5 top-3" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Enter prompt query or concept text to test embedding relevance..."
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 pl-10 text-white placeholder-[#8a8f9e] outline-none rounded-none font-sans text-xs"
              />
            </div>

            <label
              className={`px-3 py-2 border transition-colors flex items-center gap-1.5 cursor-pointer font-mono text-[11px] ${
                queryImageBase64
                  ? 'bg-[#22c55e]/15 border-[#22c55e]/40 text-[#22c55e]'
                  : 'bg-[#1f1f1f] hover:bg-[#282828] text-[#8a8f9e] hover:text-white border-[#262626]'
              }`}
              title="Search with Image Screenshot / Diagram"
            >
              <ImageIcon className="w-3.5 h-3.5" />
              <span>{queryImageBase64 ? 'Image Attached' : 'Visual Search'}</span>
              <input type="file" accept="image/*" className="hidden" onChange={handleImageQuerySelect} />
            </label>
          </div>

          {queryImageName && (
            <div className="flex items-center gap-2 text-[11px] font-mono bg-[#141414] p-1.5 px-3 border border-[#262626] text-[#86efac]">
              <ImageIcon className="w-3 h-3" />
              <span>Visual Query: <strong>{queryImageName}</strong></span>
              <button
                type="button"
                onClick={() => { setQueryImageBase64(null); setQueryImageName(null); }}
                className="ml-auto text-[#8a8f9e] hover:text-white"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
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
                      {res.source === 'file' ? (
                        <span className="bg-emerald-950/70 text-emerald-300 border border-emerald-700/60 px-2 py-0.5 rounded-none text-[11px] font-mono font-medium uppercase flex-shrink-0 flex items-center gap-1">
                          <Paperclip className="w-3 h-3 text-emerald-400" />
                          <span>FILE CHUNK</span>
                        </span>
                      ) : (
                        <span className="bg-[#ff6b00]/15 text-[#ff6b00] border border-[#ff6b00]/30 px-2 py-0.5 rounded-none text-[11px] font-medium uppercase flex-shrink-0">
                          {res.source}
                        </span>
                      )}

                      {res.filename && (
                        <span className="font-mono text-[11px] text-white font-medium">
                          {res.filename}
                        </span>
                      )}

                      {res.citation && (
                        <span className="font-mono text-[11px] text-[#8a8f9e] bg-[#141414] px-1.5 py-0.5 border border-[#2a2a2a]">
                          {res.citation}
                        </span>
                      )}

                      {res.category && res.source !== 'file' && <CategoryBadge category={res.category} />}
                      {res.source_agent && res.source !== 'file' && <AgentBadge agent={res.source_agent} />}
                      <span className="font-mono text-[11px] text-[#8a8f9e] truncate">id: {res.id}</span>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0">
                      {res.url && (
                        <a
                          href={res.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[11px] flex items-center gap-1 text-[#8a8f9e] hover:text-[#ff6b00] bg-[#161616] border border-[#333333] px-2 py-1 transition-colors"
                        >
                          <ExternalLink className="w-3 h-3" />
                          <span>Open File</span>
                        </a>
                      )}
                      <span className="text-[#ff6b00] font-semibold text-xs bg-[#ff6b00]/15 border border-[#ff6b00]/30 px-2.5 py-1 rounded-none flex-shrink-0">
                        {(res.score * 100).toFixed(1)}% match
                      </span>
                    </div>
                  </div>

                  <p className="text-white text-xs leading-relaxed break-words break-all">{res.content}</p>

                  {res.attachments && res.attachments.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                      {res.attachments.map((att, attIdx) => (
                        <span
                          key={att.key || attIdx}
                          className="inline-flex items-center gap-1 bg-[#121212] border border-[#2a2a2a] px-2 py-0.5 text-[11px] text-[#c1c5d0]"
                        >
                          <Paperclip className="w-3 h-3 text-[#ff6b00]" />
                          <span className="font-mono truncate max-w-[150px]">{att.filename}</span>
                          {att.url && (
                            <a
                              href={att.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[#8a8f9e] hover:text-[#ff6b00] transition-colors ml-0.5"
                              title="Open / Download attached file"
                            >
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          )}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
