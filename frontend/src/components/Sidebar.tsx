import React from 'react';
import {
  PixelBrain,
  PixelDatabase,
  PixelShield,
  PixelTerminal,
  PixelSparkles,
  PixelSettings
} from './ui/PixelIcons';
import { LayoutDashboard, ExternalLink, HardDrive } from 'lucide-react';
import { TabType } from './NavigationTabs';

interface SidebarProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  counts: {
    memories: number;
    files?: number;
    rules: number;
    transcripts: number;
  };
}

interface NavItemDef {
  id: TabType;
  label: string;
  icon: any;
  group: string;
  badge?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, counts }) => {
  const navItems: NavItemDef[] = [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard, group: 'OVERVIEW' },
    { id: 'memories', label: 'Memories', icon: PixelDatabase, group: 'KNOWLEDGE BASE', badge: counts.memories },
    { id: 'files', label: 'Files & Storage', icon: HardDrive, group: 'KNOWLEDGE BASE', badge: counts.files },
    { id: 'rules', label: 'Profile Rules', icon: PixelShield, group: 'KNOWLEDGE BASE', badge: counts.rules },
    { id: 'transcripts', label: 'Chat Transcripts', icon: PixelTerminal, group: 'MONITOR & LAB', badge: counts.transcripts },
    { id: 'vector-lab', label: 'Vector Search Lab', icon: PixelSparkles, group: 'MONITOR & LAB' },
    { id: 'settings', label: 'Settings & MCP Specs', icon: PixelSettings, group: 'SETTINGS & SPECS' },
  ];

  return (
    <aside className="w-60 bg-[#141414] border-r border-[#262626] flex flex-col justify-between h-screen sticky top-0 flex-shrink-0 text-xs font-sans select-none">
      <div>
        {/* BRANDING HEADER - EXACT h-14 ALIGNED WITH NAVBAR */}
        <div className="h-14 px-4 border-b border-[#262626] flex items-center justify-between bg-[#0f0f0f]">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-[#ff6b00] text-white rounded-none flex items-center justify-center font-semibold text-sm shadow-sm shadow-[#ff6b00]/20">
              <PixelBrain className="w-4 h-4 text-white" />
            </div>
            <div>
              <span className="font-semibold text-white text-xs tracking-tight block">GigaMind</span>
              <span className="text-[10px] text-[#8a8f9e] font-mono">Memory Engine</span>
            </div>
          </div>

          <span className="flex items-center gap-1 px-2 py-0.5 bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px] font-medium rounded-none">
            <span className="w-1.5 h-1.5 rounded-none bg-amber-400 animate-pulse" />
            Active
          </span>
        </div>

        {/* NAVIGATION CONTAINER WITH SMOOTH ACTIVE HIGHLIGHT */}
        <div className="px-3 py-4 space-y-6 overflow-y-auto max-h-[calc(100vh-140px)]">
          {/* OVERVIEW GROUP */}
          <div className="space-y-1">
            {navItems.filter(i => i.group === 'OVERVIEW').map(item => (
              <SidebarNavItem key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} />
            ))}
          </div>

          {/* KNOWLEDGE GROUP */}
          <div className="space-y-1">
            <div className="px-3 text-[10px] font-semibold text-[#8a8f9e] uppercase tracking-wider mb-1">
              KNOWLEDGE BASE
            </div>
            {navItems.filter(i => i.group === 'KNOWLEDGE BASE').map(item => (
              <SidebarNavItem key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} />
            ))}
          </div>

          {/* MONITOR GROUP */}
          <div className="space-y-1">
            <div className="px-3 text-[10px] font-semibold text-[#8a8f9e] uppercase tracking-wider mb-1">
              MONITOR & LAB
            </div>
            {navItems.filter(i => i.group === 'MONITOR & LAB').map(item => (
              <SidebarNavItem key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} />
            ))}
          </div>

          {/* MANAGE GROUP */}
          <div className="space-y-1">
            <div className="px-3 text-[10px] font-semibold text-[#8a8f9e] uppercase tracking-wider mb-1">
              SETTINGS & SPECS
            </div>
            {navItems.filter(i => i.group === 'SETTINGS & SPECS').map(item => (
              <SidebarNavItem key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} />
            ))}
          </div>
        </div>
      </div>

      {/* FOOTER */}
      <div className="p-4 border-t border-[#262626] flex items-center justify-between text-[#8a8f9e] text-xs">
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

const SidebarNavItem: React.FC<{
  item: NavItemDef;
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
}> = ({ item, activeTab, setActiveTab }) => {
  const Icon = item.icon;
  const isActive = activeTab === item.id;

  return (
    <button
      onClick={() => setActiveTab(item.id)}
      className={`w-full flex items-center justify-between px-3 py-2 rounded-none font-sans text-xs transition-all duration-150 relative overflow-hidden btn-press ${
        isActive
          ? 'bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white font-medium shadow-md shadow-[#ff6b00]/20'
          : 'text-[#c1c5d0] hover:text-white hover:bg-[#222222]'
      }`}
    >
      <div className="flex items-center gap-2.5 relative z-10">
        <Icon className={`w-4 h-4 transition-colors ${isActive ? 'text-white' : 'text-[#8a8f9e]'}`} />
        <span>{item.label}</span>
      </div>
      {item.badge !== undefined && (
        <span
          className={`px-1.5 py-0.2 text-[10px] font-mono rounded-none transition-colors relative z-10 ${
            isActive ? 'bg-white/20 text-white' : 'bg-[#262626] text-[#8a8f9e]'
          }`}
        >
          {item.badge}
        </span>
      )}
    </button>
  );
};
