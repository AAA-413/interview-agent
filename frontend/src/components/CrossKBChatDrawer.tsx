import { useCallback, useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import {
  X,
  Plus,
  Send,
  Loader2,
  MessageSquare,
  ChevronDown,
  ChevronUp,
  Trash2,
} from 'lucide-react';
import { knowledgeBaseApi } from '../api/knowledgeBase';
import type { RagChatListItemDTO, RagReferenceDTO } from '../types/knowledgeBase';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  references?: RagReferenceDTO[];
  timestamp: string;
}

interface SessionGroup {
  session_id: string;
  question: string;
  created_at: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function CrossKBChatDrawer({ open, onClose }: Props) {
  const [sessions, setSessions] = useState<SessionGroup[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [streamedContent, setStreamedContent] = useState('');
  const [streamedRefs, setStreamedRefs] = useState<RagReferenceDTO[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true);
    try {
      const chats = await knowledgeBaseApi.listCrossKBChats();
      const grouped: SessionGroup[] = [];
      const seen = new Set<string>();
      for (const chat of chats) {
        if (!seen.has(chat.session_id)) {
          seen.add(chat.session_id);
          grouped.push({
            session_id: chat.session_id,
            question: chat.question,
            created_at: chat.created_at,
          });
        }
      }
      setSessions(grouped);
    } catch {
      // silent
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  const loadSessionHistory = useCallback(async (sessionId: string) => {
    setLoadingHistory(true);
    setMessages([]);
    try {
      const chats = await knowledgeBaseApi.getCrossKBSessionHistory(sessionId);
      const msgs: Message[] = [];
      for (const chat of chats) {
        msgs.push({ role: 'user', content: chat.question, timestamp: chat.created_at });
        if (chat.answer) {
          msgs.push({
            role: 'assistant',
            content: chat.answer,
            references: chat.references,
            timestamp: chat.created_at,
          });
        }
      }
      setMessages(msgs);
    } catch {
      // silent
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void loadSessions();
      setCurrentSessionId(null);
      setMessages([]);
      setStreamedContent('');
      setStreamedRefs([]);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open, loadSessions]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamedContent, scrollToBottom]);

  useEffect(() => {
    if (open && !streaming) {
      inputRef.current?.focus();
    }
  }, [open, streaming]);

  const handleNewChat = () => {
    setCurrentSessionId(null);
    setMessages([]);
    setStreamedContent('');
    setStreamedRefs([]);
    inputRef.current?.focus();
  };

  const handleSelectSession = (sessionId: string) => {
    setCurrentSessionId(sessionId);
    setStreamedContent('');
    setStreamedRefs([]);
    void loadSessionHistory(sessionId);
  };

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await knowledgeBaseApi.deleteCrossKBSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }
    } catch {
      // silent
    }
  };

  const handleSend = async () => {
    const q = input.trim();
    if (!q || streaming) return;

    setInput('');
    const userMsg: Message = { role: 'user', content: q, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setStreaming(true);
    setStreamedContent('');
    setStreamedRefs([]);

    try {
      await knowledgeBaseApi.streamCrossKBAnswer(
        { question: q, session_id: currentSessionId, top_k: 4 },
        {
          onMeta: (data) => {
            if (typeof data.session_id === 'string') {
              setCurrentSessionId(data.session_id);
            }
          },
          onChunk: (chunk) => {
            setStreamedContent((prev) => prev + chunk);
          },
          onReferences: (refs) => {
            setStreamedRefs(refs as RagReferenceDTO[]);
          },
          onDone: (data) => {
            const finalAnswer = typeof data.answer === 'string' ? data.answer : '';
            const finalRefs = Array.isArray(data.references)
              ? (data.references as RagReferenceDTO[])
              : streamedRefs;
            const assistantMsg: Message = {
              role: 'assistant',
              content: finalAnswer,
              references: finalRefs,
              timestamp: new Date().toISOString(),
            };
            setMessages((prev) => [...prev, assistantMsg]);
            setStreamedContent('');
            setStreamedRefs([]);
            void loadSessions();
          },
        },
      );
    } catch (err) {
      const errMsg: Message = {
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : '提问失败'}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errMsg]);
      setStreamedContent('');
      setStreamedRefs([]);
    } finally {
      setStreaming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      <div className="relative w-full max-w-5xl bg-white shadow-2xl flex flex-col animate-slide-in-right">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-5 h-5 text-emerald-500" />
            <h2 className="text-lg font-semibold text-slate-900">跨知识库问答</h2>
            <span className="text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">搜索所有知识库</span>
          </div>
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex flex-1 min-h-0">
          {/* Left sidebar - session list */}
          <div className="w-64 border-r border-slate-200 flex flex-col bg-slate-50">
            <div className="p-3">
              <button
                onClick={handleNewChat}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-emerald-500 text-white rounded-xl hover:bg-emerald-600 text-sm"
              >
                <Plus className="w-4 h-4" /> 新建对话
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1">
              {loadingSessions ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 text-slate-400 animate-spin" />
                </div>
              ) : sessions.length === 0 ? (
                <p className="text-xs text-slate-400 text-center py-8">暂无历史会话</p>
              ) : (
                sessions.map((s) => (
                  <div
                    key={s.session_id}
                    className={`group relative w-full text-left px-3 py-2.5 rounded-xl text-sm transition-colors cursor-pointer ${
                      currentSessionId === s.session_id
                        ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                        : 'text-slate-600 hover:bg-slate-100'
                    }`}
                    onClick={() => handleSelectSession(s.session_id)}
                  >
                    <p className="line-clamp-2 font-medium pr-6">{s.question}</p>
                    <p className="text-xs text-slate-400 mt-1">{new Date(s.created_at).toLocaleString()}</p>
                    <button
                      onClick={(e) => void handleDeleteSession(s.session_id, e)}
                      className="absolute top-2 right-2 p-1 text-slate-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                      title="删除会话"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Right - chat area */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
              {loadingHistory ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
                </div>
              ) : messages.length === 0 && !streamedContent ? (
                <div className="flex flex-col items-center justify-center py-12 text-slate-400">
                  <MessageSquare className="w-12 h-12 mb-3" />
                  <p className="text-sm">输入问题，将从所有知识库中检索回答</p>
                </div>
              ) : (
                <>
                  {messages.map((msg, i) => (
                    <ChatMessage key={i} message={msg} />
                  ))}
                  {streamedContent && (
                    <ChatMessage
                      message={{
                        role: 'assistant',
                        content: streamedContent,
                        references: streamedRefs,
                        timestamp: new Date().toISOString(),
                      }}
                      isStreaming
                    />
                  )}
                </>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input area */}
            <div className="border-t border-slate-200 px-6 py-4">
              <div className="flex gap-3 items-end">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入问题... (Enter 发送, Shift+Enter 换行)"
                  rows={1}
                  disabled={streaming}
                  className="flex-1 px-4 py-3 rounded-xl border border-slate-200 outline-none focus:border-emerald-400 resize-none disabled:bg-slate-50 text-sm"
                  style={{ maxHeight: '120px' }}
                />
                <button
                  onClick={() => void handleSend()}
                  disabled={!input.trim() || streaming}
                  className="flex items-center justify-center w-11 h-11 bg-emerald-500 text-white rounded-xl hover:bg-emerald-600 disabled:bg-slate-300 disabled:cursor-not-allowed flex-shrink-0"
                >
                  {streaming ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ChatMessage({ message, isStreaming = false }: { message: Message; isStreaming?: boolean }) {
  const [showRefs, setShowRefs] = useState(false);
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] ${isUser ? 'order-2' : ''}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-7 ${
            isUser
              ? 'bg-emerald-500 text-white'
              : 'bg-slate-100 text-slate-800'
          }`}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm max-w-none text-slate-800 [&_pre]:bg-slate-800 [&_pre]:text-slate-100 [&_pre]:rounded-lg [&_pre]:p-3 [&_code]:text-sm">
              <Markdown rehypePlugins={[rehypeHighlight]}>{message.content}</Markdown>
              {isStreaming && <span className="inline-block w-2 h-4 bg-slate-400 animate-pulse ml-0.5" />}
            </div>
          )}
        </div>

        {/* References toggle */}
        {!isUser && message.references && message.references.length > 0 && (
          <div className="mt-2">
            <button
              onClick={() => setShowRefs(!showRefs)}
              className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600"
            >
              {showRefs ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {message.references.length} 个参考片段
            </button>
            {showRefs && (
              <div className="mt-2 space-y-2">
                {message.references.map((ref, idx) => (
                  <div key={`${ref.chunk_id}-${ref.chunk_index}`} className="rounded-lg border border-slate-200 p-3 bg-white text-xs">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-emerald-600">
                        [{idx + 1}] {ref.source_name && <span className="text-slate-500">{ref.source_name}</span>}
                        {ref.source_name && ref.title ? ' / ' : ''}
                        {ref.title || ''}
                      </span>
                      <span className="text-slate-400">{(ref.score * 100).toFixed(1)}%</span>
                    </div>
                    <p className="text-slate-600 leading-5 line-clamp-3">{ref.content_preview}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {!isUser && !isStreaming && (
          <p className="text-xs text-slate-300 mt-1">{new Date(message.timestamp).toLocaleTimeString()}</p>
        )}
      </div>
    </div>
  );
}
