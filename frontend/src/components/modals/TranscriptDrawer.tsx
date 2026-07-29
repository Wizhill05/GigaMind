import React, { useState } from 'react';
import { X, Copy, Check, User, Bot, Terminal } from 'lucide-react';
import { Conversation } from '../../types';
import { AgentBadge } from '../ui/Badge';

interface TranscriptDrawerProps {
  conversation: Conversation | null;
  onClose: () => void;
}

export const TranscriptDrawer: React.FC<TranscriptDrawerProps> = ({ conversation, onClose }) => {
  const [copied, setCopied] = useState(false);

  if (!conversation) return null;

  const handleCopyTranscript = () => {
    const text = conversation.messages
      ? conversation.messages.map((m) => `[${m.role.toUpperCase()}]\n${m.content}`).join('\n\n---\n\n')
      : conversation.summary;

    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 bg-[#0a0b0e]/80 backdrop-blur-xs z-50 flex justify-end font-sans select-none">
      <div className="bg-[#13151c] border-l border-[#1e2029] w-full max-w-2xl h-full flex flex-col shadow-2xl">
        {/* DRAWER HEADER (Matching Render Image 2 Log Header) */}
        <div className="p-6 border-b border-[#1e2029] bg-[#0f1015] flex justify-between items-start gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-md font-medium">
                {conversation.platform}
              </span>
              <AgentBadge agent={conversation.source_agent} />
              <span className="text-xs text-[#8a8f9e] font-mono">id: {conversation.id}</span>
            </div>

            <h2 className="text-base font-bold text-white tracking-tight">{conversation.title}</h2>
            <p className="text-xs text-[#8a8f9e] leading-relaxed">{conversation.summary}</p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCopyTranscript}
              className="p-2 bg-[#101216] border border-[#262936] hover:border-[#3f4357] text-[#8a8f9e] hover:text-white rounded-md transition-colors"
              title="Copy Full Transcript"
            >
              {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
            </button>
            <button
              onClick={onClose}
              className="p-2 bg-[#101216] border border-[#262936] hover:border-rose-500/40 text-rose-400 hover:text-rose-300 rounded-md transition-colors"
              title="Close Drawer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* MESSAGES LIST BODY (Matching Image 2 Log View) */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4 text-xs">
          {!conversation.messages || conversation.messages.length === 0 ? (
            <div className="p-12 text-center text-[#8a8f9e]">
              No message payload attached to this transcript log record
            </div>
          ) : (
            conversation.messages.map((msg, idx) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={idx}
                  className={`p-4 rounded-lg border ${
                    isUser
                      ? 'bg-[#0a0b0e] border-[#1e2029] text-white'
                      : 'bg-[#101216] border-[#262936] text-[#c1c5d0]'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2 text-[11px] font-medium text-[#8a8f9e]">
                    {isUser ? <User className="w-3.5 h-3.5 text-[#a855f7]" /> : <Bot className="w-3.5 h-3.5 text-emerald-400" />}
                    <span className="capitalize">{msg.role}</span>
                  </div>
                  <div className="whitespace-pre-wrap leading-relaxed font-sans text-xs">{msg.content}</div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
