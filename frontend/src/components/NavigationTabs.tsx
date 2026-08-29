import React from 'react';
import { LayoutDashboard, Database, HardDrive, Shield, MessageSquare, Sparkles, Settings } from 'lucide-react';

export type TabType = 'overview' | 'memories' | 'files' | 'rules' | 'transcripts' | 'vector-lab' | 'settings';

interface NavigationTabsProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  counts: {
    memories: number;
    files?: number;
    rules: number;
    transcripts: number;
  };
}

export const NavigationTabs: React.FC<NavigationTabsProps> = ({ activeTab, setActiveTab, counts }) => {
  const tabs = [
    {
      id: 'overview' as TabType,
      label: 'Overview & Telemetry',
      icon: LayoutDashboard,
    },
    {
      id: 'memories' as TabType,
      label: 'Memory Repository',
      icon: Database,
      badge: counts.memories,
    },
    {
      id: 'files' as TabType,
      label: 'Files & R2 Storage',
      icon: HardDrive,
      badge: counts.files,
    },
    {
      id: 'rules' as TabType,
      label: 'Identity & Profile Rules',
      icon: Shield,
      badge: counts.rules,
    },
    {
      id: 'transcripts' as TabType,
      label: 'Chat Transcripts',
      icon: MessageSquare,
      badge: counts.transcripts,
    },
    {
      id: 'vector-lab' as TabType,
      label: 'Semantic Vector Lab',
      icon: Sparkles,
    },
    {
      id: 'settings' as TabType,
      label: 'Settings & MCP Specs',
      icon: Settings,
    },
  ];

  return (
    <nav className="bg-[#15171e] border-b border-[#272935] px-4 md:px-8 flex overflow-x-auto scrollbar-none">
      <div className="flex space-x-1 py-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;

          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-3 text-xs font-mono font-semibold uppercase tracking-wider transition-all border-b-2 whitespace-nowrap rounded-none ${
                isActive
                  ? 'border-[#00f2fe] text-[#00f2fe] bg-[#0b0c10]/60'
                  : 'border-transparent text-[#8b8f9a] hover:text-[#c1c5d0] hover:bg-[#1c1f29]'
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-[#00f2fe]' : 'text-[#8b8f9a]'}`} />
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span
                  className={`px-1.5 py-0.5 text-[10px] font-mono font-bold rounded-none ${
                    isActive
                      ? 'bg-[#00f2fe]/20 text-[#00f2fe] border border-[#00f2fe]/30'
                      : 'bg-[#272935] text-[#8b8f9a]'
                  }`}
                >
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
};
