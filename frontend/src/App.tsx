import React, { useState, useEffect, useRef } from "react";
import { Sidebar } from "./components/Sidebar";
import { Header } from "./components/Header";
import { TabType } from "./components/NavigationTabs";
import { AuthGate } from "./components/AuthGate";
import { OverviewTab } from "./components/tabs/OverviewTab";
import { MemoriesTab } from "./components/tabs/MemoriesTab";
import { FilesTab } from "./components/tabs/FilesTab";
import { ProfileRulesTab } from "./components/tabs/ProfileRulesTab";
import { ConversationsTab } from "./components/tabs/ConversationsTab";
import { VectorSearchLabTab } from "./components/tabs/VectorSearchLabTab";
import { ActivityTab } from "./components/tabs/ActivityTab";
import { ReviewTab } from "./components/tabs/ReviewTab";
import { KnowledgeTab } from "./components/tabs/KnowledgeTab";
import { ClientsTab } from "./components/tabs/ClientsTab";
import { JobsTab } from "./components/tabs/JobsTab";
import { SettingsTab } from "./components/tabs/SettingsTab";
import { MemoryModal } from "./components/modals/MemoryModal";
import { RuleModal } from "./components/modals/RuleModal";
import { TranscriptDrawer } from "./components/modals/TranscriptDrawer";
import { CommandPalette } from "./components/CommandPalette";
import { ToastProvider, useToast } from "./components/ui/Toast";
import { Stats, Memory, Conversation } from "./types";
import { useConversationMutation } from "./useConversationMutation";
import {
  ApiError,
  fetchStats,
  addMemory,
  updateMemory,
  setProfileRule,
  getApiKey,
  fetchConversation,
  deleteConversation,
  vectorizeConversation,
} from "./api";

export const AppContent: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>("overview");
  const [stats, setStats] = useState<Stats | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [showAuthGate, setShowAuthGate] = useState<boolean>(false);
  const [authError, setAuthError] = useState("");
  const [authPending, setAuthPending] = useState(false);
  const statsRequest = useRef<AbortController | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);

  // Modals & Palette state
  const [isMemoryModalOpen, setIsMemoryModalOpen] = useState(false);
  const [editingMemory, setEditingMemory] = useState<Memory | null>(null);

  const [isRuleModalOpen, setIsRuleModalOpen] = useState(false);
  const [activeTranscript, setActiveTranscript] = useState<Conversation | null>(
    null,
  );
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  const { toast } = useToast();

  const loadStats = async () => {
    statsRequest.current?.abort();
    const controller = new AbortController();
    statsRequest.current = controller;
    const key = getApiKey();
    if (!key) {
      setIsAuthenticated(false);
      setShowAuthGate(true);
      setAuthPending(false);
      return;
    }

    setAuthPending(true);
    try {
      const data = await fetchStats(controller.signal);
      if (controller.signal.aborted || getApiKey() !== key) return;
      setStats(data);
      setIsAuthenticated(true);
      setShowAuthGate(false);
      setAuthError("");
    } catch (error) {
      if (controller.signal.aborted || getApiKey() !== key) return;
      setIsAuthenticated(false);
      setShowAuthGate(true);
      setAuthError(
        error instanceof ApiError && error.status === 401
          ? "Invalid master key."
          : error instanceof ApiError && error.status === 403
            ? "Dashboard access requires an admin credential."
            : error instanceof Error
              ? error.message
              : "Unable to connect.",
      );
    } finally {
      if (!controller.signal.aborted && getApiKey() === key)
        setAuthPending(false);
    }
  };

  useEffect(() => {
    void loadStats();
    return () => statsRequest.current?.abort();
  }, []);

  const mutation = useConversationMutation();

  // Global Cmd+K / Ctrl+K keyboard shortcut listener
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if (mutation.locked.current) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, []);

  // Memory modal handlers
  const handleOpenNewMemoryModal = () => {
    if (mutation.locked.current) return;
    setEditingMemory(null);
    setIsMemoryModalOpen(true);
  };

  const handleOpenEditMemoryModal = (mem: Memory) => {
    if (mutation.locked.current) return;
    setEditingMemory(mem);
    setIsMemoryModalOpen(true);
  };

  const handleSaveMemory = async (data: {
    content: string;
    category: string;
    source_agent: string;
    tags: string[];
  }) => {
    if (editingMemory) {
      const result = await updateMemory(editingMemory.id, {
        ...data,
        expected_revision: editingMemory.revision ?? undefined,
      });
      if (!result?.success) throw new Error("Memory update failed.");
      toast(`Memory ${editingMemory.id} updated successfully`, "success");
    } else {
      const result = await addMemory(data);
      if (!result?.success) throw new Error("Memory save failed.");
      toast(`New memory saved to repository`, "success");
    }
    setRefreshVersion((v) => v + 1);
    void loadStats();
  };

  // Rule modal handlers
  const handleSaveRule = async (data: {
    key: string;
    value: string;
    category: string;
    source_agent: string;
  }) => {
    const result = await setProfileRule(data);
    if (!result?.success) throw new Error("Rule save failed.");
    toast(`Profile rule '${data.key}' saved successfully`, "success");
    setRefreshVersion((v) => v + 1);
    void loadStats();
  };

  const conversationChanged = () => {
    setRefreshVersion((v) => v + 1);
    void loadStats();
  };
  const runTranscriptMutation = (
    action: (valid: () => boolean) => Promise<void>,
  ) =>
    mutation.run(action, (error) =>
      toast(error instanceof Error ? error.message : "Request failed", "error"),
    );
  const handleDeleteTranscript = (id: string) => {
    if (
      mutation.locked.current ||
      !window.confirm(
        "Permanently delete conversation transcript from database?",
      )
    )
      return;
    void runTranscriptMutation(async (valid) => {
      await deleteConversation(id);
      if (!valid()) return;
      toast("Deleted conversation transcript", "success");
      setActiveTranscript(null);
      conversationChanged();
    });
  };
  const handleVectorizeTranscript = (id: string) => {
    void runTranscriptMutation(async (valid) => {
      await vectorizeConversation(id);
      if (!valid()) return;
      conversationChanged();
      const updated = await fetchConversation(id);
      if (!valid()) return;
      setActiveTranscript((current) =>
        current?.id === id ? updated : current,
      );
      if (valid()) toast("Vectorization request completed", "success");
    });
  };

  return (
    <div className="flex h-screen bg-[#0f0f0f] text-[#f4f5f8] overflow-hidden font-sans">
      {/* AUTH OVERLAY GATE */}
      {showAuthGate && (
        <AuthGate
          onAuthenticate={loadStats}
          errorNotice={authError}
          pending={authPending}
        />
      )}

      {isAuthenticated && (
        <>
          {/* LEFT SIDEBAR NAVIGATION */}
          <fieldset disabled={mutation.busy} className="contents">
            <Sidebar
              activeTab={activeTab}
              setActiveTab={(tab) => {
                if (!mutation.locked.current) setActiveTab(tab);
              }}
              counts={{
                memories: stats?.total_memories || 0,
                files: stats?.total_storage_files || 0,
                rules: stats?.total_profile_rules || 0,
                transcripts: stats?.total_chat_logs || 0,
              }}
            />
          </fieldset>
          {/* MAIN RIGHT CANVAS */}
          <div className="flex-1 flex flex-col h-screen overflow-hidden">
            {/* TOP BREADCRUMB HEADER */}
            <fieldset disabled={mutation.busy} className="contents">
              <Header
                onRefresh={() => {
                  if (mutation.locked.current) return;
                  setRefreshVersion((v) => v + 1);
                  void loadStats();
                }}
                isAuthenticated={isAuthenticated}
                onOpenNewMemoryModal={handleOpenNewMemoryModal}
                onOpenCommandPalette={() => {
                  if (!mutation.locked.current) setIsCommandPaletteOpen(true);
                }}
              />
            </fieldset>
            {/* SCROLLABLE MAIN CONTENT CANVAS WITH SMOOTH ANIMATED TAB TRANSITIONS */}
            <main className="flex-1 overflow-y-auto p-6 md:p-8">
              <div
                key={activeTab}
                className="max-w-6xl mx-auto space-y-6 animate-slide-up"
              >
                {activeTab === "overview" && (
                  <OverviewTab
                    stats={stats}
                    onNavigateTab={(tab) => {
                      if (!mutation.locked.current) setActiveTab(tab);
                    }}
                  />
                )}

                {activeTab === "memories" && (
                  <MemoriesTab
                    refreshVersion={refreshVersion}
                    onMutation={() => {
                      setRefreshVersion((v) => v + 1);
                      void loadStats();
                    }}
                    onOpenNewModal={handleOpenNewMemoryModal}
                    onOpenEditModal={handleOpenEditMemoryModal}
                  />
                )}

                {activeTab === "activity" && (
                  <ActivityTab refreshVersion={refreshVersion} />
                )}

                {activeTab === "review" && (
                  <ReviewTab
                    refreshVersion={refreshVersion}
                    onMutation={() => {
                      setRefreshVersion((v) => v + 1);
                      void loadStats();
                    }}
                  />
                )}
                {activeTab === "knowledge" && (
                  <KnowledgeTab refreshVersion={refreshVersion} />
                )}

                {activeTab === "files" && <FilesTab />}

                {activeTab === "rules" && (
                  <ProfileRulesTab
                    refreshVersion={refreshVersion}
                    onOpenNewRuleModal={() => setIsRuleModalOpen(true)}
                  />
                )}

                {activeTab === "transcripts" && (
                  <ConversationsTab
                    mutation={mutation}
                    onList={(items) =>
                      setActiveTranscript((current) =>
                        current
                          ? (items.find((item) => item.id === current.id) ??
                            current)
                          : null,
                      )
                    }
                    onMutation={conversationChanged}
                    refreshVersion={refreshVersion}
                    onOpenTranscript={(conv) => {
                      if (!mutation.locked.current) setActiveTranscript(conv);
                    }}
                  />
                )}

                {activeTab === "vector-lab" && <VectorSearchLabTab />}

                {activeTab === "clients" && (
                  <ClientsTab refreshVersion={refreshVersion} />
                )}
                {activeTab === "jobs" && (
                  <JobsTab refreshVersion={refreshVersion} />
                )}

                {activeTab === "settings" && <SettingsTab />}
              </div>
            </main>
          </div>
        </>
      )}
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
        busy={mutation.busy}
        conversation={activeTranscript}
        onClose={() => {
          if (!mutation.locked.current) setActiveTranscript(null);
        }}
        onDelete={handleDeleteTranscript}
        onVectorize={handleVectorizeTranscript}
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
