import React, { useState } from 'react';
import { Copy, Check, ExternalLink } from 'lucide-react';
import { PixelKey, PixelBrain, PixelSparkles } from '../ui/PixelIcons';
import { getApiKey, setApiKey } from '../../api';

export const SettingsTab: React.FC = () => {
  const [keyInput, setKeyInput] = useState(getApiKey());
  const [copiedSection, setCopiedSection] = useState<string | null>(null);

  const handleSaveKey = () => {
    setApiKey(keyInput.trim());
    alert('Master Password saved.');
  };

  const copyToClipboard = (text: string, section: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSection(section);
    setTimeout(() => setCopiedSection(null), 2000);
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
          <h2 className="text-xl font-bold text-white tracking-tight">Service Settings & MCP Protocol</h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Configure authorization keys, fastMCP SSE endpoints, and custom connector specs
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
              className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium px-4 py-2.5 rounded-none transition-all"
            >
              Save Key
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
    </div>
  );
};
