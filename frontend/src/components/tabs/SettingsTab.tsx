import React, { useState } from 'react';
import { Settings, Key, Copy, Check, ExternalLink, Cpu, ShieldCheck } from 'lucide-react';
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

      {/* MASTER KEY MANAGEMENT */}
      <div className="bg-[#13151c] border border-[#1e2029] p-5 rounded-lg space-y-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 border-b border-[#1e2029] pb-3">
          <Key className="w-4 h-4 text-[#a855f7]" />
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
              className="flex-1 bg-[#0a0b0e] border border-[#1e2029] focus:border-[#5b0e89] p-2.5 text-xs font-mono text-white outline-none rounded-md"
            />
            <button
              onClick={handleSaveKey}
              className="bg-[#5b0e89] hover:bg-[#6d10a3] text-white font-medium px-4 py-2.5 rounded-md transition-colors"
            >
              Save Key
            </button>
          </div>
        </div>
      </div>

      {/* ENDPOINTS GRID */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[#13151c] border border-[#1e2029] p-5 rounded-lg space-y-3">
          <span className="text-[11px] font-medium text-[#00f2fe] bg-[#00f2fe]/10 border border-[#00f2fe]/30 px-2 py-0.5 rounded-md">
            FastMCP SSE Endpoint
          </span>
          <p className="text-xs font-mono text-[#c1c5d0] break-all">{sseUrl}</p>
          <button
            onClick={() => copyToClipboard(sseUrl, 'sse')}
            className="w-full bg-[#101216] hover:bg-[#181a24] border border-[#262936] text-xs py-2 text-[#8a8f9e] hover:text-white rounded-md flex items-center justify-center gap-1.5 transition-colors"
          >
            {copiedSection === 'sse' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedSection === 'sse' ? 'Copied' : 'Copy SSE URI'}</span>
          </button>
        </div>

        <div className="bg-[#13151c] border border-[#1e2029] p-5 rounded-lg space-y-3">
          <span className="text-[11px] font-medium text-[#a855f7] bg-[#5b0e89]/20 border border-[#5b0e89]/30 px-2 py-0.5 rounded-md">
            OpenAPI 3.1.0 Spec
          </span>
          <p className="text-xs font-mono text-[#c1c5d0] break-all">{openApiUrl}</p>
          <a
            href={openApiUrl}
            target="_blank"
            rel="noreferrer"
            className="w-full bg-[#101216] hover:bg-[#181a24] border border-[#262936] text-xs py-2 text-[#8a8f9e] hover:text-white rounded-md flex items-center justify-center gap-1.5 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5 text-[#a855f7]" />
            <span>View OpenAPI JSON</span>
          </a>
        </div>

        <div className="bg-[#13151c] border border-[#1e2029] p-5 rounded-lg space-y-3">
          <span className="text-[11px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded-md">
            OAuth Authorize URL
          </span>
          <p className="text-xs font-mono text-[#c1c5d0] break-all">{oauthAuthUrl}</p>
          <button
            onClick={() => copyToClipboard(oauthAuthUrl, 'oauth')}
            className="w-full bg-[#101216] hover:bg-[#181a24] border border-[#262936] text-xs py-2 text-[#8a8f9e] hover:text-white rounded-md flex items-center justify-center gap-1.5 transition-colors"
          >
            {copiedSection === 'oauth' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedSection === 'oauth' ? 'Copied' : 'Copy OAuth URI'}</span>
          </button>
        </div>
      </div>

      {/* CLAUDE DESKTOP & CURSOR MCP CONFIG */}
      <div className="bg-[#13151c] border border-[#1e2029] p-5 rounded-lg space-y-4">
        <div className="flex justify-between items-center border-b border-[#1e2029] pb-3">
          <h3 className="text-xs font-semibold text-white flex items-center gap-2">
            <Cpu className="w-4 h-4 text-[#00f2fe]" />
            Claude Desktop & Cursor FastMCP Config
          </h3>

          <button
            onClick={() => copyToClipboard(mcpConfigSnippet, 'mcp')}
            className="px-3 py-1.5 text-xs bg-[#101216] border border-[#262936] text-[#8a8f9e] hover:text-white rounded-md flex items-center gap-1.5 transition-colors"
          >
            {copiedSection === 'mcp' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedSection === 'mcp' ? 'Copied' : 'Copy Config'}</span>
          </button>
        </div>

        <pre className="bg-[#0a0b0e] border border-[#1e2029] p-4 rounded-md text-xs font-mono text-emerald-400 overflow-x-auto">
          {mcpConfigSnippet}
        </pre>
      </div>
    </div>
  );
};
