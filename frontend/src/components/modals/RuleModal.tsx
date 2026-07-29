import React, { useState } from 'react';
import { X, ShieldPlus } from 'lucide-react';

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
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-[#0a0b0e]/80 backdrop-blur-xs flex items-center justify-center p-4 z-50 font-sans select-none">
      <div className="bg-[#13151c] border border-[#1e2029] max-w-xl w-full p-6 rounded-xl shadow-2xl space-y-4">
        <div className="flex justify-between items-center border-b border-[#1e2029] pb-3">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <ShieldPlus className="w-4 h-4 text-[#a855f7]" />
            <span>Define Identity & Profile Rule</span>
          </h3>
          <button onClick={onClose} className="text-[#8a8f9e] hover:text-white transition-colors">
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
              className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#5b0e89] p-2.5 text-white outline-none rounded-md"
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
              className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#5b0e89] p-2.5 text-white outline-none rounded-md"
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
                className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#5b0e89] p-2.5 text-white outline-none rounded-md"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#c1c5d0] mb-1">Source Agent</label>
              <select
                value={sourceAgent}
                onChange={(e) => setSourceAgent(e.target.value)}
                className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#5b0e89] p-2.5 text-white outline-none rounded-md cursor-pointer"
              >
                <option value="user" className="bg-[#0a0b0e]">User</option>
                <option value="claude" className="bg-[#0a0b0e]">Claude</option>
                <option value="gpt" className="bg-[#0a0b0e]">GPT / OpenAI</option>
                <option value="gemini" className="bg-[#0a0b0e]">Gemini</option>
                <option value="system" className="bg-[#0a0b0e]">System</option>
              </select>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1e2029]">
            <button
              type="button"
              onClick={onClose}
              className="bg-[#181a24] text-[#8a8f9e] hover:text-white px-4 py-2 rounded-md font-medium"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="bg-[#5b0e89] hover:bg-[#6d10a3] text-white font-medium px-5 py-2 rounded-md shadow-sm"
            >
              Save Rule
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
