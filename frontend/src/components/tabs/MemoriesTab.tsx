import React, { useState, useEffect } from 'react';
import { Plus, Filter, Search, Trash2, Edit3, ChevronLeft, ChevronRight, Copy, Check, CheckCircle2 } from 'lucide-react';
import { Memory } from '../../types';
import { fetchMemories, deleteMemory } from '../../api';
import { AgentBadge, CategoryBadge } from '../ui/Badge';

interface MemoriesTabProps {
  onOpenNewModal: () => void;
  onOpenEditModal: (mem: Memory) => void;
}

export const MemoriesTab: React.FC<MemoriesTabProps> = ({ onOpenNewModal, onOpenEditModal }) => {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);

  const [categoryFilter, setCategoryFilter] = useState('');
  const [sourceAgentFilter, setSourceAgentFilter] = useState('');
  const [searchFilter, setSearchFilter] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadMemories = async () => {
    const res = await fetchMemories(page, 10, categoryFilter || undefined, sourceAgentFilter || undefined);
    if (res) {
      setMemories(res.memories);
      setTotalPages(res.pages || 1);
      setTotalCount(res.total || 0);
    }
  };

  useEffect(() => {
    loadMemories();
  }, [page, categoryFilter, sourceAgentFilter]);

  const handleDelete = async (id: string) => {
    if (window.confirm(`Confirm deletion of memory item: ${id}?`)) {
      const ok = await deleteMemory(id);
      if (ok) loadMemories();
    }
  };

  const handleCopyJson = (mem: Memory) => {
    navigator.clipboard.writeText(JSON.stringify(mem, null, 2));
    setCopiedId(mem.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const filteredMemories = memories.filter((mem) => {
    if (!searchFilter.trim()) return true;
    return (
      mem.content.toLowerCase().includes(searchFilter.toLowerCase()) ||
      mem.category.toLowerCase().includes(searchFilter.toLowerCase()) ||
      mem.tags.some((t) => t.toLowerCase().includes(searchFilter.toLowerCase()))
    );
  });

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER & TOP CONTROLS */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">Memory Repository</h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Manage persistent knowledge, user facts, and contextual statements ({totalCount} total)
          </p>
        </div>

        <button
          onClick={onOpenNewModal}
          className="bg-[#5b0e89] hover:bg-[#6d10a3] text-white font-medium px-4 py-2 rounded-md flex items-center gap-2 transition-colors shadow-sm"
        >
          <Plus className="w-4 h-4" />
          <span>New Memory</span>
        </button>
      </div>

      {/* RENDER SERVICE STACK CARD (Matching Image 1) */}
      <div className="bg-[#13151c] border border-[#1e2029] rounded-lg overflow-hidden space-y-0">
        {/* FILTER BAR HEADER */}
        <div className="p-4 border-b border-[#1e2029] bg-[#101216] flex flex-col md:flex-row justify-between items-stretch md:items-center gap-3">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-[#8a8f9e] absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              placeholder="Filter memory records..."
              className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#5b0e89] pl-9 pr-3 py-1.5 text-xs text-white placeholder-[#8a8f9e] outline-none rounded-md"
            />
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 bg-[#0a0b0e] border border-[#1e2029] px-2.5 py-1.5 rounded-md text-xs text-[#8a8f9e]">
              <Filter className="w-3.5 h-3.5" />
              <select
                value={categoryFilter}
                onChange={(e) => {
                  setCategoryFilter(e.target.value);
                  setPage(1);
                }}
                className="bg-transparent text-white outline-none cursor-pointer"
              >
                <option value="" className="bg-[#0a0b0e]">All Categories</option>
                <option value="general" className="bg-[#0a0b0e]">general</option>
                <option value="coding" className="bg-[#0a0b0e]">coding</option>
                <option value="personal" className="bg-[#0a0b0e]">personal</option>
                <option value="project" className="bg-[#0a0b0e]">project</option>
                <option value="chatgpt_import" className="bg-[#0a0b0e]">chatgpt_import</option>
                <option value="claude_import" className="bg-[#0a0b0e]">claude_import</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 bg-[#0a0b0e] border border-[#1e2029] px-2.5 py-1.5 rounded-md text-xs text-[#8a8f9e]">
              <select
                value={sourceAgentFilter}
                onChange={(e) => {
                  setSourceAgentFilter(e.target.value);
                  setPage(1);
                }}
                className="bg-transparent text-white outline-none cursor-pointer"
              >
                <option value="" className="bg-[#0a0b0e]">All Source Agents</option>
                <option value="claude" className="bg-[#0a0b0e]">Claude</option>
                <option value="gpt" className="bg-[#0a0b0e]">GPT</option>
                <option value="gemini" className="bg-[#0a0b0e]">Gemini</option>
                <option value="user" className="bg-[#0a0b0e]">User</option>
              </select>
            </div>
          </div>
        </div>

        {/* ROWS STACK (Matching Image 1 Render Deploy Feed) */}
        {filteredMemories.length === 0 ? (
          <div className="p-12 text-center text-[#8a8f9e]">
            No memory records match the selected filter criteria
          </div>
        ) : (
          <div className="divide-y divide-[#1e2029]">
            {filteredMemories.map((mem) => (
              <div
                key={mem.id}
                className="p-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 hover:bg-[#181a24] transition-colors group"
              >
                <div className="flex items-start gap-3 flex-1">
                  <div className="w-7 h-7 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <CheckCircle2 className="w-4 h-4" />
                  </div>

                  <div className="space-y-1.5 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-white font-medium text-xs">
                        {mem.content}
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-[#8a8f9e] text-xs">
                      <CategoryBadge category={mem.category} />
                      <AgentBadge agent={mem.source_agent} />
                      <span className="font-mono text-[11px]">id: {mem.id}</span>
                      {mem.created_at && (
                        <span>{new Date(mem.created_at).toLocaleString()}</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* ROW ACTIONS */}
                <div className="flex items-center gap-2 opacity-90 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => handleCopyJson(mem)}
                    className="bg-[#101216] border border-[#262936] hover:border-[#3f4357] text-[#c1c5d0] hover:text-white px-3 py-1.5 rounded-md text-xs transition-colors flex items-center gap-1.5"
                  >
                    {copiedId === mem.id ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedId === mem.id ? 'Copied' : 'JSON'}</span>
                  </button>

                  <button
                    onClick={() => onOpenEditModal(mem)}
                    className="bg-[#101216] border border-[#262936] hover:border-[#3f4357] text-[#c1c5d0] hover:text-white px-3 py-1.5 rounded-md text-xs transition-colors flex items-center gap-1.5"
                  >
                    <Edit3 className="w-3.5 h-3.5" />
                    <span>Edit</span>
                  </button>

                  <button
                    onClick={() => handleDelete(mem.id)}
                    className="bg-[#101216] border border-[#262936] hover:border-rose-500/40 text-rose-400 hover:text-rose-300 px-3 py-1.5 rounded-md text-xs transition-colors flex items-center gap-1.5"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Delete</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* PAGINATION FOOTER */}
        <div className="p-4 border-t border-[#1e2029] bg-[#101216] flex justify-between items-center text-xs text-[#8a8f9e]">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="w-4 h-4" /> Previous
          </button>

          <span>Page {page} of {totalPages}</span>

          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="flex items-center gap-1 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Next <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
