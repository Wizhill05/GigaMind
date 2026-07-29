import React, { useState, useEffect, useRef } from 'react';
import { X, CornerDownLeft, Copy, Check } from 'lucide-react';
import { PixelBrain, PixelSparkles } from './ui/PixelIcons';
import { SearchResult } from '../types';
import { searchMemory } from '../api';
import { CategoryBadge, AgentBadge } from './ui/Badge';
import { useToast } from './ui/Toast';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({ isOpen, onClose }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isExiting, setIsExiting] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  // Listen for Cmd+K / Ctrl+K and ESC key globally
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (isOpen) {
          handleAnimatedClose();
        } else {
          setQuery('');
          setResults([]);
          setSelectedIndex(0);
        }
      } else if (e.key === 'Escape' && isOpen && !isExiting) {
        handleAnimatedClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isExiting]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Live vector search debounced on query change
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setIsSearching(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      const res = await searchMemory(query.trim(), undefined, undefined, 6);
      if (res) {
        setResults(res);
        setSelectedIndex(0);
      }
      setIsSearching(false);
    }, 150);

    return () => clearTimeout(timer);
  }, [query]);

  // Keyboard Arrow Navigation in List
  const handleInputKeyDown = (e: React.KeyboardEvent) => {
    if (results.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % results.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const selected = results[selectedIndex];
      if (selected) {
        handleCopy(selected);
      }
    }
  };

  const handleAnimatedClose = () => {
    setIsExiting(true);
    setTimeout(() => {
      setIsExiting(false);
      onClose();
    }, 180);
  };

  const handleCopy = (item: SearchResult) => {
    navigator.clipboard.writeText(item.content);
    setCopiedId(item.id);
    toast(`Copied memory to clipboard`, 'success');
    setTimeout(() => setCopiedId(null), 2000);
  };

  if (!isOpen) return null;

  return (
    <div
      onClick={handleAnimatedClose}
      className={`fixed inset-0 bg-[#0a0b0e]/85 backdrop-blur-md z-50 flex items-start justify-center pt-20 px-4 font-sans select-none transition-all duration-200 ${
        isExiting ? 'animate-fade-out' : 'animate-fade-in'
      }`}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={`bg-[#13151c] border border-[#1e2029] max-w-2xl w-full rounded-none shadow-2xl overflow-hidden text-xs ${
          isExiting ? 'animate-scale-out' : 'animate-scale-in'
        }`}
      >
        {/* INPUT HEADER WITH 8-BIT PIXEL BRAIN ICON */}
        <div className="p-4 border-b border-[#1e2029] flex items-center gap-3 bg-[#0a0b0e]">
          <PixelBrain className="w-5 h-5 text-[#ff6b00] flex-shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Type a command or query memory database..."
            className="w-full bg-transparent text-white font-sans text-xs outline-none placeholder-[#8a8f9e]"
          />
          {query && (
            <button onClick={() => setQuery('')} className="text-[#8a8f9e] hover:text-white">
              <X className="w-4 h-4" />
            </button>
          )}
          <span className="px-2 py-0.5 bg-[#181a24] border border-[#262936] text-[10px] font-mono text-[#8a8f9e] rounded-none">
            ESC
          </span>
        </div>

        {/* RESULTS LIST BODY */}
        <div className="max-h-96 overflow-y-auto p-2 space-y-1">
          {!query.trim() ? (
            <div className="p-8 text-center text-[#8a8f9e] space-y-2">
              <PixelSparkles className="w-6 h-6 text-[#ff6b00] mx-auto opacity-70" />
              <p>Type anything to run instant semantic vector search across all memories</p>
              <div className="flex justify-center items-center gap-2 text-[11px] font-mono text-[#8a8f9e]">
                <span>Use ↑ ↓ to navigate</span>
                <span>•</span>
                <span>Enter to copy</span>
              </div>
            </div>
          ) : isSearching ? (
            <div className="p-8 text-center text-[#8a8f9e]">
              Searching vector database...
            </div>
          ) : results.length === 0 ? (
            <div className="p-8 text-center text-[#8a8f9e]">
              No semantic memory records found matching query
            </div>
          ) : (
            results.map((res, idx) => {
              const isSelected = selectedIndex === idx;
              return (
                <div
                  key={res.id || idx}
                  onClick={() => handleCopy(res)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`p-3 rounded-none flex items-center justify-between gap-3 cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-gradient-to-r from-[#ff6b00]/20 to-[#f59e0b]/20 border border-[#ff6b00]/40 text-white'
                      : 'bg-[#0a0b0e] border border-[#1e2029] text-[#c1c5d0] hover:border-[#262936]'
                  }`}
                >
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <CategoryBadge category={res.category} />
                      <AgentBadge agent={res.source_agent} />
                    </div>
                    <p className="text-white text-xs leading-relaxed">{res.content}</p>
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-[#ff6b00] font-semibold text-[11px]">
                      {(res.score * 100).toFixed(0)}% match
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopy(res);
                      }}
                      className="p-1.5 bg-[#101216] border border-[#262936] hover:border-[#ff6b00] text-[#8a8f9e] hover:text-white rounded-none transition-colors"
                      title="Copy memory"
                    >
                      {copiedId === res.id ? <Check className="w-3.5 h-3.5 text-amber-400" /> : <CornerDownLeft className="w-3.5 h-3.5 text-[#ff6b00]" />}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* FOOTER */}
        <div className="px-4 py-2 border-t border-[#1e2029] bg-[#0a0b0e] flex justify-between items-center text-[11px] text-[#8a8f9e]">
          <span>GigaMind Spotlight Quick Search</span>
          <div className="flex items-center gap-3">
            <span>↑↓ Navigate</span>
            <span>↵ Select/Copy</span>
            <span>esc Exit</span>
          </div>
        </div>
      </div>
    </div>
  );
};
