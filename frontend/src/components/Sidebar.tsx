import React from 'react';
import {
  LayoutDashboard,
  Database,
  Shield,
  Settings,
  Terminal,
  Sparkles,
  ExternalLink,
  Brain
} from 'lucide-react';
import { TabType } from './NavigationTabs';

interface SidebarProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  counts: {
    memories: number;
    rules: number;
    transcripts: number;
  };
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, counts }) => {
  return (
    <aside className="w-60 bg-[#0f1015] border-r border-[#1e2029] flex flex-col justify-between h-screen sticky top-0 flex-shrink-0 text-xs font-sans select-none">
      <div>
        {/* BRANDING HEADER */}
        <div className="p-4 border-b border-[#1e2029] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-[#5b0e89] text-white rounded-md flex items-center justify-center font-bold text-sm shadow-sm">
              <Brain className="w-4 h-4 text-white" />
            </div>
            <div>
              <span className="font-bold text-white text-sm tracking-tight block">GigaMind</span>
              <span className="text-[10px] text-[#8a8f9e] font-mono">Memory Engine</span>
            </div>
          </div>

          <span className="flex items-center gap-1 px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-medium rounded-md">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Active
          </span>
        </div>

        {/* NAVIGATION SECTIONS */}
        <div className="px-3 py-4 space-y-6 overflow-y-auto max-h-[calc(100vh-140px)]">
          {/* OVERVIEW GROUP */}
          <div className="space-y-1">
            <SidebarItem
              id="overview"
              label="Overview"
              icon={LayoutDashboard}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
            />
          </div>

          {/* KNOWLEDGE GROUP */}
          <div className="space-y-1">
            <div className="px-3 text-[10px] font-semibold text-[#8a8f9e] uppercase tracking-wider mb-1">
              KNOWLEDGE BASE
            </div>
            <SidebarItem
              id="memories"
              label="Memories"
              icon={Database}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              badge={counts.memories}
            />
            <SidebarItem
              id="rules"
              label="Profile Rules"
              icon={Shield}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              badge={counts.rules}
            />
          </div>

          {/* MONITOR GROUP */}
          <div className="space-y-1">
            <div className="px-3 text-[10px] font-semibold text-[#8a8f9e] uppercase tracking-wider mb-1">
              MONITOR & LAB
            </div>
            <SidebarItem
              id="transcripts"
              label="Chat Transcripts"
              icon={Terminal}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              badge={counts.transcripts}
            />
            <SidebarItem
              id="vector-lab"
              label="Vector Search Lab"
              icon={Sparkles}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
            />
          </div>

          {/* MANAGE GROUP */}
          <div className="space-y-1">
            <div className="px-3 text-[10px] font-semibold text-[#8a8f9e] uppercase tracking-wider mb-1">
              SETTINGS & SPECS
            </div>
            <SidebarItem
              id="settings"
              label="Settings & MCP Specs"
              icon={Settings}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
            />
          </div>
        </div>
      </div>

      {/* FOOTER */}
      <div className="p-4 border-t border-[#1e2029] flex items-center justify-between text-[#8a8f9e] text-xs">
        <a
          href="https://github.com/Wizhill05/GigaMind"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 hover:text-white transition-colors"
        >
          <span>GitHub</span>
          <ExternalLink className="w-3 h-3" />
        </a>
        <span className="text-[11px] font-mono text-[#8a8f9e]">v2.0.0</span>
      </div>
    </aside>
  );
};

const SidebarItem: React.FC<{
  id: TabType;
  label: string;
  icon: any;
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  badge?: number;
}> = ({ id, label, icon: Icon, activeTab, setActiveTab, badge }) => {
  const isActive = activeTab === id;

  return (
    <button
      onClick={() => setActiveTab(id)}
      className={`w-full flex items-center justify-between px-3 py-2 rounded-md font-sans text-xs transition-colors ${
        isActive
          ? 'bg-[#5b0e89] text-white font-medium shadow-sm'
          : 'text-[#c1c5d0] hover:text-white hover:bg-[#181a24]'
      }`}
    >
      <div className="flex items-center gap-2.5">
        <Icon className={`w-4 h-4 ${isActive ? 'text-white' : 'text-[#8a8f9e]'}`} />
        <span>{label}</span>
      </div>
      {badge !== undefined && (
        <span
          className={`px-1.5 py-0.2 text-[10px] font-mono rounded-full ${
            isActive ? 'bg-white/20 text-white' : 'bg-[#1e2029] text-[#8a8f9e]'
          }`}
        >
          {badge}
        </span>
      )}
    </button>
  );
};
