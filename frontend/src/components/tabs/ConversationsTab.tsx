import React, { useState, useEffect } from 'react';
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
  Terminal,
  FolderInput,
  Search,
  Sparkles
} from 'lucide-react';
import { PixelTerminal } from '../ui/PixelIcons';
import { Conversation } from '../../types';
import { fetchConversations, importConversationsFile, importConversationsPath, searchConversations } from '../../api';
import { AgentBadge } from '../ui/Badge';
import { useToast } from '../ui/Toast';

interface ConversationsTabProps {
  onOpenTranscript: (conv: Conversation) => void;
}

export const ConversationsTab: React.FC<ConversationsTabProps> = ({ onOpenTranscript }) => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [platformFilter, setPlatformFilter] = useState('');
  const [sourceAgentFilter, setSourceAgentFilter] = useState('');

  // Semantic Vector Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<any[] | null>(null);

  // Import Chat History State
  const [showImportCard, setShowImportCard] = useState(false);
  const [localPathInput, setLocalPathInput] = useState('C:\\Users\\Aryan\\Downloads\\conversations-000\\conversations.json');
  const [importPlatform, setImportPlatform] = useState('');
  const [isImporting, setIsImporting] = useState(false);
  const [importStatus, setImportStatus] = useState<string | null>(null);

  const { toast } = useToast();

  const loadConversations = async () => {
    const res = await fetchConversations(page, 10, platformFilter || undefined, sourceAgentFilter || undefined);
    if (res) {
      setConversations(res.conversations);
      setTotalPages(res.pages || 1);
      setTotalCount(res.total || 0);
    }
  };

  useEffect(() => {
    if (searchResults === null) {
      loadConversations();
    }
  }, [page, platformFilter, sourceAgentFilter, searchResults]);

  // Handle semantic transcript search
  const handleTranscriptSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setIsSearching(true);
    const res = await searchConversations(searchQuery.trim(), platformFilter || undefined, sourceAgentFilter || undefined, 10);
    setSearchResults(res || []);
    setIsSearching(false);
  };

  // Handle local path import
  const handleImportFromPath = async () => {
    if (!localPathInput.trim()) {
      toast('Please enter a valid file path', 'error');
      return;
    }

    setIsImporting(true);
    setImportStatus('Reading and ingesting conversations from local path...');
    toast('Starting chat transcript import...', 'info');

    const res = await importConversationsPath(localPathInput.trim(), importPlatform || undefined);
    setIsImporting(false);

    if (res && res.success) {
      toast(res.message, 'success');
      setImportStatus(res.message);
      loadConversations();
      setTimeout(() => {
        setShowImportCard(false);
        setImportStatus(null);
      }, 3000);
    } else {
      toast('Failed to import conversations. Verify the file path.', 'error');
      setImportStatus('Error: Failed to import from specified path.');
    }
  };

  // Handle file upload import
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsImporting(true);
    setImportStatus(`Uploading and parsing ${file.name}...`);
    toast(`Uploading ${file.name}...`, 'info');

    const res = await importConversationsFile(file, importPlatform || undefined);
    setIsImporting(false);
    e.target.value = '';

    if (res && res.success) {
      toast(res.message, 'success');
      setImportStatus(res.message);
      loadConversations();
      setTimeout(() => {
        setShowImportCard(false);
        setImportStatus(null);
      }, 3000);
    } else {
      toast(`Failed to import ${file.name}. Check format.`, 'error');
      setImportStatus(`Error: Failed to import ${file.name}.`);
    }
  };

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER & TOP CONTROLS */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-[#141414] border border-[#262626] p-5 rounded-none">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-[#ff6b00]/10 border border-[#ff6b00]/30 flex items-center justify-center text-[#ff6b00]">
              <MessageSquare className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white tracking-tight">Chat Logs & Transcripts</h2>
              <p className="text-xs text-[#8a8f9e]">
                Imported conversation history from Claude, ChatGPT, and AI agent sessions ({totalCount} total)
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => { setSearchResults(null); setSearchQuery(''); loadConversations(); }}
            className="px-3 py-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-[#c1c5d0] hover:text-white border border-[#333333] transition-colors flex items-center gap-1.5 font-mono text-[11px]"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>

          <button
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
              onClick={() => setShowImportCard(false)}
              className="text-[#8a8f9e] hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* METHOD A: DIRECT LOCAL PATH INGESTION */}
            <div className="bg-[#0f0f0f] border border-[#262626] p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Terminal className="w-3.5 h-3.5 text-[#ff6b00]" />
                <span className="font-semibold text-white text-xs">Option 1: Ingest from Local File Path</span>
              </div>
              <p className="text-[11px] text-[#8a8f9e]">
                Directly reads <code>conversations.json</code> from disk for instant zero-network batch ingestion:
              </p>

              <div className="space-y-2">
                <input
                  type="text"
                  value={localPathInput}
                  onChange={(e) => setLocalPathInput(e.target.value)}
                  placeholder="C:\Users\...\conversations.json"
                  className="w-full bg-[#161616] border border-[#333333] focus:border-[#ff6b00] p-2 text-white font-mono text-[11px] outline-none"
                />

                <div className="flex items-center justify-between gap-2">
                  <select
                    value={importPlatform}
                    onChange={(e) => setImportPlatform(e.target.value)}
                    className="bg-[#161616] border border-[#333333] text-white p-1.5 text-xs outline-none"
                  >
                    <option value="">Auto-Detect Format (Claude/GPT)</option>
                    <option value="claude">Claude Export</option>
                    <option value="chatgpt">ChatGPT Export</option>
                  </select>

                  <button
                    onClick={handleImportFromPath}
                    disabled={isImporting}
                    className="px-4 py-1.5 bg-[#ff6b00] hover:bg-[#e05e00] text-white font-medium transition-colors flex items-center gap-1.5 text-xs disabled:opacity-50"
                  >
                    {isImporting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                    <span>{isImporting ? 'Ingesting...' : 'Import from Path'}</span>
                  </button>
                </div>
              </div>
            </div>

            {/* METHOD B: BROWSER FILE UPLOAD */}
            <div className="bg-[#0f0f0f] border border-[#262626] p-4 flex flex-col justify-between space-y-3">
              <div>
                <div className="flex items-center gap-2">
                  <FileJson className="w-3.5 h-3.5 text-[#22c55e]" />
                  <span className="font-semibold text-white text-xs">Option 2: Upload JSON Export</span>
                </div>
                <p className="text-[11px] text-[#8a8f9e] mt-1">
                  Select and upload an exported <code>conversations.json</code> or zip file from Claude/ChatGPT settings:
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
                  disabled={isImporting}
                />
              </label>
            </div>
          </div>

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

      {/* SEMANTIC TRANSCRIPTS VECTOR SEARCH BAR */}
      <div className="bg-[#141414] border border-[#262626] p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-white font-mono text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5 text-[#ff6b00]" />
            <span>Semantic Transcript Vector Search</span>
          </div>
        </div>

        <form onSubmit={handleTranscriptSearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-[#8a8f9e] absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search concepts across all conversation sessions (e.g. 'Laptop for Blender', 'Body temperature recovery', 'FastAPI OAuth')..."
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
              onClick={() => { setSearchResults(null); setSearchQuery(''); }}
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
              {searchResults !== null ? `${searchResults.length} matching search result(s)` : `${totalCount} total`}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 bg-[#0f0f0f] border border-[#262626] px-2.5 py-1.5 rounded-none text-xs text-[#8a8f9e]">
              <Filter className="w-3.5 h-3.5" />
              <select
                value={platformFilter}
                onChange={(e) => {
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

        {/* LOG ROWS */}
        {(searchResults !== null ? searchResults : conversations).length === 0 ? (
          <div className="p-12 text-center text-[#8a8f9e] space-y-3">
            <MessageSquare className="w-8 h-8 mx-auto text-[#444444]" />
            <p className="text-white font-medium">No chat transcript logs found</p>
            <p className="text-xs max-w-md mx-auto">
              {searchResults !== null
                ? 'No conversation transcripts matched your vector search query.'
                : 'Click "Import Chat History" above to ingest your Claude or ChatGPT export files directly into GigaMind.'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-[#202020]">
            {(searchResults !== null ? searchResults : conversations).map((conv) => (
              <div
                key={conv.id}
                onClick={() => onOpenTranscript(conv)}
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
                      {conv.score !== undefined && (
                        <span className="text-[10px] font-mono bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/30 px-1.5 py-0.2">
                          {(conv.score * 100).toFixed(1)}% match
                        </span>
                      )}
                    </div>

                    <p className="text-[#8a8f9e] text-xs line-clamp-1 break-words font-sans">
                      {conv.summary}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="text-[11px] font-mono text-[#8a8f9e]">
                    {conv.messages ? conv.messages.length : (conv.messages_count || 0)} messages
                  </span>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenTranscript(conv);
                    }}
                    className="bg-[#161616] border border-[#333333] hover:border-[#ff6b00]/40 text-[#ff6b00] hover:text-[#ff8800] px-3 py-1.5 rounded-none text-xs transition-colors flex items-center gap-1.5 font-medium flex-shrink-0"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>Inspect Log</span>
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
    </div>
  );
};
