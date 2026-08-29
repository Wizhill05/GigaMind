import React, { useState, useEffect } from 'react';
import { Plus, Filter, Search, Trash2, Edit3, ChevronLeft, ChevronRight, Copy, Check, Paperclip, ExternalLink, RefreshCw, FileText } from 'lucide-react';
import { PixelDatabase } from '../ui/PixelIcons';
import { Memory, StorageFile } from '../../types';
import { fetchMemories, deleteMemory, fetchIndexedFiles, reindexStorageFile } from '../../api';
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
  const [activeSubTab, setActiveSubTab] = useState<'memories' | 'files'>('memories');
  const [storageFiles, setStorageFiles] = useState<StorageFile[]>([]);
  const [isStorageLoading, setIsStorageLoading] = useState(false);
  const [reindexingKey, setReindexingKey] = useState<string | null>(null);

  const { toast } = useToast();

  const loadStorageFiles = async () => {
    setIsStorageLoading(true);
    const res = await fetchIndexedFiles(100);
    if (res && res.files) {
      setStorageFiles(res.files);
    }
    setIsStorageLoading(false);
  };

  const handleReindex = async (key: string) => {
    setReindexingKey(key);
    const ok = await reindexStorageFile(key);
    if (ok) {
      toast(`Re-indexing queued for ${key}`, 'success');
      setTimeout(loadStorageFiles, 1500);
    } else {
      toast('Could not queue vector extraction', 'error');
    }
    setReindexingKey(null);
  };

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
    if (activeSubTab === 'memories') {
      loadMemories();
    } else {
      loadStorageFiles();
    }
  }, [page, categoryFilter, sourceAgentFilter, activeSubTab]);
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
          <h2 className="text-xl font-semibold text-white tracking-tight">Memory &amp; Knowledge Repository</h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Manage persistent knowledge, user facts, and vectorized Cloudflare R2 files
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 bg-[#141414] border border-[#262626] p-1">
            <button
              onClick={() => setActiveSubTab('memories')}
              className={`px-3 py-1.5 text-xs font-medium transition-all ${
                activeSubTab === 'memories'
                  ? 'bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white shadow-sm'
                  : 'text-[#8a8f9e] hover:text-white'
              }`}
            >
              Memories ({totalCount})
            </button>
            <button
              onClick={() => setActiveSubTab('files')}
              className={`px-3 py-1.5 text-xs font-medium transition-all ${
                activeSubTab === 'files'
                  ? 'bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white shadow-sm'
                  : 'text-[#8a8f9e] hover:text-white'
              }`}
            >
              Indexed Files ({storageFiles.length})
            </button>
          </div>

          {activeSubTab === 'memories' && (
            <button
              onClick={onOpenNewModal}
              className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium px-4 py-2 rounded-none flex items-center gap-2 transition-all shadow-sm btn-press"
            >
              <Plus className="w-4 h-4" />
              <span>New Memory</span>
            </button>
          )}
        </div>
      </div>

      {activeSubTab === 'files' ? (
        /* STORAGE FILES VECTORIZED LIST */
        <div className="bg-[#181818] border border-[#262626] rounded-none overflow-hidden space-y-0">
          <div className="p-4 border-b border-[#262626] bg-[#161616] flex justify-between items-center">
            <span className="text-white font-medium flex items-center gap-2">
              <FileText className="w-4 h-4 text-[#ff6b00]" />
              <span>Cloudflare R2 Vectorized Files ({storageFiles.length})</span>
            </span>
            <button
              onClick={loadStorageFiles}
              disabled={isStorageLoading}
              className="flex items-center gap-1.5 bg-[#141414] hover:bg-[#202020] border border-[#333333] text-[#c1c5d0] px-3 py-1 text-xs transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${isStorageLoading ? 'animate-spin text-[#ff6b00]' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>

          {isStorageLoading ? (
            <div className="p-12 text-center text-[#8a8f9e]">Loading indexed documents...</div>
          ) : storageFiles.length === 0 ? (
            <div className="p-12 text-center text-[#8a8f9e]">
              No files have been uploaded and vectorized yet. Upload PDFs or documents via the Memory modal or FastMCP tools.
            </div>
          ) : (
            <div className="divide-y divide-[#262626]">
              {storageFiles.map((file) => (
                <div key={file.id} className="p-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 hover:bg-[#202020] transition-colors">
                  <div className="space-y-1 min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-white font-mono font-medium text-xs truncate max-w-[320px]">{file.filename}</span>
                      <span className={`px-2 py-0.5 text-[10px] font-mono uppercase border ${
                        file.indexing_status === 'completed'
                          ? 'bg-emerald-950/70 text-emerald-300 border-emerald-700/60'
                          : file.indexing_status === 'pending'
                          ? 'bg-amber-950/70 text-amber-300 border-amber-700/60'
                          : 'bg-zinc-800 text-zinc-400 border-zinc-700'
                      }`}>
                        {file.indexing_status}
                      </span>
                      <span className="bg-[#141414] border border-[#2a2a2a] px-2 py-0.5 text-[10px] font-mono text-zinc-400">
                        {file.total_chunks} chunks
                      </span>
                      {file.extracted_text_length > 0 && (
                        <span className="text-zinc-500 font-mono text-[10px]">
                          ({(file.extracted_text_length / 1000).toFixed(1)}k chars)
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] text-[#8a8f9e] font-mono truncate">
                      key: {file.key} &bull; uploaded {new Date(file.created_at).toLocaleString()}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {file.url && (
                      <a
                        href={file.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 bg-[#141414] hover:bg-[#252525] border border-[#333333] text-white px-2.5 py-1 text-xs transition-colors"
                        title="Download / Open from R2"
                      >
                        <ExternalLink className="w-3 h-3" />
                        <span>Open File</span>
                      </a>
                    )}
                    <button
                      onClick={() => handleReindex(file.key)}
                      disabled={reindexingKey === file.key}
                      className="flex items-center gap-1 bg-[#141414] hover:bg-[#252525] border border-[#333333] text-[#c1c5d0] px-2.5 py-1 text-xs transition-colors disabled:opacity-50"
                      title="Re-extract text and re-generate embeddings"
                    >
                      <RefreshCw className={`w-3 h-3 ${reindexingKey === file.key ? 'animate-spin text-[#ff6b00]' : ''}`} />
                      <span>Re-index</span>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        /* MEMORIES LIST */
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

                      {mem.attachments && mem.attachments.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          {mem.attachments.map((att, attIdx) => (
                            <span
                              key={att.key || attIdx}
                              className="inline-flex items-center gap-1 bg-[#141414] border border-[#2a2a2a] px-2 py-0.5 text-[11px] text-[#c1c5d0]"
                            >
                              <Paperclip className="w-3 h-3 text-[#ff6b00]" />
                              <span className="font-mono truncate max-w-[140px]">{att.filename}</span>
                              {att.url && (
                                <a
                                  href={att.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  className="text-[#8a8f9e] hover:text-[#ff6b00] transition-colors ml-0.5"
                                  title="Download / Open file from Cloudflare R2"
                                >
                                  <ExternalLink className="w-3 h-3" />
                                </a>
                              )}
                            </span>
                          ))}
                        </div>
                      )}

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
      )}
    </div>
  );
};
