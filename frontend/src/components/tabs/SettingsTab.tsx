import React, { useState } from 'react';
import { Copy, Check, ExternalLink, Download, Trash2, AlertTriangle, Lock } from 'lucide-react';
import { PixelKey, PixelBrain, PixelSparkles, PixelDatabase } from '../ui/PixelIcons';
import { getApiKey, setApiKey, exportMemories, hardResetMemories } from '../../api';
import { useToast } from '../ui/Toast';

export const SettingsTab: React.FC = () => {
  const [keyInput, setKeyInput] = useState(getApiKey());
  const [copiedSection, setCopiedSection] = useState<string | null>(null);
  const [showResetModal, setShowResetModal] = useState(false);
  const [resetPasswordInput, setResetPasswordInput] = useState('');
  const [resetErrorMessage, setResetErrorMessage] = useState('');
  const [isResetting, setIsResetting] = useState(false);

  const { toast } = useToast();

  const handleSaveKey = () => {
    setApiKey(keyInput.trim());
    toast('Master Password saved.', 'success');
  };

  const copyToClipboard = (text: string, section: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSection(section);
    setTimeout(() => setCopiedSection(null), 2000);
  };

  const handleExport = async (format: 'json' | 'csv') => {
    toast(`Exporting memories as ${format.toUpperCase()}...`, 'info');
    await exportMemories(format);
  };

  const handleConfirmHardReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetPasswordInput.trim()) {
      setResetErrorMessage('Password is required to confirm hard reset');
      return;
    }

    setIsResetting(true);
    setResetErrorMessage('');
    const res = await hardResetMemories(resetPasswordInput.trim());
    setIsResetting(false);

    if (res && res.success) {
      toast(res.message || 'Hard memory reset complete.', 'success');
      setShowResetModal(false);
      setResetPasswordInput('');
    } else {
      setResetErrorMessage(res?.message || 'Password verification failed');
    }
  };

  const sseUrl = `${window.location.origin}/sse`;
  const openApiUrl = `${window.location.origin}/openapi.json`;
  const oauthAuthUrl = `${window.location.origin}/oauth/authorize`;

  const mcpConfigSnippet = JSON.stringify(
    {
      mcpServers: {
        gigamind: {
          command: 'npx',
          args: ['-y', '@modelcontextprotocol/server-sse'],
          env: {
            URL: sseUrl,
            API_KEY: getApiKey() || 'YOUR_MASTER_KEY',
          },
        },
      },
    },
    null,
    2
  );

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-semibold text-white tracking-tight">Service Settings & MCP Protocol</h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Configure authorization keys, export database records, and perform administrative actions
          </p>
        </div>
      </div>

      {/* CONNECT AI SERVICES FEATURED BANNER */}
      <div className="bg-[#181818] border border-[#ff6b00]/30 p-5 rounded-none space-y-3 bg-gradient-to-r from-[#ff6b00]/10 via-transparent to-transparent">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div className="space-y-1">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <PixelSparkles className="w-4 h-4 text-[#ff6b00]" />
              Connect GigaMind to AI Services & Coding Harnesses
            </h3>
            <p className="text-xs text-[#8a8f9e]">
              Step-by-step documentation for Claude Web (claude.ai), Claude Code, Cursor, Windsurf, OpenCode, ChatGPT Custom GPTs, and Claude Desktop.
            </p>
          </div>
          <a
            href="https://github.com/Wizhill05/GigaMind#connecting-gigamind-to-ai-services--coding-harnesses"
            target="_blank"
            rel="noreferrer"
            className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white text-xs font-medium px-4 py-2 rounded-none flex items-center gap-1.5 transition-all btn-press flex-shrink-0"
          >
            <span>View Connect Guide</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>

      {/* MASTER KEY MANAGEMENT */}
      <div className="bg-[#181818] border border-[#262626] p-5 rounded-none space-y-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 border-b border-[#262626] pb-3">
          <PixelKey className="w-4 h-4 text-[#ff6b00]" />
          Master Password Settings
        </h3>

        <div className="space-y-3 max-w-xl">
          <label className="block text-xs text-[#8a8f9e]">
            GIGAMIND MASTER API KEY
          </label>
          <div className="flex gap-2">
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="Enter GIGAMIND_API_KEY..."
              className="flex-1 bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 text-xs font-mono text-white outline-none rounded-none"
            />
            <button
              onClick={handleSaveKey}
              className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium px-4 py-2.5 rounded-none transition-all btn-press"
            >
              Save Key
            </button>
          </div>
        </div>
      </div>

      {/* EXPORT DATABASE SECTION */}
      <div className="bg-[#181818] border border-[#262626] p-5 rounded-none space-y-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 border-b border-[#262626] pb-3">
          <PixelDatabase className="w-4 h-4 text-[#ff6b00]" />
          Database Backup & Export
        </h3>

        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div className="space-y-1">
            <p className="text-xs text-[#c1c5d0] font-medium">Export All Memory Records</p>
            <p className="text-xs text-[#8a8f9e]">
              Download your entire persistent memory database as structured JSON or CSV for backups and analysis.
            </p>
          </div>

          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              onClick={() => handleExport('json')}
              className="bg-[#161616] border border-[#333333] hover:border-[#ff6b00]/40 text-white font-medium px-4 py-2 rounded-none transition-colors flex items-center gap-2 btn-press"
            >
              <Download className="w-3.5 h-3.5 text-[#ff6b00]" />
              <span>Export JSON</span>
            </button>

            <button
              onClick={() => handleExport('csv')}
              className="bg-[#161616] border border-[#333333] hover:border-[#ff6b00]/40 text-white font-medium px-4 py-2 rounded-none transition-colors flex items-center gap-2 btn-press"
            >
              <Download className="w-3.5 h-3.5 text-amber-400" />
              <span>Export CSV</span>
            </button>
          </div>
        </div>
      </div>

      {/* ENDPOINTS GRID */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[#181818] border border-[#262626] p-5 rounded-none space-y-3">
          <span className="text-[11px] font-medium text-[#ff6b00] bg-[#ff6b00]/10 border border-[#ff6b00]/30 px-2 py-0.5 rounded-none">
            FastMCP SSE Endpoint
          </span>
          <p className="text-xs font-mono text-[#c1c5d0] break-all">{sseUrl}</p>
          <button
            onClick={() => copyToClipboard(sseUrl, 'sse')}
            className="w-full bg-[#161616] hover:bg-[#222222] border border-[#333333] text-xs py-2 text-[#8a8f9e] hover:text-white rounded-none flex items-center justify-center gap-1.5 transition-colors"
          >
            {copiedSection === 'sse' ? <Check className="w-3.5 h-3.5 text-amber-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedSection === 'sse' ? 'Copied' : 'Copy SSE URI'}</span>
          </button>
        </div>

        <div className="bg-[#181818] border border-[#262626] p-5 rounded-none space-y-3">
          <span className="text-[11px] font-medium text-[#ff8800] bg-[#ff8800]/10 border border-[#ff8800]/30 px-2 py-0.5 rounded-none">
            OpenAPI 3.1.0 Spec
          </span>
          <p className="text-xs font-mono text-[#c1c5d0] break-all">{openApiUrl}</p>
          <a
            href={openApiUrl}
            target="_blank"
            rel="noreferrer"
            className="w-full bg-[#161616] hover:bg-[#222222] border border-[#333333] text-xs py-2 text-[#8a8f9e] hover:text-white rounded-none flex items-center justify-center gap-1.5 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5 text-[#ff8800]" />
            <span>View OpenAPI JSON</span>
          </a>
        </div>

        <div className="bg-[#181818] border border-[#262626] p-5 rounded-none space-y-3">
          <span className="text-[11px] font-medium text-amber-400 bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 rounded-none">
            OAuth Authorize URL
          </span>
          <p className="text-xs font-mono text-[#c1c5d0] break-all">{oauthAuthUrl}</p>
          <button
            onClick={() => copyToClipboard(oauthAuthUrl, 'oauth')}
            className="w-full bg-[#161616] hover:bg-[#222222] border border-[#333333] text-xs py-2 text-[#8a8f9e] hover:text-white rounded-none flex items-center justify-center gap-1.5 transition-colors"
          >
            {copiedSection === 'oauth' ? <Check className="w-3.5 h-3.5 text-amber-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedSection === 'oauth' ? 'Copied' : 'Copy OAuth URI'}</span>
          </button>
        </div>
      </div>

      {/* CLAUDE DESKTOP & CURSOR MCP CONFIG */}
      <div className="bg-[#181818] border border-[#262626] p-5 rounded-none space-y-4">
        <div className="flex justify-between items-center border-b border-[#262626] pb-3">
          <h3 className="text-xs font-semibold text-white flex items-center gap-2">
            <PixelBrain className="w-4 h-4 text-[#ff6b00]" />
            Claude Desktop & Cursor FastMCP Config
          </h3>

          <button
            onClick={() => copyToClipboard(mcpConfigSnippet, 'mcp')}
            className="px-3 py-1.5 text-xs bg-[#161616] border border-[#333333] text-[#8a8f9e] hover:text-white rounded-none flex items-center gap-1.5 transition-colors"
          >
            {copiedSection === 'mcp' ? <Check className="w-3.5 h-3.5 text-amber-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedSection === 'mcp' ? 'Copied' : 'Copy Config'}</span>
          </button>
        </div>

        <pre className="bg-[#0f0f0f] border border-[#262626] p-4 rounded-none text-xs font-mono text-[#ff8800] overflow-x-auto">
          {mcpConfigSnippet}
        </pre>
      </div>

      {/* DANGER ZONE - HARD MEMORY RESET */}
      <div className="bg-rose-500/5 border border-rose-500/30 p-5 rounded-none space-y-4">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b border-rose-500/20 pb-3">
          <div>
            <h3 className="text-sm font-semibold text-rose-400 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
              Danger Zone — Hard Memory Reset
            </h3>
            <p className="text-xs text-[#8a8f9e] mt-1">
              Permanently purge all memory records from the GigaMind engine. This action is irreversible.
            </p>
          </div>

          <button
            onClick={() => {
              setShowResetModal(true);
              setResetErrorMessage('');
              setResetPasswordInput('');
            }}
            className="bg-rose-600 hover:bg-rose-700 text-white font-semibold px-4 py-2 rounded-none transition-colors flex items-center gap-2 btn-press flex-shrink-0"
          >
            <Trash2 className="w-4 h-4" />
            <span>Hard Reset Database</span>
          </button>
        </div>
      </div>

      {/* HARD RESET CONFIRMATION MODAL */}
      {showResetModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-[#181818] border border-rose-500/40 p-6 max-w-md w-full rounded-none space-y-5 animate-scale-in">
            <div className="flex items-center gap-3 border-b border-[#262626] pb-4">
              <div className="w-9 h-9 bg-rose-500/10 border border-rose-500/30 text-rose-400 flex items-center justify-center flex-shrink-0">
                <Lock className="w-5 h-5 text-rose-400" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-white">Confirm Hard Memory Reset</h3>
                <p className="text-xs text-rose-400 mt-0.5">Password Re-authentication Required</p>
              </div>
            </div>

            <p className="text-xs text-[#c1c5d0] leading-relaxed">
              Are you sure you want to purge <strong>ALL</strong> memory items? To confirm this destructive action, please re-enter your GigaMind Master Password below.
            </p>

            <form onSubmit={handleConfirmHardReset} className="space-y-4">
              <div>
                <label className="block text-xs text-[#8a8f9e] mb-1.5">
                  ENTER MASTER PASSWORD / API KEY
                </label>
                <input
                  type="password"
                  value={resetPasswordInput}
                  onChange={(e) => setResetPasswordInput(e.target.value)}
                  placeholder="Master API Key..."
                  className="w-full bg-[#0f0f0f] border border-rose-500/40 focus:border-rose-500 p-2.5 text-xs font-mono text-white outline-none rounded-none"
                  autoFocus
                />
                {resetErrorMessage && (
                  <p className="text-xs text-rose-400 mt-1.5">{resetErrorMessage}</p>
                )}
              </div>

              <div className="flex justify-end items-center gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowResetModal(false)}
                  className="bg-[#161616] border border-[#333333] hover:bg-[#222222] text-[#c1c5d0] hover:text-white px-4 py-2 rounded-none text-xs transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isResetting}
                  className="bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white font-medium px-4 py-2 rounded-none text-xs transition-colors flex items-center gap-1.5 btn-press"
                >
                  {isResetting ? (
                    <span>Purging...</span>
                  ) : (
                    <>
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Confirm & Erase All Memories</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
