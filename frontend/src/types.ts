export type SourceAgent = 'claude' | 'gpt' | 'gemini' | 'user' | 'system' | 'cursor' | 'windsurf' | string;

export interface MemoryAttachment {
  key: string;
  filename: string;
  mime_type?: string;
  size_bytes?: number;
  url?: string;
  created_at?: string;
}

export interface Memory {
  id: string;
  content: string;
  category: string;
  source_agent: SourceAgent;
  media_type?: string;
  media_url?: string;
  attachments?: MemoryAttachment[];
  tags: string[];
  created_at: string;
  last_accessed?: string;
}

export interface ProfileRule {
  id: string;
  key: string;
  value: string;
  category: string;
  source_agent: SourceAgent;
  updated_at: string;
}

export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface Conversation {
  id: string;
  platform: string;
  title: string;
  summary: string;
  source_agent: SourceAgent;
  messages: ConversationMessage[];
  created_at: string;
}

export interface SearchResult {
  id: string;
  source: 'memory' | 'profile';
  content: string;
  category: string;
  source_agent: SourceAgent;
  score: number;
  vector_score?: number;
  rerank_score?: number;
  tags?: string[];
  attachments?: MemoryAttachment[];
}

export interface Stats {
  total_memories: number;
  total_profile_rules: number;
  total_chat_logs: number;
  total_task_sessions: number;
  source_distribution: Record<string, number>;
}
