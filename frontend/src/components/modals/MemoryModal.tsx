import React, { useState, useEffect } from 'react';
import { X, Save, Plus } from 'lucide-react';
import { Memory } from '../../types';

interface MemoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (data: { content: string; category: string; source_agent: string; tags: string[] }) => void;
  initialMemory?: Memory | null;
}

export const MemoryModal: React.FC<MemoryModalProps> = ({
  isOpen,
  onClose,
  onSave,
  initialMemory,
}) => {
  const [content, setContent] = useState('');
  const [category, setCategory] = useState('general');
  const [sourceAgent, setSourceAgent] = useState('user');
  const [tagsInput, setTagsInput] = useState('');
  const [isExiting, setIsExiting] = useState(false);

  useEffect(() => {
    if (initialMemory) {
      setContent(initialMemory.content || '');
      setCategory(initialMemory.category || 'general');
      setSourceAgent(initialMemory.source_agent || 'user');
      setTagsInput(initialMemory.tags ? initialMemory.tags.join(', ') : '');
    } else {
      setContent('');
      setCategory('general');
      setSourceAgent('user');
      setTagsInput('');
    }
  }, [initialMemory, isOpen]);

  // Handle ESC key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen && !isExiting) {
        handleAnimatedClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isExiting]);

  const handleAnimatedClose = () => {
    setIsExiting(true);
    setTimeout(() => {
      setIsExiting(false);
      onClose();
    }, 180);
  };

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) return;

    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);

    onSave({
      content: content.trim(),
      category: category.trim() || 'general',
      source_agent: sourceAgent.trim() || 'user',
      tags,
    });
    handleAnimatedClose();
  };

  const isEdit = !!initialMemory;

  return (
    <div
      onClick={handleAnimatedClose}
      className={`fixed inset-0 bg-[#0f0f0f]/85 backdrop-blur-md z-50 flex items-center justify-center p-4 font-sans select-none transition-all duration-200 ${
        isExiting ? 'animate-fade-out' : 'animate-fade-in'
      }`}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={`bg-[#181818] border border-[#262626] max-w-xl w-full p-6 rounded-none shadow-2xl space-y-4 ${
          isExiting ? 'animate-scale-out' : 'animate-scale-in'
        }`}
      >
        <div className="flex justify-between items-center border-b border-[#262626] pb-3">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            {isEdit ? <Save className="w-4 h-4 text-[#ff6b00]" /> : <Plus className="w-4 h-4 text-[#ff6b00]" />}
            <span>{isEdit ? `Edit Memory Record (${initialMemory.id})` : 'Create New Memory Record'}</span>
          </h3>
          <button
            onClick={handleAnimatedClose}
            className="text-[#8a8f9e] hover:text-white transition-colors btn-press"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          <div>
            <label className="block text-xs font-medium text-[#c1c5d0] mb-1">
              Memory Statement / Fact Content
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              required
              placeholder="Enter memory statement or factual context..."
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-3 text-white outline-none rounded-none text-xs font-sans transition-colors"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#c1c5d0] mb-1">Category</label>
              <input
                type="text"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g. general, coding, personal"
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 text-white outline-none rounded-none transition-colors"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#c1c5d0] mb-1">Source Agent / Origin</label>
              <select
                value={sourceAgent}
                onChange={(e) => setSourceAgent(e.target.value)}
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 text-white outline-none rounded-none cursor-pointer transition-colors"
              >
                <option value="user" className="bg-[#0f0f0f]">User</option>
                <option value="claude" className="bg-[#0f0f0f]">Claude</option>
                <option value="gpt" className="bg-[#0f0f0f]">GPT / OpenAI</option>
                <option value="gemini" className="bg-[#0f0f0f]">Gemini</option>
                <option value="system" className="bg-[#0f0f0f]">System</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#c1c5d0] mb-1">
              Tags (Comma Separated)
            </label>
            <input
              type="text"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="python, api, config, preferences"
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 text-white outline-none rounded-none transition-colors"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#262626]">
            <button
              type="button"
              onClick={handleAnimatedClose}
              className="bg-[#222222] text-[#8a8f9e] hover:text-white px-4 py-2 rounded-none font-medium btn-press"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium px-5 py-2 rounded-none shadow-sm btn-press"
            >
              Save Memory
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
