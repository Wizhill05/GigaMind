/// <reference types="vite/client" />
import React, { useState, useEffect, useRef } from "react";
import { Plus, RefreshCw, Search, ExternalLink, Upload } from "lucide-react";
import { PixelKey } from "./ui/PixelIcons";
import { getApiKey, setApiKey, uploadFile } from "../api";
import { useToast } from "./ui/Toast";

interface HeaderProps {
  onRefresh: () => void;
  isAuthenticated: boolean;
  onOpenNewMemoryModal: () => void;
  onOpenCommandPalette: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onRefresh,
  isAuthenticated,
  onOpenNewMemoryModal,
  onOpenCommandPalette,
}) => {
  const [keyInput, setKeyInput] = useState(getApiKey());
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [isExiting, setIsExiting] = useState(false);

  const { toast } = useToast();
  const [isHeaderUploading, setIsHeaderUploading] = useState(false);

  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const uploadErrorCredential = useRef(getApiKey());
  const uploadPending = useRef(false);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const handleHeaderFileUpload = async (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const input = e.currentTarget;
    const files = Array.from(input.files || []);
    input.value = "";
    if (!files.length || uploadPending.current) return;
    uploadPending.current = true;
    const credential = getApiKey();
    const active = () => mounted.current && getApiKey() === credential;
    setIsHeaderUploading(true);
    if (uploadErrorCredential.current !== credential) setUploadErrors([]);
    uploadErrorCredential.current = credential;
    let succeeded = false;
    try {
      for (const file of files) {
        if (!active()) break;
        toast(`Uploading ${file.name}...`, "info");
        const res = await uploadFile(file, "files");
        if (!active()) break;
        if (res.success) {
          succeeded = true;
          toast(`Uploaded ${file.name} & queued vector indexing`, "success");
        } else {
          setUploadErrors((errors) => [
            ...errors,
            `Failed to upload ${file.name}: ${res.error || "Unknown error"}`,
          ]);
        }
      }
      if (succeeded && active()) onRefresh();
    } finally {
      uploadPending.current = false;
      if (mounted.current) {
        setIsHeaderUploading(false);
        if (getApiKey() !== credential) setUploadErrors([]);
      }
    }
  };

  // Handle ESC key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && showKeyModal && !isExiting) {
        handleAnimatedClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showKeyModal, isExiting]);

  const handleAnimatedClose = () => {
    setIsExiting(true);
    setTimeout(() => {
      setIsExiting(false);
      setShowKeyModal(false);
    }, 180);
  };

  const handleConnect = () => {
    if (uploadPending.current) return;
    if (keyInput.trim()) {
      setApiKey(keyInput.trim());
      handleAnimatedClose();
      toast("Master key saved. Checking connection...", "info");
      onRefresh();
    }
  };

  const handleLock = () => {
    if (uploadPending.current) return;
    setApiKey("");
    setKeyInput("");
    handleAnimatedClose();
    toast("Disconnected Master Key", "info");
    onRefresh();
  };

  return (
    <header className="relative h-14 border-b border-[#262626] bg-[#0f0f0f] px-6 flex items-center justify-between font-sans text-xs select-none">
      {/* BREADCRUMB TITLE */}
      <div className="flex items-center gap-2 text-white font-medium text-xs">
        <span className="font-semibold tracking-tight text-white text-sm">
          GigaMind
        </span>
        <span className="text-[#8a8f9e]">/</span>
        <span className="text-[#8a8f9e] font-normal">Console</span>
        {import.meta.env.VITE_SYNTHETIC_DEMO === "1" && (
          <span>
            Synthetic demo · External indexing and storage unavailable
          </span>
        )}
      </div>

      {/* RIGHT ACTIONS - UNIFORM h-8 (32px) HEIGHT FOR ALL BUTTONS */}
      <div className="flex items-center gap-2.5">
        {/* CMD+K SPOTLIGHT SEARCH BUTTON */}
        <button
          disabled={isHeaderUploading}
          onClick={() => {
            if (!uploadPending.current) onOpenCommandPalette();
          }}
          className="h-8 bg-[#161616] border border-[#333333] hover:border-[#ff6b00]/40 text-[#8a8f9e] hover:text-white px-3 rounded-none flex items-center gap-2 font-medium transition-all btn-press"
          title="Search (Cmd+K / Ctrl+K)"
        >
          <Search className="w-3.5 h-3.5 text-[#ff6b00]" />
          <span className="text-xs">Search</span>
          <span className="bg-[#222222] border border-[#333333] text-[10px] font-mono px-1.5 py-0.5 rounded-none text-[#8a8f9e] leading-none">
            ⌘K
          </span>
        </button>

        {/* CONNECT AI DOCS LINK */}
        <a
          href="https://github.com/Wizhill05/GigaMind/blob/main/docs/mcp-setup.md"
          target="_blank"
          rel="noreferrer"
          className="h-8 bg-[#161616] border border-[#333333] hover:border-[#ff6b00]/40 text-[#8a8f9e] hover:text-white px-3 rounded-none flex items-center gap-1.5 font-medium transition-all btn-press"
          title="Connect AI Harnesses & Services Guide"
        >
          <ExternalLink className="w-3.5 h-3.5 text-[#ff6b00]" />
          <span className="leading-none text-xs">Connect AI</span>
        </a>

        {/* + NEW MEMORY BUTTON */}
        <button
          disabled={isHeaderUploading}
          onClick={() => {
            if (!uploadPending.current) onOpenNewMemoryModal();
          }}
          className="h-8 bg-transparent hover:bg-[#222222] border border-[#333333] text-white px-3 rounded-none flex items-center gap-1.5 font-medium transition-all btn-press"
        >
          <Plus className="w-3.5 h-3.5" />
          <span className="leading-none text-xs">New Memory</span>
        </button>

        {/* + UPLOAD FILE BUTTON */}
        <label className="h-8 bg-[#ff6b00] hover:bg-[#e05e00] text-white px-3 rounded-none flex items-center gap-1.5 font-medium transition-all btn-press cursor-pointer shadow-sm shadow-[#ff6b00]/20">
          <Upload
            className={`w-3.5 h-3.5 ${isHeaderUploading ? "animate-spin" : ""}`}
          />
          <span className="leading-none text-xs">
            {isHeaderUploading ? "Uploading..." : "Upload File"}
          </span>
          <input
            type="file"
            multiple
            className="hidden"
            onChange={handleHeaderFileUpload}
            disabled={isHeaderUploading}
          />
        </label>

        {/* MASTER KEY AUTH BUTTON - UNIFORM h-8 HEIGHT */}
        <button
          disabled={isHeaderUploading}
          onClick={() => {
            if (!uploadPending.current) setShowKeyModal(!showKeyModal);
          }}
          className={`h-8 border px-3 rounded-none flex items-center gap-2 font-medium transition-all btn-press ${
            isAuthenticated
              ? "bg-[#10b981]/15 text-emerald-400 border-emerald-500/30"
              : "bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white border-transparent hover:opacity-90"
          }`}
        >
          <span className="flex items-center justify-center flex-shrink-0">
            <PixelKey
              className={`w-3.5 h-3.5 ${isAuthenticated ? "text-emerald-400" : "text-white"}`}
            />
          </span>
          <span className="leading-none text-xs flex items-center">
            {isAuthenticated ? "Connected" : "Master Key"}
          </span>
        </button>

        {/* REFRESH - UNIFORM h-8 w-8 HEIGHT & WIDTH */}
        <button
          disabled={isHeaderUploading}
          onClick={() => {
            if (uploadPending.current) return;
            onRefresh();
            toast("Refreshed system telemetry", "info");
          }}
          className="h-8 w-8 flex items-center justify-center text-[#8a8f9e] hover:text-white border border-[#333333] bg-[#161616] rounded-none transition-all btn-press"
          title="Refresh telemetry"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {uploadErrors.length > 0 && (
        <div
          role="alert"
          className="absolute top-14 right-6 z-40 max-w-md border border-rose-500/40 bg-[#181818] p-4 space-y-2 text-white select-text"
        >
          <p>Upload failures</p>
          {uploadErrors.map((message, index) => (
            <p key={index}>{message}</p>
          ))}
          <p>
            Keep recovery references. An uncertain upload may have reached
            storage.
          </p>
          <button
            disabled={isHeaderUploading}
            onClick={() => {
              if (!uploadPending.current) setUploadErrors([]);
            }}
          >
            Dismiss upload errors
          </button>
        </div>
      )}
      {/* MASTER KEY POPUP MODAL WITH SMOOTH FADE & BACKDROP BLUR */}
      {showKeyModal && (
        <div
          onClick={handleAnimatedClose}
          className={`fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4 transition-all duration-200 ${
            isExiting ? "animate-fade-out" : "animate-fade-in"
          }`}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className={`bg-[#181818] border border-[#262626] max-w-sm w-full p-6 rounded-none shadow-2xl space-y-4 ${
              isExiting ? "animate-scale-out" : "animate-scale-in"
            }`}
          >
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <PixelKey className="w-4 h-4 text-[#ff6b00]" />
              Master API Key Settings
            </h3>
            <p className="text-xs text-[#8a8f9e] leading-relaxed">
              Enter your GigaMind Master Password to authenticate local API
              access.
            </p>
            <input
              type="password"
              disabled={isHeaderUploading}
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleConnect()}
              placeholder="Enter GIGAMIND_API_KEY..."
              autoFocus
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 text-white font-mono text-xs rounded-none outline-none transition-colors"
            />
            <div className="flex justify-end gap-2 pt-2">
              {isAuthenticated && (
                <button
                  disabled={isHeaderUploading}
                  onClick={handleLock}
                  className="bg-rose-500/20 text-rose-400 border border-rose-500/30 px-3 py-1.5 rounded-none text-xs font-medium btn-press"
                >
                  Disconnect
                </button>
              )}
              <button
                onClick={handleAnimatedClose}
                className="bg-[#222222] text-[#8a8f9e] hover:text-white px-3 py-1.5 rounded-none text-xs btn-press"
              >
                Cancel
              </button>
              <button
                disabled={isHeaderUploading}
                onClick={handleConnect}
                className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white px-4 py-1.5 rounded-none text-xs font-medium btn-press shadow-sm"
              >
                Save & Connect
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
};
