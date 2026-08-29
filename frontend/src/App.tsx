import React, { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { TabType } from './components/NavigationTabs';
import { AuthGate } from './components/AuthGate';
import { OverviewTab } from './components/tabs/OverviewTab';
import { MemoriesTab } from './components/tabs/MemoriesTab';
import { FilesTab } from './components/tabs/FilesTab';
import { ProfileRulesTab } from './components/tabs/ProfileRulesTab';
import { ConversationsTab } from './components/tabs/ConversationsTab';
import { VectorSearchLabTab } from './components/tabs/VectorSearchLabTab';
import { SettingsTab } from './components/tabs/SettingsTab';
import { MemoryModal } from './components/modals/MemoryModal';
import { RuleModal } from './components/modals/RuleModal';
import { TranscriptDrawer } from './components/modals/TranscriptDrawer';
import { CommandPalette } from './components/CommandPalette';
import { ToastProvider, useToast } from './components/ui/Toast';
import { Stats, Memory, Conversation } from './types';
import { fetchStats, addMemory, updateMemory, setProfileRule, getApiKey } from './api';

export const AppContent: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [stats, setStats] = useState<Stats | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(true);
  const [showAuthGate, setShowAuthGate] = useState<boolean>(false);

  // Modals & Palette state
  const [isMemoryModalOpen, setIsMemoryModalOpen] = useState(false);
  const [editingMemory, setEditingMemory] = useState<Memory | null>(null);

  const [isRuleModalOpen, setIsRuleModalOpen] = useState(false);
  const [activeTranscript, setActiveTranscript] = useState<Conversation | null>(null);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  const { toast } = useToast();

  const loadStats = async () => {
    const key = getApiKey();
    if (!key) {
      setIsAuthenticated(false);
      setShowAuthGate(true);
      return;
    }

    const data = await fetchStats();
    if (data) {
      setStats(data);
      setIsAuthenticated(true);
      setShowAuthGate(false);
    } else {
      setIsAuthenticated(false);
      setShowAuthGate(true);
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  // Global Cmd+K / Ctrl+K keyboard shortcut listener
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, []);

  // Memory modal handlers
  const handleOpenNewMemoryModal = () => {
    setEditingMemory(null);
    setIsMemoryModalOpen(true);
  };

  const handleOpenEditMemoryModal = (mem: Memory) => {
    setEditingMemory(mem);
    setIsMemoryModalOpen(true);
  };

  const handleSaveMemory = async (data: { content: string; category: string; source_agent: string; tags: string[] }) => {
    if (editingMemory) {
      await updateMemory(editingMemory.id, data);
      toast(`Memory ${editingMemory.id} updated successfully`, 'success');
    } else {
      await addMemory(data);
      toast(`New memory saved to repository`, 'success');
    }
    loadStats();
  };

  // Rule modal handlers
  const handleSaveRule = async (data: { key: string; value: string; category: string; source_agent: string }) => {
    await setProfileRule(data);
    toast(`Profile rule '${data.key}' saved successfully`, 'success');
    loadStats();
  };

  return (
    <div className="flex h-screen bg-[#0f0f0f] text-[#f4f5f8] overflow-hidden font-sans">
      {/* AUTH OVERLAY GATE */}
      {showAuthGate && (
        <AuthGate
          onAuthenticate={loadStats}
          errorNotice={!isAuthenticated && !!getApiKey()}
        />
      )}

      {/* LEFT SIDEBAR NAVIGATION */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        counts={{
          memories: stats?.total_memories || 0,
          files: stats?.total_storage_files || 0,
          rules: stats?.total_profile_rules || 0,
          transcripts: stats?.total_chat_logs || 0,
        }}
      />

      {/* MAIN RIGHT CANVAS */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        {/* TOP BREADCRUMB HEADER */}
        <Header
          onRefresh={loadStats}
          isAuthenticated={isAuthenticated}
          onOpenNewMemoryModal={handleOpenNewMemoryModal}
          onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        />

        {/* SCROLLABLE MAIN CONTENT CANVAS WITH SMOOTH ANIMATED TAB TRANSITIONS */}
        <main className="flex-1 overflow-y-auto p-6 md:p-8">
          <div key={activeTab} className="max-w-6xl mx-auto space-y-6 animate-slide-up">
            {activeTab === 'overview' && (
              <OverviewTab stats={stats} onNavigateTab={(tab) => setActiveTab(tab)} />
            )}

            {activeTab === 'memories' && (
              <MemoriesTab
                onOpenNewModal={handleOpenNewMemoryModal}
                onOpenEditModal={handleOpenEditMemoryModal}
              />
            )}

            {activeTab === 'files' && <FilesTab />}

            {activeTab === 'rules' && (
              <ProfileRulesTab onOpenNewRuleModal={() => setIsRuleModalOpen(true)} />
            )}

            {activeTab === 'transcripts' && (
              <ConversationsTab onOpenTranscript={(conv) => setActiveTranscript(conv)} />
            )}

            {activeTab === 'vector-lab' && <VectorSearchLabTab />}

            {activeTab === 'settings' && <SettingsTab />}
          </div>
        </main>
      </div>

      {/* MODALS & DRAWERS */}
      <MemoryModal
        isOpen={isMemoryModalOpen}
        onClose={() => setIsMemoryModalOpen(false)}
        onSave={handleSaveMemory}
        initialMemory={editingMemory}
      />

      <RuleModal
        isOpen={isRuleModalOpen}
        onClose={() => setIsRuleModalOpen(false)}
        onSave={handleSaveRule}
      />

      <TranscriptDrawer
        conversation={activeTranscript}
        onClose={() => setActiveTranscript(null)}
      />

      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
      />
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  );
};
