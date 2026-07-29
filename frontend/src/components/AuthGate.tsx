import React, { useState } from 'react';
import { ShieldAlert, Key, ArrowRight } from 'lucide-react';
import { setApiKey } from '../api';

interface AuthGateProps {
  onAuthenticate: () => void;
  errorNotice?: boolean;
}

export const AuthGate: React.FC<AuthGateProps> = ({ onAuthenticate, errorNotice }) => {
  const [keyInput, setKeyInput] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (keyInput.trim()) {
      setApiKey(keyInput.trim());
      onAuthenticate();
    }
  };

  return (
    <div className="fixed inset-0 bg-[#0a0b0e]/90 backdrop-blur-sm z-50 flex items-center justify-center p-4 font-sans select-none">
      <div className="bg-[#13151c] border border-[#1e2029] max-w-md w-full p-8 rounded-xl shadow-2xl space-y-6">
        <div className="text-center space-y-2">
          <div className="w-12 h-12 bg-[#5b0e89]/20 border border-[#5b0e89]/40 text-[#a855f7] mx-auto rounded-full flex items-center justify-center">
            <Key className="w-6 h-6" />
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight">
            Authenticate Connection
          </h2>
          <p className="text-xs text-[#8a8f9e] leading-relaxed">
            Enter your GigaMind Master Password to access your personal memory database and telemetry endpoints.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          <div>
            <label className="block text-xs font-medium text-[#c1c5d0] mb-1.5">
              Master API Key
            </label>
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="Enter GIGAMIND_API_KEY..."
              autoFocus
              className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#a855f7] p-3 text-white font-mono text-xs rounded-md outline-none transition-colors"
            />
          </div>

          {errorNotice && (
            <div className="bg-rose-500/10 border border-rose-500/30 p-3 text-xs text-rose-400 rounded-md text-center">
              Invalid Master Password. Please check your key and try again.
            </div>
          )}

          <button
            type="submit"
            className="w-full bg-[#5b0e89] hover:bg-[#6d10a3] text-white font-semibold py-3 rounded-md text-xs tracking-wide flex items-center justify-center gap-2 shadow-lg shadow-[#5b0e89]/20 transition-all"
          >
            <span>Authorize Connection</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
};
