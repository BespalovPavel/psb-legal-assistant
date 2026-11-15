export interface ChatListItem {
  chat_id: string;
  title: string;
  updated_at: string;
  last_message: string | null;
}

export interface ChatCreated {
  chat_id: string;
  title: string;
}

export interface MessageSource {
  doc_id: string | null;
  chunk_id: string | null;
  doc_title: string | null;
  path: string | null;
  snippet: string | null;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
  sources: MessageSource[];
}

export interface UiChatMessage extends ChatMessage {
  pending?: boolean;
  localKey?: string;
}

export interface ChatDetail {
  chat_id: string;
  title: string;
  messages: ChatMessage[];
}

export interface DeleteChatResponse {
  status: string;
}

export interface SendMessageResponse {
  user_message_id: number;
  assistant_message_id: number;
  answer: string;
  sources: MessageSource[];
}

export interface DocumentListItem {
  doc_id: string;
  title: string;
  doc_type: string | null;
  status: string | null;
  valid_from: string | null;
  valid_to: string | null;
  n_chunks: number;
}

export interface ChunkSummary {
  chunk_id: string;
  ord: number;
  path: string | null;
  text: string;
  is_heading: boolean;
}

export interface DocumentRecord {
  doc_id: string;
  file: string;
  title: string;
  kind?: string | null;
  doc_type?: string | null;
  status?: string | null;
  doc_date?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  number?: string | null;
  related_ref?: string | null;
  parties?: string[] | null;
  extra?: Record<string, unknown> | null;
  raw_text: string | null;
  content_hash?: string;
  n_chunks?: number;
  created_at?: string;
}

export interface DocumentDetail {
  document: DocumentRecord;
  chunks: ChunkSummary[];
}

export interface ChunkDetail {
  chunk_id: string;
  doc_id: string;
  ord: number;
  path: string | null;
  section: string | null;
  text: string;
  note: string | null;
  is_heading: boolean;
  status?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  prev_id: string | null;
  next_id: string | null;
}

export interface ChunkWithDoc {
  chunk: ChunkDetail;
  document: DocumentRecord | null;
}
