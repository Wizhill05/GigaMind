import React, { useRef, useEffect, useState } from 'react';
import {
  PixelBrain,
  PixelDatabase,
  PixelShield,
  PixelTerminal,
  PixelSparkles,
  PixelSettings
} from './ui/PixelIcons';
import { LayoutDashboard, ExternalLink } from 'lucide-react';
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

interface NavItemDef {
  id: TabType;
  label: string;
  icon: any;
  group: string;
  badge?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, counts }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [sliderStyle, setSliderStyle] = useState<{ top: number; height: number; opacity: number }>({
    top: 0,
    height: 0,
    opacity: 0,
  });

  const navItems: NavItemDef[] = [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard, group: 'OVERVIEW' },
    { id: 'memories', label: 'Memories', icon: PixelDatabase, group: 'KNOWLEDGE BASE', badge: counts.memories },
    { id: 'rules', label: 'Profile Rules', icon: PixelShield, group: 'KNOWLEDGE BASE', badge: counts.rules },
    { id: 'transcripts', label: 'Chat Transcripts', icon: PixelTerminal, group: 'MONITOR & LAB', badge: counts.transcripts },
    { id: 'vector-lab', label: 'Vector Search Lab', icon: PixelSparkles, group: 'MONITOR & LAB' },
    { id: 'settings', label: 'Settings & MCP Specs', icon: PixelSettings, group: 'SETTINGS & SPECS' },
  ];

  // Update slider position whenever activeTab changes
  useEffect(() => {
    if (!containerRef.current) return;
    const activeEl = containerRef.current.querySelector<HTMLElement>(`[data-tab-id="${activeTab}"]`);
    if (activeEl) {
      setSliderStyle({
        top: activeEl.offsetTop,
        height: activeEl.offsetHeight,
        opacity: 1,
      });
    }
  }, [activeTab]);

  return (
    <aside className="w-60 bg-[#0f1015] border-r border-[#1e2029] flex flex-col justify-between h-screen sticky top-0 flex-shrink-0 text-xs font-sans select-none">
      <div>
        {/* BRANDING HEADER - EXACT h-14 ALIGNED WITH NAVBAR */}
        <div className="h-14 px-4 border-b border-[#1e2029] flex items-center justify-between bg-[#0a0b0e]">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-[#ff6b00] text-white rounded-none flex items-center justify-center font-bold text-sm shadow-sm shadow-[#ff6b00]/20">
              <PixelBrain className="w-4 h-4 text-white" />
            </div>
            <div>
              <span className="font-bold text-white text-xs tracking-tight block">GigaMind</span>
              <span className="text-[10px] text-[#8a8f9e] font-mono">Memory Engine</span>
            </div>
          </div>

          <span className="flex items-center gap-1 px-2 py-0.5 bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px] font-medium rounded-none">
            <span className="w-1.5 h-1.5 rounded-none bg-amber-400 animate-pulse" />
            Active
          </span>
        </div>

        {/* NAVIGATION CONTAINER WITH SMOOTH SLIDING ACTIVE HIGHLIGHT */}
        <div ref={containerRef} className="relative px-3 py-4 space-y-6 overflow-y-auto max-h-[calc(100vh-140px)]">
          {/* SMOOTH FAST SLIDING HIGHLIGHT PILL */}
          <div
            className="absolute left-3 right-3 bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] rounded-none shadow-sm shadow-[#ff6b00]/20 pointer-events-none transition-all duration-200 ease-out"
            style={{
              top: `${sliderStyle.top}px`,
              height: `${sliderStyle.height}px`,
              opacity: sliderStyle.opacity,
            }}
          />

          {/* OVERVIEW GROUP */}
          <div className="space-y-1 relative z-10">
            {navItems.filter(i => i.group === 'OVERVIEW').map(item => (
              <SidebarNavItem key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} />
            ))}
          </div>

          {/* KNOWLEDGE GROUP */}
          <div className="space-y-1 relative z-10">
            <div className="px-3 text-[10px] font-semibold text-[#8a8f9e] uppercase tracking-wider mb-1">
              KNOWLEDGE BASE
            </div>
            {navItems.filter(i => i.group === 'KNOWLEDGE BASE').map(item => (
              <SidebarNavItem key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} />
            ))}
          </div>

          {/* MONITOR GROUP */}
          <div className="space-y-1 relative z-10">
            <div className="px-3 text-[10px] font-semibold text-[#8a8f9e] uppercase tracking-wider mb-1">
              MONITOR & LAB
            </div>
            {navItems.filter(i => i.group === 'MONITOR & LAB').map(item => (
              <SidebarNavItem key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} />
            ))}
          </div>

          {/* MANAGE GROUP */}
          <div className="space-y-1 relative z-10">
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

const SidebarNavItem: React.FC<{
  item: NavItemDef;
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
}> = ({ item, activeTab, setActiveTab }) => {
  const Icon = item.icon;
  const isActive = activeTab === item.id;

  return (
    <button
      data-tab-id={item.id}
      onClick={() => setActiveTab(item.id)}
      className={`w-full flex items-center justify-between px-3 py-2 rounded-none font-sans text-xs transition-colors btn-press ${
        isActive
          ? 'text-white font-semibold'
          : 'text-[#c1c5d0] hover:text-white hover:bg-[#181a24]/60'
      }`}
    >
      <div className="flex items-center gap-2.5">
        <Icon className={`w-4 h-4 transition-colors ${isActive ? 'text-white' : 'text-[#8a8f9e]'}`} />
        <span>{item.label}</span>
      </div>
      {item.badge !== undefined && (
        <span
          className={`px-1.5 py-0.2 text-[10px] font-mono rounded-none transition-colors ${
            isActive ? 'bg-white/20 text-white' : 'bg-[#1e2029] text-[#8a8f9e]'
          }`}
        >
          {item.badge}
        </span>
      )}
    </button>
  );
};
