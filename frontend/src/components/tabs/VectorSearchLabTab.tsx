import React, { useState, useRef, useEffect } from "react";
import {
  Search,
  Code,
  Paperclip,
  ExternalLink,
  ImageIcon,
  X,
} from "lucide-react";
import { PixelSparkles, PixelTerminal } from "../ui/PixelIcons";
import { useLegacySearch } from "../../useLegacySearch";
import { getApiKey } from "../../api";
import { AgentBadge, CategoryBadge } from "../ui/Badge";

export const VectorSearchLabTab: React.FC = () => {
  const [query, setQuery] = useState("");
  const [queryImageBase64, setQueryImageBase64] = useState<string | null>(null);
  const [queryImageName, setQueryImageName] = useState<string | null>(null);
  const [scope, setScope] = useState<"all" | "memories" | "files">("all");
  const [category, setCategory] = useState("");
  const [sourceAgent, setSourceAgent] = useState("");
  const [limit, setLimit] = useState(5);

  const { results, pending: isLoading, error, run, clear } = useLegacySearch();
  const [showRawJson, setShowRawJson] = useState(false);
  const [imageError, setImageError] = useState("");
  const [reading, setReading] = useState(false);
  const reader = useRef<FileReader | null>(null);
  const imageCredential = useRef("");
  useEffect(
    () => () => {
      reader.current?.abort();
      reader.current = null;
    },
    [],
  );
  const cancelRead = () => {
    const old = reader.current;
    reader.current = null;
    old?.abort();
    setReading(false);
    setImageError("");
  };
  const handleSearch = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (reading) return;
    if (queryImageBase64 && getApiKey() !== imageCredential.current) {
      clear();
      setQueryImageBase64(null);
      setQueryImageName(null);
      setImageError("API key changed. Select the image again.");
      return;
    }
    await run({
      query: query.trim() || undefined,
      category: category || undefined,
      sourceAgent: sourceAgent || undefined,
      limit,
      scope,
      image: queryImageBase64 || undefined,
    });
  };
  const handleImageQuerySelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    cancelRead();
    clear();
    setQueryImageBase64(null);
    setQueryImageName(null);
    if (!file.type.startsWith("image/")) {
      setImageError("Choose an image file.");
      return;
    }
    const current = new FileReader();
    const key = getApiKey();
    reader.current = current;
    setReading(true);
    current.onload = () => {
      if (reader.current !== current) return;
      reader.current = null;
      setReading(false);
      if (getApiKey() !== key) {
        setImageError("API key changed. Select the image again.");
        return;
      }
      if (typeof current.result !== "string" || !current.result.includes(",")) {
        setImageError("Could not read the image.");
        return;
      }
      imageCredential.current = key;
      setQueryImageBase64(
        current.result.slice(current.result.indexOf(",") + 1),
      );
      setQueryImageName(file.name);
    };
    current.onerror = () => {
      if (reader.current !== current) return;
      reader.current = null;
      setReading(false);
      setImageError("Could not read the image. Select it again.");
    };
    current.readAsDataURL(file);
  };
  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-semibold text-white tracking-tight">
            Legacy source search lab
          </h2>
          <p className="text-xs text-[#8a8f9e] mt-0.5">
            Search legacy sources. Approved Knowledge is retrieved through MCP
            context. Raw scores are not confidence percentages.
          </p>
        </div>

        <button
          onClick={() => setShowRawJson(!showRawJson)}
          className={`px-3 py-1.5 text-xs font-medium border rounded-none transition-colors flex items-center gap-1.5 ${
            showRawJson
              ? "bg-[#ff6b00] text-white border-transparent"
              : "bg-[#161616] text-[#8a8f9e] border-[#333333] hover:text-white"
          }`}
        >
          <Code className="w-3.5 h-3.5" />
          <span>{showRawJson ? "Hide Raw JSON" : "Show Raw JSON"}</span>
        </button>
      </div>

      {/* SEARCH CONTROLS FORM */}
      <div className="bg-[#181818] border border-[#262626] p-5 rounded-none space-y-4">
        <form onSubmit={handleSearch} className="space-y-4">
          {/* SEARCH SCOPE TOGGLE */}
          <div className="flex items-center gap-2 border-b border-[#262626] pb-3">
            <span className="text-[#8a8f9e] text-xs font-medium">
              Search Domain:
            </span>
            <div className="flex items-center gap-1 bg-[#101010] p-1 border border-[#262626]">
              <button
                type="button"
                onClick={() => {
                  clear();
                  setScope("all");
                }}
                className={`px-3 py-1 text-xs font-medium transition-all ${
                  scope === "all"
                    ? "bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white shadow-sm"
                    : "text-[#8a8f9e] hover:text-white"
                }`}
              >
                All legacy sources (Memories + Files)
              </button>
              <button
                type="button"
                onClick={() => {
                  clear();
                  setScope("memories");
                }}
                className={`px-3 py-1 text-xs font-medium transition-all ${
                  scope === "memories"
                    ? "bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white shadow-sm"
                    : "text-[#8a8f9e] hover:text-white"
                }`}
              >
                Memories Only
              </button>
              <button
                type="button"
                onClick={() => {
                  clear();
                  setScope("files");
                }}
                className={`px-3 py-1 text-xs font-medium transition-all ${
                  scope === "files"
                    ? "bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white shadow-sm"
                    : "text-[#8a8f9e] hover:text-white"
                }`}
              >
                Files only
              </button>
            </div>
          </div>

          {/* QUERY INPUT ROW WITH VISUAL QUERY UPLOAD */}
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-[#8a8f9e] absolute left-3.5 top-3" />
              <input
                type="text"
                value={query}
                onChange={(e) => {
                  cancelRead();
                  clear();
                  setQuery(e.target.value);
                }}
                placeholder="Enter prompt query or concept text to test embedding relevance..."
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 pl-10 text-white placeholder-[#8a8f9e] outline-none rounded-none font-sans text-xs"
              />
            </div>

            <label
              className={`px-3 py-2 border transition-colors flex items-center gap-1.5 cursor-pointer font-mono text-[11px] ${
                queryImageBase64
                  ? "bg-[#22c55e]/15 border-[#22c55e]/40 text-[#22c55e]"
                  : "bg-[#1f1f1f] hover:bg-[#282828] text-[#8a8f9e] hover:text-white border-[#262626]"
              }`}
              title="Search with Image Screenshot / Diagram"
            >
              <ImageIcon className="w-3.5 h-3.5" />
              <span>
                {queryImageBase64 ? "Image Attached" : "Visual Search"}
              </span>
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={handleImageQuerySelect}
              />
            </label>
          </div>

          {queryImageName && (
            <div className="flex items-center gap-2 text-[11px] font-mono bg-[#141414] p-1.5 px-3 border border-[#262626] text-[#86efac]">
              <ImageIcon className="w-3 h-3" />
              <span>
                Visual Query: <strong>{queryImageName}</strong>
              </span>
              <button
                type="button"
                onClick={() => {
                  cancelRead();
                  clear();
                  setQueryImageBase64(null);
                  setQueryImageName(null);
                }}
                className="ml-auto text-[#8a8f9e] hover:text-white"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#8a8f9e] mb-1">
                Category Filter
              </label>
              <select
                value={category}
                onChange={(e) => {
                  clear();
                  setCategory(e.target.value);
                }}
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2 text-xs text-white outline-none rounded-none cursor-pointer"
              >
                <option value="" className="bg-[#0f0f0f]">
                  All Categories
                </option>
                <option value="general" className="bg-[#0f0f0f]">
                  general
                </option>
                <option value="coding" className="bg-[#0f0f0f]">
                  coding
                </option>
                <option value="personal" className="bg-[#0f0f0f]">
                  personal
                </option>
                <option value="project" className="bg-[#0f0f0f]">
                  project
                </option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-[#8a8f9e] mb-1">
                Source Agent Filter
              </label>
              <select
                value={sourceAgent}
                onChange={(e) => {
                  clear();
                  setSourceAgent(e.target.value);
                }}
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2 text-xs text-white outline-none rounded-none cursor-pointer"
              >
                <option value="" className="bg-[#0f0f0f]">
                  All Source Agents
                </option>
                <option value="claude" className="bg-[#0f0f0f]">
                  Claude
                </option>
                <option value="gpt" className="bg-[#0f0f0f]">
                  GPT
                </option>
                <option value="gemini" className="bg-[#0f0f0f]">
                  Gemini
                </option>
                <option value="user" className="bg-[#0f0f0f]">
                  User
                </option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-[#8a8f9e] mb-1">
                Max Results (Limit)
              </label>
              <select
                value={limit}
                onChange={(e) => {
                  clear();
                  setLimit(Number(e.target.value));
                }}
                className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2 text-xs text-white outline-none rounded-none cursor-pointer"
              >
                <option value={3} className="bg-[#0f0f0f]">
                  3 Results
                </option>
                <option value={5} className="bg-[#0f0f0f]">
                  5 Results
                </option>
                <option value={10} className="bg-[#0f0f0f]">
                  10 Results
                </option>
                <option value={20} className="bg-[#0f0f0f]">
                  20 Results
                </option>
              </select>
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading || reading}
            className="w-full bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-medium py-2.5 rounded-none transition-all flex items-center justify-center gap-2 shadow-sm"
          >
            <PixelTerminal className="w-4 h-4 text-white" />
            <span>
              {isLoading ? "Calculating similarity..." : "Run source search"}
            </span>
          </button>
        </form>
      </div>

      {reading && <p role="status">Reading image...</p>}
      {(error || imageError) && (
        <div role="alert">
          {error || imageError}{" "}
          {error && (
            <button onClick={() => void handleSearch()}>Retry search</button>
          )}
        </div>
      )}
      {/* RESULTS DISPLAY CARD */}
      {results !== null && (
        <div className="bg-[#181818] border border-[#262626] rounded-none overflow-hidden space-y-0">
          <div className="p-4 border-b border-[#262626] bg-[#161616] flex justify-between items-center text-xs text-[#8a8f9e]">
            <span>Vector relevance matches ({results.length})</span>
            <span>Raw ranking scores</span>
          </div>

          {showRawJson ? (
            <pre className="bg-[#0f0f0f] p-4 text-xs font-mono text-[#ff8800] overflow-x-auto">
              {JSON.stringify(results, null, 2)}
            </pre>
          ) : results.length === 0 ? (
            <div className="p-12 text-center text-[#8a8f9e]">
              No source matches found
            </div>
          ) : (
            <div className="divide-y divide-[#262626]">
              {results.map((res, idx) => (
                <div
                  key={res.id || idx}
                  className="p-4 space-y-2 hover:bg-[#222222] transition-colors"
                >
                  <div className="flex justify-between items-center gap-4">
                    <div className="flex flex-wrap items-center gap-2 min-w-0">
                      {res.source === "file" ? (
                        <span className="bg-emerald-950/70 text-emerald-300 border border-emerald-700/60 px-2 py-0.5 rounded-none text-[11px] font-mono font-medium uppercase flex-shrink-0 flex items-center gap-1">
                          <Paperclip className="w-3 h-3 text-emerald-400" />
                          <span>FILE CHUNK</span>
                        </span>
                      ) : (
                        <span className="bg-[#ff6b00]/15 text-[#ff6b00] border border-[#ff6b00]/30 px-2 py-0.5 rounded-none text-[11px] font-medium uppercase flex-shrink-0">
                          {res.source}
                        </span>
                      )}

                      {res.filename && (
                        <span className="font-mono text-[11px] text-white font-medium">
                          {res.filename}
                        </span>
                      )}

                      {res.citation && (
                        <span className="font-mono text-[11px] text-[#8a8f9e] bg-[#141414] px-1.5 py-0.5 border border-[#2a2a2a]">
                          {res.citation}
                        </span>
                      )}

                      {res.category && res.source !== "file" && (
                        <CategoryBadge category={res.category} />
                      )}
                      {res.source_agent && res.source !== "file" && (
                        <AgentBadge agent={res.source_agent} />
                      )}
                      <span className="font-mono text-[11px] text-[#8a8f9e] truncate">
                        id: {res.id}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0">
                      {res.url && (
                        <a
                          href={res.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[11px] flex items-center gap-1 text-[#8a8f9e] hover:text-[#ff6b00] bg-[#161616] border border-[#333333] px-2 py-1 transition-colors"
                        >
                          <ExternalLink className="w-3 h-3" />
                          <span>Open File</span>
                        </a>
                      )}
                      <span className="text-[#ff6b00] font-semibold text-xs bg-[#ff6b00]/15 border border-[#ff6b00]/30 px-2.5 py-1 rounded-none flex-shrink-0">
                        Raw score: {res.score.toFixed(4)}
                      </span>
                    </div>
                  </div>

                  <p className="text-white text-xs leading-relaxed break-words break-all">
                    {res.content}
                  </p>

                  {res.retrieval_method && (
                    <p className="text-[#8a8f9e]">
                      Retrieval: {res.retrieval_method}
                    </p>
                  )}
                  {res.attachments && res.attachments.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                      {res.attachments.map((att, attIdx) => (
                        <span
                          key={att.key || attIdx}
                          className="inline-flex items-center gap-1 bg-[#121212] border border-[#2a2a2a] px-2 py-0.5 text-[11px] text-[#c1c5d0]"
                        >
                          <Paperclip className="w-3 h-3 text-[#ff6b00]" />
                          <span className="font-mono truncate max-w-[150px]">
                            {att.filename}
                          </span>
                          {att.url && (
                            <a
                              href={att.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[#8a8f9e] hover:text-[#ff6b00] transition-colors ml-0.5"
                              title="Open / Download attached file"
                            >
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          )}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
