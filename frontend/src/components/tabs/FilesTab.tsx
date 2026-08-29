import React, { useState, useEffect } from 'react';
import {
  FileText,
  Upload,
  Search,
  RefreshCw,
  Trash2,
  ExternalLink,
  Layers,
  CheckCircle2,
  AlertCircle,
  Clock,
  ChevronRight,
  X,
  FileCode,
  FileCheck,
  HardDrive
} from 'lucide-react';
import { StorageFile, StorageChunk, SearchResult } from '../../types';
import {
  fetchIndexedFiles,
  searchFiles,
  uploadFile,
  deleteStorageFile,
  reindexStorageFile,
  fetchFileChunks
} from '../../api';
import { useToast } from '../ui/Toast';

export const FilesTab: React.FC = () => {
  const [files, setFiles] = useState<StorageFile[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [filterText, setFilterText] = useState<string>('');

  // Semantic File Search state
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);

  // Selected file for viewing chunks in modal
  const [selectedFileForChunks, setSelectedFileForChunks] = useState<StorageFile | null>(null);
  const [fileChunks, setFileChunks] = useState<StorageChunk[]>([]);
  const [isLoadingChunks, setIsLoadingChunks] = useState<boolean>(false);

  // Re-indexing state tracking
  const [reindexingKeys, setReindexingKeys] = useState<Record<string, boolean>>({});

  const { toast } = useToast();

  const loadFiles = async () => {
    setIsLoading(true);
    const res = await fetchIndexedFiles(100);
    if (res && res.files) {
      setFiles(res.files);
    }
    setIsLoading(false);
  };

  useEffect(() => {
    loadFiles();
  }, []);

  // Handle direct file search
  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setIsSearching(true);
    const results = await searchFiles(searchQuery.trim(), 10);
    setSearchResults(results || []);
    setIsSearching(false);
  };

  // Handle direct file upload
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;

    setIsUploading(true);
    let successCount = 0;

    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i];
      toast(`Uploading ${file.name}...`, 'info');
      const res = await uploadFile(file, 'files');
      if (res.success) {
        successCount++;
      } else {
        toast(`Upload failed for ${file.name}: ${res.error || 'Unknown error'}`, 'error');
      }
    }

    setIsUploading(false);
    e.target.value = '';

    if (successCount > 0) {
      toast(`Uploaded ${successCount} file(s). Vector indexing queued in background.`, 'success');
      setTimeout(loadFiles, 1500);
    }
  };

  // Handle file deletion
  const handleDelete = async (file: StorageFile) => {
    if (!window.confirm(`Delete ${file.filename} from Cloudflare R2 and remove all vector chunks?`)) {
      return;
    }
    const ok = await deleteStorageFile(file.key);
    if (ok) {
      toast(`Deleted ${file.filename}`, 'success');
      loadFiles();
    } else {
      toast(`Failed to delete ${file.filename}`, 'error');
    }
  };

  // Handle manual re-indexing
  const handleReindex = async (file: StorageFile) => {
    setReindexingKeys(prev => ({ ...prev, [file.key]: true }));
    toast(`Re-indexing ${file.filename}...`, 'info');
    const ok = await reindexStorageFile(file.key);
    if (ok) {
      toast(`Re-indexing queued for ${file.filename}`, 'success');
      setTimeout(async () => {
        await loadFiles();
        setReindexingKeys(prev => ({ ...prev, [file.key]: false }));
      }, 2500);
    } else {
      toast(`Could not trigger re-indexing for ${file.filename}`, 'error');
      setReindexingKeys(prev => ({ ...prev, [file.key]: false }));
    }
  };

  // Open chunks inspection modal
  const handleOpenChunksModal = async (file: StorageFile) => {
    setSelectedFileForChunks(file);
    setIsLoadingChunks(true);
    const res = await fetchFileChunks(file.key);
    if (res && res.chunks) {
      setFileChunks(res.chunks);
    } else {
      setFileChunks([]);
    }
    setIsLoadingChunks(false);
  };

  // Filtered files list
  const filteredFiles = files.filter(f =>
    f.filename.toLowerCase().includes(filterText.toLowerCase()) ||
    f.key.toLowerCase().includes(filterText.toLowerCase()) ||
    (f.mime_type && f.mime_type.toLowerCase().includes(filterText.toLowerCase()))
  );

  // Storage Stats Summary
  const totalChunksCount = files.reduce((acc, f) => acc + (f.total_chunks || 0), 0);
  const totalExtractedLength = files.reduce((acc, f) => acc + (f.extracted_text_length || 0), 0);

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* HEADER & ACTIONS */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#141414] border border-[#262626] p-5 rounded-none">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-[#22c55e]/10 border border-[#22c55e]/30 flex items-center justify-center text-[#22c55e]">
              <HardDrive className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white tracking-tight">R2 Object Storage & Vectorized Files</h2>
              <p className="text-xs text-[#8a8f9e]">
                Direct semantic search, chunk inspection, and zero-egress document management.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={loadFiles}
            disabled={isLoading}
            className="px-3 py-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-[#c1c5d0] hover:text-white border border-[#333333] transition-colors flex items-center gap-1.5 font-mono text-[11px]"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>

          <label className="px-3.5 py-1.5 bg-[#ff6b00] hover:bg-[#e05e00] text-white font-medium border border-[#ff6b00] transition-colors flex items-center gap-1.5 cursor-pointer font-sans text-xs shadow-sm shadow-[#ff6b00]/20">
            <Upload className="w-3.5 h-3.5" />
            <span>{isUploading ? 'Uploading...' : 'Upload & Vectorize Document'}</span>
            <input
              type="file"
              multiple
              className="hidden"
              onChange={handleFileUpload}
              disabled={isUploading}
            />
          </label>
        </div>
      </div>

      {/* METRICS ROW */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[#141414] border border-[#262626] p-4 rounded-none">
          <div className="flex items-center justify-between text-[#8a8f9e] mb-1">
            <span className="font-mono text-[11px] uppercase tracking-wider">Total Documents</span>
            <FileText className="w-4 h-4 text-[#ff6b00]" />
          </div>
          <div className="text-xl font-bold text-white font-mono">{files.length}</div>
          <p className="text-[11px] text-[#8a8f9e] mt-1">Stored in Cloudflare R2 bucket</p>
        </div>

        <div className="bg-[#141414] border border-[#262626] p-4 rounded-none">
          <div className="flex items-center justify-between text-[#8a8f9e] mb-1">
            <span className="font-mono text-[11px] uppercase tracking-wider">Vector Chunks in Neon</span>
            <Layers className="w-4 h-4 text-[#22c55e]" />
          </div>
          <div className="text-xl font-bold text-white font-mono">{totalChunksCount}</div>
          <p className="text-[11px] text-[#8a8f9e] mt-1">pgvector HNSW 768-dim embeddings</p>
        </div>

        <div className="bg-[#141414] border border-[#262626] p-4 rounded-none">
          <div className="flex items-center justify-between text-[#8a8f9e] mb-1">
            <span className="font-mono text-[11px] uppercase tracking-wider">Extracted Text</span>
            <FileCode className="w-4 h-4 text-[#00f2fe]" />
          </div>
          <div className="text-xl font-bold text-white font-mono">
            {(totalExtractedLength / 1000).toFixed(1)}k <span className="text-xs text-[#8a8f9e] font-normal">chars</span>
          </div>
          <p className="text-[11px] text-[#8a8f9e] mt-1">Parsed PDFs, Markdown, and Code</p>
        </div>
      </div>

      {/* SEMANTIC SEARCH INSIDE FILES ONLY */}
      <div className="bg-[#141414] border border-[#262626] p-5 rounded-none space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-xs font-semibold text-white uppercase tracking-wider font-mono flex items-center gap-2">
              <Search className="w-3.5 h-3.5 text-[#ff6b00]" />
              Direct File Semantic Search
            </h3>
            <p className="text-[11px] text-[#8a8f9e]">
              Search specifically inside all uploaded PDF pages, markdown documents, and code files.
            </p>
          </div>
        </div>

        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-[#8a8f9e] absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search concepts inside PDF papers, algorithms, or code files (e.g. QAOA 128 qubits, transmon fidelity)..."
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-2.5 pl-10 text-white placeholder-[#8a8f9e] outline-none font-sans text-xs"
            />
          </div>
          <button
            type="submit"
            disabled={isSearching}
            className="px-4 py-2 bg-[#ff6b00] hover:bg-[#e05e00] text-white font-medium transition-colors flex items-center gap-1.5 font-sans text-xs"
          >
            {isSearching ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
            <span>Search Files</span>
          </button>
          {searchResults !== null && (
            <button
              type="button"
              onClick={() => { setSearchResults(null); setSearchQuery(''); }}
              className="px-3 py-2 bg-[#1f1f1f] hover:bg-[#282828] text-[#8a8f9e] hover:text-white border border-[#333333] transition-colors"
            >
              Clear
            </button>
          )}
        </form>

        {/* SEARCH RESULTS PREVIEW */}
        {searchResults !== null && (
          <div className="mt-4 space-y-3 pt-3 border-t border-[#262626]">
            <div className="text-[11px] font-mono text-[#8a8f9e] flex items-center justify-between">
              <span>Found {searchResults.length} matching document chunk(s)</span>
            </div>

            {searchResults.length === 0 ? (
              <div className="p-4 text-center text-[#8a8f9e] bg-[#0f0f0f] border border-[#262626]">
                No matching file chunks found. Try uploading relevant documents or rephrasing your search query.
              </div>
            ) : (
              <div className="space-y-2.5 max-h-[360px] overflow-y-auto pr-1">
                {searchResults.map((res, idx) => (
                  <div key={idx} className="bg-[#0f0f0f] border border-[#262626] hover:border-[#333333] p-3.5 transition-colors space-y-2">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 bg-[#22c55e]/10 text-[#22c55e] border border-[#22c55e]/30 text-[10px] font-mono font-semibold flex items-center gap-1">
                          <FileText className="w-3 h-3" />
                          {res.citation || res.filename || 'File'}
                        </span>
                        <span className="text-[10px] font-mono text-[#8a8f9e]">
                          Score: {(res.score * 100).toFixed(1)}%
                        </span>
                      </div>

                      {res.url && (
                        <a
                          href={res.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[11px] text-[#ff6b00] hover:underline flex items-center gap-1 font-mono"
                        >
                          <ExternalLink className="w-3 h-3" />
                          <span>Open File</span>
                        </a>
                      )}
                    </div>

                    <p className="text-white text-xs leading-relaxed font-sans whitespace-pre-wrap bg-[#141414] p-2.5 border border-[#1f1f1f]">
                      {res.content}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* VECTORIZED FILES DATA TABLE */}
      <div className="bg-[#141414] border border-[#262626] rounded-none overflow-hidden">
        {/* FILTER BAR */}
        <div className="p-4 border-b border-[#262626] bg-[#161616] flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-white uppercase text-[11px] font-mono">Indexed Files Repository</span>
            <span className="px-1.5 py-0.5 bg-[#262626] text-[#8a8f9e] font-mono text-[10px]">
              {filteredFiles.length} file(s)
            </span>
          </div>

          <div className="relative w-full md:w-72">
            <Search className="w-3.5 h-3.5 text-[#8a8f9e] absolute left-3 top-2.5" />
            <input
              type="text"
              value={filterText}
              onChange={e => setFilterText(e.target.value)}
              placeholder="Filter by filename or MIME..."
              className="w-full bg-[#0f0f0f] border border-[#262626] focus:border-[#ff6b00] p-1.5 pl-8 text-white placeholder-[#8a8f9e] outline-none font-sans text-xs"
            />
          </div>
        </div>

        {/* TABLE CONTENT */}
        {isLoading ? (
          <div className="p-12 text-center text-[#8a8f9e] space-y-2">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto text-[#ff6b00]" />
            <p>Loading files from Cloudflare R2 and Neon pgvector...</p>
          </div>
        ) : filteredFiles.length === 0 ? (
          <div className="p-12 text-center text-[#8a8f9e] space-y-3">
            <HardDrive className="w-8 h-8 mx-auto text-[#444444]" />
            <p className="text-white font-medium">No files uploaded yet</p>
            <p className="text-xs max-w-md mx-auto">
              Upload PDF research papers, Markdown notes, or code repositories to enable direct semantic vector retrieval.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[#262626] bg-[#111111] text-[#8a8f9e] font-mono text-[11px] uppercase">
                  <th className="p-3 pl-4">Filename</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Vector Chunks</th>
                  <th className="p-3">Extracted Text</th>
                  <th className="p-3">Upload Date</th>
                  <th className="p-3 text-right pr-4">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#202020]">
                {filteredFiles.map((file) => {
                  const isReindexing = reindexingKeys[file.key];
                  return (
                    <tr key={file.id || file.key} className="hover:bg-[#181818] transition-colors">
                      <td className="p-3 pl-4">
                        <div className="flex items-center gap-2.5">
                          <FileText className="w-4 h-4 text-[#ff6b00] flex-shrink-0" />
                          <div>
                            <div className="font-medium text-white tracking-tight">{file.filename}</div>
                            <div className="text-[10px] font-mono text-[#8a8f9e] truncate max-w-xs">{file.key}</div>
                          </div>
                        </div>
                      </td>

                      <td className="p-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono font-semibold rounded-none ${
                          file.indexing_status === 'completed'
                            ? 'bg-[#22c55e]/10 text-[#22c55e] border border-[#22c55e]/30'
                            : file.indexing_status === 'pending'
                            ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30 animate-pulse'
                            : 'bg-[#262626] text-[#8a8f9e] border border-[#333333]'
                        }`}>
                          {file.indexing_status === 'completed' ? (
                            <CheckCircle2 className="w-3 h-3" />
                          ) : (
                            <Clock className="w-3 h-3" />
                          )}
                          {file.indexing_status || 'completed'}
                        </span>
                      </td>

                      <td className="p-3">
                        <span className="font-mono text-[#c1c5d0] bg-[#1f1f1f] px-2 py-0.5 border border-[#2a2a2a]">
                          {file.total_chunks || 0} chunks
                        </span>
                      </td>

                      <td className="p-3 font-mono text-[#8a8f9e]">
                        {file.extracted_text_length ? `${(file.extracted_text_length / 1000).toFixed(1)}k chars` : '—'}
                      </td>

                      <td className="p-3 font-mono text-[#8a8f9e] text-[11px]">
                        {file.created_at ? new Date(file.created_at).toLocaleDateString() : '—'}
                      </td>

                      <td className="p-3 text-right pr-4">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => handleOpenChunksModal(file)}
                            className="p-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-[#c1c5d0] hover:text-white border border-[#333333] transition-colors"
                            title="Inspect Semantic Chunks"
                          >
                            <Layers className="w-3.5 h-3.5" />
                          </button>

                          {file.url && (
                            <a
                              href={file.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="p-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-[#c1c5d0] hover:text-[#ff6b00] border border-[#333333] transition-colors inline-flex items-center"
                              title="Download / Open in R2"
                            >
                              <ExternalLink className="w-3.5 h-3.5" />
                            </a>
                          )}

                          <button
                            onClick={() => handleReindex(file)}
                            disabled={isReindexing}
                            className="p-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-[#c1c5d0] hover:text-[#22c55e] border border-[#333333] transition-colors"
                            title="Re-Index Vectors"
                          >
                            <RefreshCw className={`w-3.5 h-3.5 ${isReindexing ? 'animate-spin text-[#22c55e]' : ''}`} />
                          </button>

                          <button
                            onClick={() => handleDelete(file)}
                            className="p-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-[#c1c5d0] hover:text-red-400 border border-[#333333] transition-colors"
                            title="Delete File from R2"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* CHUNKS INSPECTION MODAL */}
      {selectedFileForChunks && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#141414] border border-[#262626] w-full max-w-3xl max-h-[85vh] flex flex-col rounded-none shadow-2xl">
            {/* MODAL HEADER */}
            <div className="p-4 border-b border-[#262626] flex items-center justify-between bg-[#161616]">
              <div className="flex items-center gap-2.5">
                <FileText className="w-4 h-4 text-[#ff6b00]" />
                <div>
                  <h3 className="text-sm font-semibold text-white">{selectedFileForChunks.filename}</h3>
                  <p className="text-[11px] font-mono text-[#8a8f9e]">
                    {fileChunks.length} Semantic Vector Chunks Extracted in Neon
                  </p>
                </div>
              </div>
              <button
                onClick={() => setSelectedFileForChunks(null)}
                className="p-1 text-[#8a8f9e] hover:text-white hover:bg-[#222222] transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* MODAL BODY */}
            <div className="p-4 overflow-y-auto flex-1 space-y-3">
              {isLoadingChunks ? (
                <div className="p-8 text-center text-[#8a8f9e]">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto text-[#ff6b00] mb-2" />
                  <span>Loading semantic chunks...</span>
                </div>
              ) : fileChunks.length === 0 ? (
                <div className="p-8 text-center text-[#8a8f9e]">
                  No vector chunks found for this file. It may be a non-text binary or still undergoing indexing.
                </div>
              ) : (
                fileChunks.map((chunk, idx) => (
                  <div key={chunk.id || idx} className="bg-[#0f0f0f] border border-[#262626] p-3.5 space-y-2">
                    <div className="flex items-center justify-between text-[11px] font-mono">
                      <span className="px-2 py-0.5 bg-[#262626] text-[#c1c5d0] border border-[#333333]">
                        Chunk {chunk.chunk_index + 1} of {chunk.total_chunks}
                        {chunk.page_number !== undefined && chunk.page_number !== null ? ` (Page ${chunk.page_number})` : ''}
                      </span>
                      <span className="text-[#8a8f9e]">{chunk.content.length} chars</span>
                    </div>
                    <p className="text-white text-xs leading-relaxed font-sans whitespace-pre-wrap bg-[#141414] p-2.5 border border-[#1f1f1f]">
                      {chunk.content}
                    </p>
                  </div>
                ))
              )}
            </div>

            {/* MODAL FOOTER */}
            <div className="p-3 border-t border-[#262626] bg-[#111111] flex justify-end">
              <button
                onClick={() => setSelectedFileForChunks(null)}
                className="px-4 py-1.5 bg-[#1f1f1f] hover:bg-[#282828] text-white border border-[#333333] transition-colors font-sans text-xs"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
