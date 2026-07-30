import React, { useState, useEffect } from 'react';
import { Plus, Filter, Search, Trash2, Edit3, ChevronLeft, ChevronRight, Copy, Check } from 'lucide-react';
import { PixelDatabase } from '../ui/PixelIcons';
import { Memory } from '../../types';
import { fetchMemories, deleteMemory } from '../../api';
import { AgentBadge, CategoryBadge } from '../ui/Badge';
import { useToast } from '../ui/Toast';

interface MemoriesTabProps {
  onOpenNewModal: () => void;
  onOpenEditModal: (mem: Memory) => void;
}

export const MemoriesTab: React.FC<MemoriesTabProps> = ({ onOpenNewModal, onOpenEditModal }) => {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);

  const [isLoading, setIsLoading] = useState(true);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [sourceAgentFilter, setSourceAgentFilter] = useState('');
  const [searchFilter, setSearchFilter] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);

  const { toast } = useToast();

  const loadMemories = async () => {
    setIsLoading(true);
    const res = await fetchMemories(page, 10, categoryFilter || undefined, sourceAgentFilter || undefined);
    if (res) {
      setMemories(res.memories);
      setTotalPages(res.pages || 1);
      setTotalCount(res.total || 0);
    }
    setIsLoading(false);
  };

  useEffect(() => {
    loadMemories();
  }, [page, categoryFilter, sourceAgentFilter]);

  const handleDelete = async (id: string) => {
    if (window.confirm(`Confirm deletion of memory item: ${id}?`)) {
      const ok = await deleteMemory(id);
      if (ok) {
        toast(`Memory ${id} deleted successfully`, 'success');
        loadMemories();
      }
    }
  };

  const handleCopyJson = (mem: Memory) => {
    navigator.clipboard.writeText(JSON.stringify(mem, null, 2));
    setCopiedId(mem.id);
    toast(`Copied memory JSON to clipboard`, 'success');
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

  // Keyboard Arrow Navigation inside list
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (filteredMemories.length === 0) return;
      if (document.activeElement?.tagName === 'INPUT' || document.activeElement?.tagName === 'TEXTAREA') return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % filteredMemories.length);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredMemories.length) % filteredMemories.length);
      } else if (e.key === 'Enter' && selectedIndex >= 0 && selectedIndex < filteredMemories.length) {
        e.preventDefault();
        onOpenEditModal(filteredMemories[selectedIndex]);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [filteredMemories, selectedIndex, onOpenEditModal]);

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER & TOP CONTROLS */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white tracking-tight">Memory Repository</h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Manage persistent knowledge, user facts, and contextual statements ({totalCount} total)
          </p>
        </div>

        <button
          onClick={onOpenNewModal}
          className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium px-4 py-2 rounded-none flex items-center gap-2 transition-all shadow-sm btn-press"
        >
          <Plus className="w-4 h-4" />
          <span>New Memory</span>
        </button>
      </div>

      {/* RENDER SERVICE STACK CARD */}
      <div className="bg-[#181818] border border-[#262626] rounded-none overflow-hidden space-y-0">
        {/* FILTER BAR HEADER */}
        <div className="p-4 border-b border-[#262626] bg-[#161616] flex flex-col md:flex-row justify-between items-stretch md:items-center gap-3">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-[#8a8f9e] absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              placeholder="Filter memory records... (Use ↑ ↓ arrow keys to navigate)"
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] pl-9 pr-3 py-1.5 text-xs text-white placeholder-[#8a8f9e] outline-none rounded-none font-sans transition-colors"
            />
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 bg-[#0f0f0f] border border-[#262626] px-2.5 py-1.5 rounded-none text-xs text-[#8a8f9e]">
              <Filter className="w-3.5 h-3.5" />
              <select
                value={categoryFilter}
                onChange={(e) => {
                  setCategoryFilter(e.target.value);
                  setPage(1);
                }}
                className="bg-transparent text-white outline-none cursor-pointer"
              >
                <option value="" className="bg-[#0f0f0f]">All Categories</option>
                <option value="general" className="bg-[#0f0f0f]">general</option>
                <option value="coding" className="bg-[#0f0f0f]">coding</option>
                <option value="personal" className="bg-[#0f0f0f]">personal</option>
                <option value="project" className="bg-[#0f0f0f]">project</option>
                <option value="chatgpt_import" className="bg-[#0f0f0f]">chatgpt_import</option>
                <option value="claude_import" className="bg-[#0f0f0f]">claude_import</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 bg-[#0f0f0f] border border-[#262626] px-2.5 py-1.5 rounded-none text-xs text-[#8a8f9e]">
              <select
                value={sourceAgentFilter}
                onChange={(e) => {
                  setSourceAgentFilter(e.target.value);
                  setPage(1);
                }}
                className="bg-transparent text-white outline-none cursor-pointer"
              >
                <option value="" className="bg-[#0f0f0f]">All Source Agents</option>
                <option value="claude" className="bg-[#0f0f0f]">Claude</option>
                <option value="gpt" className="bg-[#0f0f0f]">GPT</option>
                <option value="gemini" className="bg-[#0f0f0f]">Gemini</option>
                <option value="user" className="bg-[#0f0f0f]">User</option>
              </select>
            </div>
          </div>
        </div>

        {/* SKELETON LOADING OR ROWS STACK */}
        {isLoading ? (
          <div className="divide-y divide-[#262626] p-2 space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="p-4 bg-[#0f0f0f] border border-[#262626] animate-pulse space-y-3">
                <div className="h-4 bg-[#262626] rounded-none w-3/4" />
                <div className="flex items-center gap-3">
                  <div className="h-3 bg-[#222222] w-16" />
                  <div className="h-3 bg-[#222222] w-12" />
                  <div className="h-3 bg-[#222222] w-24" />
                </div>
              </div>
            ))}
          </div>
        ) : filteredMemories.length === 0 ? (
          <div className="p-12 text-center text-[#8a8f9e]">
            No memory records match the selected filter criteria
          </div>
        ) : (
          <div className="divide-y divide-[#262626]">
            {filteredMemories.map((mem, idx) => {
              const isSelected = selectedIndex === idx;
              return (
                <div
                  key={mem.id}
                  onClick={() => setSelectedIndex(idx)}
                  className={`p-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 transition-all group ${
                    isSelected
                      ? 'bg-[#222222] border-l-2 border-l-[#ff6b00]'
                      : 'hover:bg-[#222222]'
                  }`}
                >
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <div className="w-7 h-7 rounded-none bg-[#ff6b00]/10 border border-[#ff6b00]/30 text-[#ff6b00] flex items-center justify-center flex-shrink-0 mt-0.5">
                      <PixelDatabase className="w-4 h-4 text-[#ff6b00]" />
                    </div>

                    <div className="space-y-1.5 flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-white font-medium text-xs break-words break-all">
                          {mem.content}
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-3 text-[#8a8f9e] text-xs">
                        <CategoryBadge category={mem.category} />
                        <AgentBadge agent={mem.source_agent} />
                        <span className="font-mono text-[11px] truncate">id: {mem.id}</span>
                        {mem.created_at && (
                          <span>{new Date(mem.created_at).toLocaleString()}</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* ROW ACTIONS */}
                  <div className="flex items-center gap-2 flex-shrink-0 opacity-90 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => handleCopyJson(mem)}
                      className="bg-[#161616] border border-[#333333] hover:border-[#ff6b00]/40 text-[#c1c5d0] hover:text-white px-3 py-1.5 rounded-none text-xs transition-colors flex items-center gap-1.5 btn-press"
                    >
                      {copiedId === mem.id ? <Check className="w-3.5 h-3.5 text-amber-400" /> : <Copy className="w-3.5 h-3.5" />}
                      <span>{copiedId === mem.id ? 'Copied' : 'JSON'}</span>
                    </button>

                    <button
                      onClick={() => onOpenEditModal(mem)}
                      className="bg-[#161616] border border-[#333333] hover:border-[#ff6b00]/40 text-[#c1c5d0] hover:text-white px-3 py-1.5 rounded-none text-xs transition-colors flex items-center gap-1.5 btn-press"
                    >
                      <Edit3 className="w-3.5 h-3.5" />
                      <span>Edit</span>
                    </button>

                    <button
                      onClick={() => handleDelete(mem.id)}
                      className="bg-[#161616] border border-[#333333] hover:border-rose-500/40 text-rose-400 hover:text-rose-300 px-3 py-1.5 rounded-none text-xs transition-colors flex items-center gap-1.5 btn-press"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Delete</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* PAGINATION FOOTER */}
        <div className="p-4 border-t border-[#262626] bg-[#161616] flex justify-between items-center text-xs text-[#8a8f9e]">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed btn-press"
          >
            <ChevronLeft className="w-4 h-4" /> Previous
          </button>

          <span>Page {page} of {totalPages}</span>

          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="flex items-center gap-1 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed btn-press"
          >
            Next <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
