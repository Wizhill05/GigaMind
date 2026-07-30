import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { PixelShield } from '../ui/PixelIcons';

interface RuleModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (data: { key: string; value: string; category: string; source_agent: string }) => void;
}

export const RuleModal: React.FC<RuleModalProps> = ({ isOpen, onClose, onSave }) => {
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');
  const [category, setCategory] = useState('general');
  const [sourceAgent, setSourceAgent] = useState('user');
  const [isExiting, setIsExiting] = useState(false);

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
    if (!key.trim() || !value.trim()) return;

    onSave({
      key: key.trim().toLowerCase().replace(/\s+/g, '_'),
      value: value.trim(),
      category: category.trim() || 'general',
      source_agent: sourceAgent.trim() || 'user',
    });
    setKey('');
    setValue('');
    setCategory('general');
    setSourceAgent('user');
    handleAnimatedClose();
  };

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
            <PixelShield className="w-4 h-4 text-[#ff6b00]" />
            <span>Define Identity & Profile Rule</span>
          </h3>
          <button onClick={handleAnimatedClose} className="text-[#8a8f9e] hover:text-white transition-colors btn-press">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          <div>
            <label className="block text-xs font-medium text-[#c1c5d0] mb-1">
              Rule Key (Unique Identifier)
            </label>
            <input
              type="text"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="e.g. primary_programming_language"
              required
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 text-white outline-none rounded-none transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#c1c5d0] mb-1">
              Rule Value / Statement
            </label>
            <input
              type="text"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="e.g. Python / TypeScript with strict typing"
              required
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 text-white outline-none rounded-none transition-colors"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#c1c5d0] mb-1">Category</label>
              <input
                type="text"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="general, coding, bio"
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 text-white outline-none rounded-none transition-colors"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#c1c5d0] mb-1">Source Agent</label>
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
              Save Rule
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
