import React, { useState, useEffect, useRef } from 'react';
import {
  Filter,
  Eye,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  Upload,
  FileJson,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  X,
  FolderInput,
  Search,
  Sparkles,
  Trash2,
  Clock,
  Zap
} from 'lucide-react';
import { PixelTerminal } from '../ui/PixelIcons';
import { Conversation } from '../../types';
import {
  fetchConversations,
  type ConversationSearchResult,
  getApiKey,
  importConversationsFile,
  searchConversations,
  deleteConversation,
  vectorizeConversation,
  backfillConversationVectors
} from '../../api';
import { AgentBadge } from '../ui/Badge';
import { useToast } from '../ui/Toast';

interface ConversationsTabProps {
  onOpenTranscript: (conv: Conversation) => void;
  refreshVersion?: number;
  onMutation?: () => void;
}

export const ConversationsTab: React.FC<ConversationsTabProps> = ({ onOpenTranscript, refreshVersion = 0, onMutation = () => {} }) => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [totalVectorized, setTotalVectorized] = useState(0);
  const [platformFilter, setPlatformFilter] = useState('');
  const [sourceAgentFilter, setSourceAgentFilter] = useState('');

  // Transcript search state
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<ConversationSearchResult[] | null>(null);

  const searchRequest = useRef<AbortController | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [localRefresh, setLocalRefresh] = useState(0);

  // Import Chat History State
  const [showImportCard, setShowImportCard] = useState(false);
  const [importPlatform, setImportPlatform] = useState('');
  const [isImporting, setIsImporting] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [isBackfilling, setIsBackfilling] = useState(false);
  const [importStatus, setImportStatus] = useState<string | null>(null);

  const { toast } = useToast();

  const listRequest = useRef<AbortController | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const loadConversations = async () => {
    listRequest.current?.abort();
    const controller = new AbortController();
    listRequest.current = controller;
    const key = getApiKey();
    setListLoading(true); setLoadError(null); setConversations([]);
    try {
      const res = await fetchConversations(page, 10, platformFilter || undefined, sourceAgentFilter || undefined, controller.signal);
      if (controller.signal.aborted || key !== getApiKey()) return;
      if (page > Math.max(1, res.pages)) { setPage(Math.max(1, res.pages)); return; }
      setConversations(res.conversations);
      setTotalPages(res.pages || 1);
      setTotalCount(res.total);
      setTotalVectorized(res.total_vectorized);
      setLoadError(null);
    } catch (error) {
      if (!controller.signal.aborted && key === getApiKey()) setLoadError(error instanceof Error ? error.message : 'Unable to load conversations');
    } finally {
      if (!controller.signal.aborted && key === getApiKey()) setListLoading(false);
    }
  };

  useEffect(() => {
    void loadConversations();
    return () => listRequest.current?.abort();
  }, [page, platformFilter, sourceAgentFilter, refreshVersion, localRefresh]);

  useEffect(() => {
    searchRequest.current?.abort();
    if (!submittedQuery) { setSearchResults(null); setSearchError(null); setIsSearching(false); return; }
    const controller = new AbortController();
    searchRequest.current = controller;
    const key = getApiKey();
    setSearchResults([]); setSearchError(null); setIsSearching(true);
    void searchConversations(submittedQuery, platformFilter || undefined, sourceAgentFilter || undefined, 10, controller.signal)
      .then(results => { if (!controller.signal.aborted && key === getApiKey()) setSearchResults(results); })
      .catch(error => { if (!controller.signal.aborted && key === getApiKey()) setSearchError(error instanceof Error ? error.message : 'Search failed'); })
      .finally(() => { if (!controller.signal.aborted && key === getApiKey()) setIsSearching(false); });
    return () => controller.abort();
  }, [submittedQuery, platformFilter, sourceAgentFilter, localRefresh, refreshVersion]);

  const handleTranscriptSearch = (e?: React.FormEvent) => {
    e?.preventDefault();
    searchRequest.current?.abort();
    setSearchResults(null); setSearchError(null);
    if (submittedQuery === searchQuery.trim()) setLocalRefresh(v => v + 1);
    else setSubmittedQuery(searchQuery.trim());
  };
  const changed = () => { searchRequest.current?.abort(); listRequest.current?.abort(); setSearchResults(submittedQuery ? [] : null); setIsSearching(!!submittedQuery); setConversations([]); setListLoading(true); setLocalRefresh(v => v + 1); onMutation(); };

  const runMutation = async (action: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try { await action(); }
    catch (error) { toast(error instanceof Error ? error.message : 'Request failed', 'error'); }
    finally { busyRef.current = false; setBusy(false); }
  };

  const submitImport = async (selected: File) => runMutation(async () => {
    setIsImporting(true);
    setImportStatus(`Uploading ${selected.name}...`);
    try {
      const result = await importConversationsFile(selected, importPlatform || undefined);
      setImportStatus(`Imported ${result.ingested}; skipped ${result.skipped}; ${result.pending_indexing} pending indexing.`);
      toast(result.message, 'success');
      setFile(null);
      changed();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Import failed';
      setImportStatus(`Error: ${message}`);
      toast(message, 'error');
    } finally { setIsImporting(false); }
  });
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (!selected || busyRef.current) return;
    setFile(selected);
    e.target.value = '';
    void submitImport(selected);
  };
  const handleDeleteConversation = (id: string, title?: string) => {
    if (busyRef.current || !window.confirm(`Permanently delete conversation transcript "${title || id}" from database?`)) return;
    void runMutation(async () => { await deleteConversation(id); toast('Deleted conversation transcript', 'success'); changed(); });
  };
  const handleVectorizeSingle = (id: string) => {
    void runMutation(async () => { await vectorizeConversation(id); toast('Vectorization request completed', 'success'); changed(); });
  };
  const handleBackfillAll = () => {
    void runMutation(async () => {
      setIsBackfilling(true);
      try { const result = await backfillConversationVectors(); toast(result.message, 'success'); changed(); }
      finally { setIsBackfilling(false); }
    });
  };

  const resultsById = new Map(searchResults?.map(result => [result.id, result]));

  return (
    <fieldset disabled={busy} className="space-y-6 font-sans text-xs">
      {/* HEADER & TOP CONTROLS */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-[#141414] border border-[#262626] p-5 rounded-none">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-[#ff6b00]/10 border border-[#ff6b00]/30 flex items-center justify-center text-[#ff6b00]">
              <MessageSquare className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-white tracking-tight">Chat Logs & Transcripts</h2>
                <span className="px-2 py-0.2 bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/30 font-mono text-[10px] font-semibold">
                  {totalVectorized} / {totalCount} Vectorized
                </span>
              </div>
              <p className="text-xs text-[#8a8f9e]">
                Conversation history exports from Claude, ChatGPT, and AI agent sessions
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <button
            onClick={() => { searchRequest.current?.abort(); setSubmittedQuery(''); setSearchResults(null); setSearchQuery(''); setLocalRefresh(v => v + 1); }}
            className="px-3 py-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-[#c1c5d0] hover:text-white border border-[#333333] transition-colors flex items-center gap-1.5 font-mono text-[11px]"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>

          <button
            onClick={handleBackfillAll}
            disabled={busy}
            className="px-3 py-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-[#22c55e] hover:text-white border border-[#333333] transition-colors flex items-center gap-1.5 font-mono text-[11px]"
            title="Compute Gemini Embedding 2 vectors for all unindexed transcripts"
          >
            <Zap className={`w-3.5 h-3.5 ${isBackfilling ? 'animate-spin' : ''}`} />
            <span>Vectorize All</span>
          </button>

          <button
            disabled={busy}
            onClick={() => setShowImportCard(!showImportCard)}
            className="px-3.5 py-1.5 bg-[#ff6b00] hover:bg-[#e05e00] text-white font-medium border border-[#ff6b00] transition-colors flex items-center gap-1.5 font-sans text-xs shadow-sm shadow-[#ff6b00]/20"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>{showImportCard ? 'Close Importer' : 'Import Chat History'}</span>
          </button>
        </div>
      </div>

      {/* CHAT TRANSCRIPT IMPORT CARD */}
      {showImportCard && (
        <div className="bg-[#141414] border border-[#262626] p-5 rounded-none space-y-4 animate-slide-up">
          <div className="flex items-center justify-between border-b border-[#262626] pb-3">
            <div className="flex items-center gap-2">
              <FolderInput className="w-4 h-4 text-[#ff6b00]" />
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider font-mono">
                Import Conversations Export (Claude / ChatGPT / JSON)
              </h3>
            </div>
            <button
              disabled={busy}
              onClick={() => setShowImportCard(false)}
              className="text-[#8a8f9e] hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <select disabled={busy} value={importPlatform} onChange={e => setImportPlatform(e.target.value)} aria-label="Import format" className="bg-[#161616] text-white p-2">
              <option value="">Auto-Detect Format (Claude/GPT)</option>
              <option value="claude">Claude Export</option>
              <option value="chatgpt">ChatGPT Export</option>
            </select>
            {/* METHOD B: BROWSER FILE UPLOAD */}
            <div className="bg-[#0f0f0f] border border-[#262626] p-4 flex flex-col justify-between space-y-3">
              <div>
                <div className="flex items-center gap-2">
                  <FileJson className="w-3.5 h-3.5 text-[#22c55e]" />
                  <span className="font-semibold text-white text-xs">Upload JSON Export</span>
                </div>
                <p className="text-[11px] text-[#8a8f9e] mt-1">
                  Select and upload an exported <code>conversations.json</code> file from Claude/ChatGPT settings:
                </p>
              </div>

              <label className="border-2 border-dashed border-[#333333] hover:border-[#ff6b00] p-4 text-center cursor-pointer transition-colors block bg-[#141414]">
                <FileJson className="w-6 h-6 mx-auto text-[#8a8f9e] mb-1.5" />
                <span className="text-xs text-white font-medium block">Click to select conversations.json</span>
                <span className="text-[10px] text-[#8a8f9e] font-mono block mt-0.5">Supports Claude &amp; ChatGPT exports</span>
                <input
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={handleFileUpload}
                  disabled={busy}
                />
              </label>
            </div>
          </div>

          {file && !isImporting && <button disabled={busy} onClick={() => void submitImport(file)} className="text-[#ff6b00] underline">Retry {file.name}</button>}
          {importStatus && (
            <div className={`p-3 border font-mono text-[11px] flex items-center gap-2 ${
              importStatus.startsWith('Error')
                ? 'bg-rose-950/40 text-rose-300 border-rose-800/50'
                : 'bg-[#05200f] text-[#86efac] border-[#144625]'
            }`}>
              {importStatus.startsWith('Error') ? (
                <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
              ) : (
                <CheckCircle2 className="w-4 h-4 text-[#22c55e] flex-shrink-0" />
              )}
              <span>{importStatus}</span>
            </div>
          )}
        </div>
      )}

      {/* TRANSCRIPT SEARCH BAR */}
      <div className="bg-[#141414] border border-[#262626] p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-white font-mono text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5 text-[#ff6b00]" />
            <span>Transcript Search</span>
          </div>
        </div>

        <form onSubmit={handleTranscriptSearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-[#8a8f9e] absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => { searchRequest.current?.abort(); setSubmittedQuery(''); setSearchResults(null); setIsSearching(false); setSearchQuery(e.target.value); }}
              placeholder="Search conversation sessions (e.g. 'Laptop for Blender', 'Body temperature recovery', 'FastAPI OAuth')..."
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 pl-10 text-white placeholder-[#8a8f9e] outline-none font-sans text-xs"
            />
          </div>
          <button
            type="submit"
            disabled={isSearching}
            className="px-4 py-2 bg-[#ff6b00] hover:bg-[#e05e00] text-white font-medium transition-colors flex items-center gap-1.5 font-sans text-xs disabled:opacity-50"
          >
            {isSearching ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
            <span>Search Transcripts</span>
          </button>
          {searchResults !== null && (
            <button
              type="button"
              onClick={() => { searchRequest.current?.abort(); setSubmittedQuery(''); setSearchResults(null); setSearchQuery(''); }}
              className="px-3 py-2 bg-[#1f1f1f] hover:bg-[#282828] text-[#8a8f9e] hover:text-white border border-[#333333] transition-colors"
            >
              Clear
            </button>
          )}
        </form>
      </div>

      {/* RENDER SERVICE STACK CARD */}
      <div className="bg-[#141414] border border-[#262626] rounded-none overflow-hidden space-y-0">
        {/* LOG FILTER HEADER */}
        <div className="p-4 border-b border-[#262626] bg-[#161616] flex flex-col md:flex-row justify-between items-stretch md:items-center gap-3">
          <div className="flex items-center gap-2">
            <PixelTerminal className="w-4 h-4 text-[#ff6b00]" />
            <span className="font-semibold text-white">Application Transcript Logs</span>
            <span className="px-1.5 py-0.5 bg-[#262626] text-[#8a8f9e] font-mono text-[10px]">
              {searchResults !== null ? `${searchResults.length} matching result(s)` : `${totalCount} total`}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 bg-[#0f0f0f] border border-[#262626] px-2.5 py-1.5 rounded-none text-xs text-[#8a8f9e]">
              <Filter className="w-3.5 h-3.5" />
              <select
                value={platformFilter}
                onChange={(e) => {
                  searchRequest.current?.abort(); setSearchResults(submittedQuery ? [] : null); setConversations([]);
                  setPlatformFilter(e.target.value);
                  setPage(1);
                }}
                className="bg-transparent text-white outline-none cursor-pointer"
              >
                <option value="" className="bg-[#0f0f0f]">All Platforms</option>
                <option value="chatgpt" className="bg-[#0f0f0f]">ChatGPT</option>
                <option value="claude" className="bg-[#0f0f0f]">Claude</option>
                <option value="gemini" className="bg-[#0f0f0f]">Gemini</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 bg-[#0f0f0f] border border-[#262626] px-2.5 py-1.5 rounded-none text-xs text-[#8a8f9e]">
              <select
                value={sourceAgentFilter}
                onChange={(e) => {
                  searchRequest.current?.abort(); setSearchResults(submittedQuery ? [] : null); setConversations([]);
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

        {searchError && <div role="alert" className="p-4 text-rose-300">{searchError} <button onClick={() => setLocalRefresh(v => v + 1)} className="underline">Retry search</button></div>}
        {loadError && <div role="alert" className="p-4 text-rose-300">{loadError} <button onClick={() => void loadConversations()} className="underline">Retry</button></div>}
        {/* LOG ROWS */}
        {isSearching ? <div className="p-4">Searching...</div> : searchError || (searchResults === null && loadError) ? null : searchResults === null && listLoading ? <div className="p-4">Loading...</div> : (searchResults !== null ? searchResults : conversations).length === 0 ? (
          <div className="p-12 text-center text-[#8a8f9e] space-y-3">
            <MessageSquare className="w-8 h-8 mx-auto text-[#444444]" />
            <p className="text-white font-medium">No chat transcript logs found</p>
            <p className="text-xs max-w-md mx-auto">
              {searchResults !== null
                ? 'No conversation transcripts matched your search.'
                : 'Click "Import Chat History" above to ingest your Claude or ChatGPT export files directly into GigaMind.'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-[#202020]">
            {(searchResults !== null ? searchResults : conversations).map((conv) => (
              <div
                key={conv.id}
                onClick={() => { if (!busyRef.current) onOpenTranscript(conv); }}
                className="p-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 hover:bg-[#1c1c1c] cursor-pointer transition-colors group"
              >
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <div className="w-7 h-7 rounded-none bg-[#ff6b00]/10 border border-[#ff6b00]/30 text-[#ff6b00] flex items-center justify-center flex-shrink-0 mt-0.5">
                    <MessageSquare className="w-3.5 h-3.5" />
                  </div>

                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-white text-xs group-hover:text-[#ff6b00] transition-colors break-words">
                        {conv.title}
                      </span>
                      <span className="text-[10px] font-mono text-[#ff6b00] bg-[#ff6b00]/10 border border-[#ff6b00]/20 px-2 py-0.5 rounded-none flex-shrink-0 uppercase">
                        {conv.platform}
                      </span>
                      <AgentBadge agent={conv.source_agent} />
                      
                      {/* VECTORIZATION STATUS BADGE */}
                      {conv.is_vectorized ? (
                        <span className="inline-flex items-center gap-1 bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/30 px-2 py-0.2 text-[10px] font-mono font-semibold">
                          <Sparkles className="w-3 h-3" />
                          <span>Vectorized</span>
                        </span>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleVectorizeSingle(conv.id);
                          }}
                          className="inline-flex items-center gap-1 bg-amber-500/15 text-amber-400 hover:text-amber-300 border border-amber-500/30 px-2 py-0.2 text-[10px] font-mono font-semibold transition-colors"
                          title="Click to compute vector embedding with Gemini Embedding 2"
                        >
                          <Clock className="w-3 h-3" />
                          <span>Pending Vectorization</span>
                        </button>
                      )}

                      {resultsById.has(conv.id) && (
                        <span className="text-[10px] font-mono bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/30 px-1.5 py-0.2">
                          {resultsById.get(conv.id)?.retrieval_method === 'lexical+vector' ? 'fusion' : resultsById.get(conv.id)?.retrieval_method} · score {resultsById.get(conv.id)?.score.toFixed(2)}
                        </span>
                      )}
                    </div>

                    {resultsById.get(conv.id)?.evidence.map((item, index) => <p key={index} className="text-[#8a8f9e]">{item.role}: {item.text}</p>)}
                    <p className="text-[#8a8f9e] text-xs line-clamp-1 break-words font-sans">
                      {conv.summary}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2.5 flex-shrink-0">
                  <span className="text-[11px] font-mono text-[#8a8f9e]">
                    {conv.messages ? conv.messages.length : 0} messages
                  </span>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenTranscript(conv);
                    }}
                    className="bg-[#161616] border border-[#333333] hover:border-[#ff6b00]/40 text-[#ff6b00] hover:text-[#ff8800] px-3 py-1.5 rounded-none text-xs transition-colors flex items-center gap-1.5 font-medium flex-shrink-0"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>Inspect</span>
                  </button>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteConversation(conv.id, conv.title);
                    }}
                    className="p-1.5 bg-[#161616] border border-[#333333] hover:border-rose-500/40 text-[#8a8f9e] hover:text-rose-400 rounded-none transition-colors flex-shrink-0"
                    title="Delete Transcript from Database"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* PAGINATION FOOTER */}
        {searchResults === null && (
          <div className="p-4 border-t border-[#262626] bg-[#161616] flex justify-between items-center text-xs text-[#8a8f9e]">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="flex items-center gap-1 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed font-mono text-[11px]"
            >
              <ChevronLeft className="w-4 h-4" /> Previous
            </button>

            <span className="font-mono text-[11px]">Page {page} of {totalPages}</span>

            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="flex items-center gap-1 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed font-mono text-[11px]"
            >
              Next <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </fieldset>
  );
};
