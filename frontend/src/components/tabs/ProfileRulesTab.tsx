import React, { useState, useEffect } from 'react';
import { Plus, Filter, Search, Trash2 } from 'lucide-react';
import { PixelShield } from '../ui/PixelIcons';
import { ProfileRule } from '../../types';
import { fetchProfileRules, deleteProfileRule } from '../../api';
import { AgentBadge, CategoryBadge } from '../ui/Badge';
import { useToast } from '../ui/Toast';

interface ProfileRulesTabProps {
  onOpenNewRuleModal: () => void;
}

export const ProfileRulesTab: React.FC<ProfileRulesTabProps> = ({ onOpenNewRuleModal }) => {
  const [rules, setRules] = useState<ProfileRule[]>([]);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [sourceAgentFilter, setSourceAgentFilter] = useState('');
  const [searchFilter, setSearchFilter] = useState('');

  const { toast } = useToast();

  const loadRules = async () => {
    const res = await fetchProfileRules(categoryFilter || undefined, sourceAgentFilter || undefined);
    if (res) {
      setRules(res);
    }
  };

  useEffect(() => {
    loadRules();
  }, [categoryFilter, sourceAgentFilter]);

  const handleDelete = async (id: string) => {
    if (window.confirm(`Confirm deletion of profile rule: ${id}?`)) {
      const ok = await deleteProfileRule(id);
      if (ok) {
        toast(`Profile rule deleted`, 'success');
        loadRules();
      }
    }
  };

  const filteredRules = rules.filter((rule) => {
    if (!searchFilter.trim()) return true;
    return (
      rule.key.toLowerCase().includes(searchFilter.toLowerCase()) ||
      rule.value.toLowerCase().includes(searchFilter.toLowerCase()) ||
      rule.category.toLowerCase().includes(searchFilter.toLowerCase())
    );
  });

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER & TOP CONTROLS */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white tracking-tight">Identity & Profile Rules</h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Permanent bio statements, tech preferences, and core behavioral directives ({rules.length} total)
          </p>
        </div>

        <button
          onClick={onOpenNewRuleModal}
          className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium px-4 py-2 rounded-none flex items-center gap-2 transition-all shadow-sm btn-press"
        >
          <Plus className="w-4 h-4" />
          <span>Add Rule</span>
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
              placeholder="Search rule keys or values..."
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] pl-9 pr-3 py-1.5 text-xs text-white placeholder-[#8a8f9e] outline-none rounded-none font-sans"
            />
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 bg-[#0f0f0f] border border-[#262626] px-2.5 py-1.5 rounded-none text-xs text-[#8a8f9e]">
              <Filter className="w-3.5 h-3.5" />
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="bg-transparent text-white outline-none cursor-pointer"
              >
                <option value="" className="bg-[#0f0f0f]">All Categories</option>
                <option value="general" className="bg-[#0f0f0f]">general</option>
                <option value="coding" className="bg-[#0f0f0f]">coding</option>
                <option value="bio" className="bg-[#0f0f0f]">bio</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 bg-[#0f0f0f] border border-[#262626] px-2.5 py-1.5 rounded-none text-xs text-[#8a8f9e]">
              <select
                value={sourceAgentFilter}
                onChange={(e) => setSourceAgentFilter(e.target.value)}
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

        {/* ROWS STACK */}
        {filteredRules.length === 0 ? (
          <div className="p-12 text-center text-[#8a8f9e]">
            No profile rules match search criteria
          </div>
        ) : (
          <div className="divide-y divide-[#262626]">
            {filteredRules.map((rule) => (
              <div
                key={rule.id}
                className="p-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 hover:bg-[#222222] transition-colors group"
              >
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <div className="w-7 h-7 rounded-none bg-[#ff6b00]/10 border border-[#ff6b00]/30 text-[#ff6b00] flex items-center justify-center flex-shrink-0 mt-0.5">
                    <PixelShield className="w-3.5 h-3.5 text-[#ff6b00]" />
                  </div>

                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-white text-xs break-words break-all">
                        {rule.key}
                      </span>
                      <span className="text-[#8a8f9e]">=</span>
                      <span className="text-[#c1c5d0] font-normal break-words break-all">{rule.value}</span>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-[#8a8f9e] text-xs">
                      <CategoryBadge category={rule.category} />
                      <AgentBadge agent={rule.source_agent} />
                      <span className="font-mono text-[11px] truncate">id: {rule.id}</span>
                      {rule.updated_at && (
                        <span>Updated: {new Date(rule.updated_at).toLocaleDateString()}</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* ROW ACTION */}
                <button
                  onClick={() => handleDelete(rule.id)}
                  className="bg-[#161616] border border-[#333333] hover:border-rose-500/40 text-rose-400 hover:text-rose-300 px-3 py-1.5 rounded-none text-xs transition-colors flex items-center gap-1.5 flex-shrink-0 opacity-90 group-hover:opacity-100 btn-press"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>Delete</span>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
