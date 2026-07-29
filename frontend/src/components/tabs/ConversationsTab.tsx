import React, { useState, useEffect } from 'react';
import { Terminal, Filter, Eye, ChevronLeft, ChevronRight, MessageSquare } from 'lucide-react';
import { Conversation } from '../../types';
import { fetchConversations } from '../../api';
import { AgentBadge } from '../ui/Badge';

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

  const loadConversations = async () => {
    const res = await fetchConversations(page, 10, platformFilter || undefined, sourceAgentFilter || undefined);
    if (res) {
      setConversations(res.conversations);
      setTotalPages(res.pages || 1);
      setTotalCount(res.total || 0);
    }
  };

  useEffect(() => {
    loadConversations();
  }, [page, platformFilter, sourceAgentFilter]);

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER & TOP CONTROLS */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">Chat Logs & Transcripts</h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Imported conversation sessions and chat history exports ({totalCount} total)
          </p>
        </div>
      </div>

      {/* RENDER SERVICE STACK CARD (Matching Image 2 Log View Header) */}
      <div className="bg-[#13151c] border border-[#1e2029] rounded-lg overflow-hidden space-y-0">
        {/* LOG FILTER HEADER (Matching Image 2) */}
        <div className="p-4 border-b border-[#1e2029] bg-[#101216] flex flex-col md:flex-row justify-between items-stretch md:items-center gap-3">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-emerald-400" />
            <span className="font-semibold text-white">Application Transcript Logs</span>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 bg-[#0a0b0e] border border-[#1e2029] px-2.5 py-1.5 rounded-md text-xs text-[#8a8f9e]">
              <Filter className="w-3.5 h-3.5" />
              <select
                value={platformFilter}
                onChange={(e) => {
                  setPlatformFilter(e.target.value);
                  setPage(1);
                }}
                className="bg-transparent text-white outline-none cursor-pointer"
              >
                <option value="" className="bg-[#0a0b0e]">All Platforms</option>
                <option value="chatgpt" className="bg-[#0a0b0e]">ChatGPT</option>
                <option value="claude" className="bg-[#0a0b0e]">Claude</option>
                <option value="gemini" className="bg-[#0a0b0e]">Gemini</option>
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
              </select>
            </div>
          </div>
        </div>

        {/* LOG ROWS */}
        {conversations.length === 0 ? (
          <div className="p-12 text-center text-[#8a8f9e]">
            No chat transcript logs stored matching filter criteria
          </div>
        ) : (
          <div className="divide-y divide-[#1e2029]">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => onOpenTranscript(conv)}
                className="p-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 hover:bg-[#181a24] cursor-pointer transition-colors group"
              >
                <div className="flex items-start gap-3 flex-1">
                  <div className="w-7 h-7 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <MessageSquare className="w-3.5 h-3.5" />
                  </div>

                  <div className="space-y-1.5 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-white text-xs group-hover:text-emerald-400 transition-colors">
                        {conv.title}
                      </span>
                      <span className="text-[11px] font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-md">
                        {conv.platform}
                      </span>
                      <AgentBadge agent={conv.source_agent} />
                    </div>

                    <p className="text-[#8a8f9e] text-xs line-clamp-1">
                      {conv.summary}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span className="text-[11px] font-mono text-[#8a8f9e]">
                    {conv.messages ? conv.messages.length : 0} messages
                  </span>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenTranscript(conv);
                    }}
                    className="bg-[#101216] border border-[#262936] hover:border-emerald-500/40 text-emerald-400 hover:text-emerald-300 px-3 py-1.5 rounded-md text-xs transition-colors flex items-center gap-1.5 font-medium"
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
