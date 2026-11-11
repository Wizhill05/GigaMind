import React from "react";
import {
  LayoutDashboard,
  Database,
  HardDrive,
  Shield,
  MessageSquare,
  Sparkles,
  Settings,
} from "lucide-react";

export type TabType =
  | "jobs"
  | "clients"
  | "activity"
  | "review"
  | "overview"
  | "memories"
  | "files"
  | "rules"
  | "transcripts"
  | "vector-lab"
  | "settings";

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

export const NavigationTabs: React.FC<NavigationTabsProps> = ({
  activeTab,
  setActiveTab,
  counts,
}) => {
  const tabs: {
    id: TabType;
    label: string;
    icon: typeof Shield;
    badge?: number;
  }[] = [
    { id: "jobs", label: "Jobs", icon: Shield },
    { id: "clients", label: "Clients", icon: Shield },
    { id: "activity", label: "Activity", icon: Shield },
    { id: "review", label: "Review", icon: Shield },
    {
      id: "overview",
      label: "Overview & Telemetry",
      icon: LayoutDashboard,
    },
    {
      id: "memories",
      label: "Memory Repository",
      icon: Database,
      badge: counts.memories,
    },
    {
      id: "files",
      label: "Files & R2 Storage",
      icon: HardDrive,
      badge: counts.files,
    },
    {
      id: "rules",
      label: "Identity & Profile Rules",
      icon: Shield,
      badge: counts.rules,
    },
    {
      id: "transcripts",
      label: "Chat Transcripts",
      icon: MessageSquare,
      badge: counts.transcripts,
    },
    {
      id: "vector-lab",
      label: "Semantic Vector Lab",
      icon: Sparkles,
    },
    {
      id: "settings",
      label: "Settings & MCP Specs",
      icon: Settings,
    },
  ];

  return (
    <nav className="bg-[#141414] border-b border-[#262626] px-4 md:px-8 flex overflow-x-auto scrollbar-none select-none">
      <div className="flex space-x-1 py-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;

          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-mono font-semibold uppercase tracking-wider transition-all border-b-2 whitespace-nowrap rounded-none ${
                isActive
                  ? "border-[#ff6b00] text-white bg-[#1c1c1c]"
                  : "border-transparent text-[#8a8f9e] hover:text-white hover:bg-[#1a1a1a]"
              }`}
            >
              <Icon
                className={`w-3.5 h-3.5 ${isActive ? "text-[#ff6b00]" : "text-[#8a8f9e]"}`}
              />
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span
                  className={`px-1.5 py-0.2 text-[10px] font-mono font-bold rounded-none ${
                    isActive
                      ? "bg-[#ff6b00]/20 text-[#ff6b00] border border-[#ff6b00]/30"
                      : "bg-[#262626] text-[#8a8f9e]"
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
