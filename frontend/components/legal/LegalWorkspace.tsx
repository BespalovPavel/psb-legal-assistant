"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Download,
  Menu as MenuIcon,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ApiError,
  createChat,
  deleteChat,
  getChat,
  getErrorMessage,
  isAbortError,
  listChats,
  listDocuments,
  sendMessage,
} from "@/lib/legal-api";
import {
  deriveChatTitle,
  isSyntheticWholeChunk,
} from "@/lib/legal-format";
import type {
  ChatListItem,
  MessageSource,
  UiChatMessage,
} from "@/types/legal";
import { Composer } from "./Composer";
import { KnowledgeBaseModal } from "./KnowledgeBaseModal";
import { MessageThread } from "./MessageThread";
import {
  SourceViewerModal,
  type SourceModalTarget,
} from "./SourceViewerModal";
import { ToastRegion, type ToastItem } from "./ToastRegion";

type ActiveModal =
  | null
  | { type: "kb" }
  | {
      type: "source";
      chunkId?: string | null;
      docId?: string | null;
      returnToKb?: boolean;
    };

function isPointOutsideDialog(
  clientX: number,
  clientY: number,
  dialog: HTMLDialogElement,
): boolean {
  if (clientX === 0 && clientY === 0) return false;
  const rect = dialog.getBoundingClientRect();
  return (
    clientX < rect.left ||
    clientX > rect.right ||
    clientY < rect.top ||
    clientY > rect.bottom
  );
}

export function LegalWorkspace() {
  const prefersReducedMotion = Boolean(useReducedMotion());

  const [chats, setChats] = useState<ChatListItem[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [, setDocCount] = useState<number | null>(null);

  const [isLoadingChats, setIsLoadingChats] = useState(true);
  const [isLoadingChat, setIsLoadingChat] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [deletingChatId, setDeletingChatId] = useState<string | null>(null);

  const [showHistory, setShowHistory] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeModal, setActiveModal] = useState<ActiveModal>(null);
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const activeChatIdRef = useRef<string | null>(null);
  const chatLoadAbortRef = useRef<AbortController | null>(null);
  const chatLoadSeqRef = useRef(0);
  const sendAbortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const menuPanelRef = useRef<HTMLDivElement | null>(null);
  const menuBtnRef = useRef<HTMLButtonElement | null>(null);

  const mobileDialogRef = useRef<HTMLDialogElement | null>(null);
  const mobilePressedOutsideRef = useRef(false);
  const mobileOpenRef = useRef(mobileDrawerOpen);
  mobileOpenRef.current = mobileDrawerOpen;
  const suppressMobileCloseRef = useRef(false);

  const addToast = useCallback((tone: "error" | "info", message: string) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((prev) => [...prev.slice(-3), { id, tone, message }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Load chats and documents on mount
  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    async function init() {
      setIsLoadingChats(true);
      const [chatsRes, docsRes] = await Promise.allSettled([
        listChats(controller.signal),
        listDocuments(controller.signal),
      ]);

      if (!active) return;

      if (chatsRes.status === "fulfilled") {
        setChats(chatsRes.value);
      } else if (!isAbortError(chatsRes.reason)) {
        addToast(
          "error",
          getErrorMessage(
            chatsRes.reason,
            "Не удалось загрузить историю диалогов.",
          ),
        );
      }

      if (docsRes.status === "fulfilled") {
        setDocCount(docsRes.value.length);
      }

      setIsLoadingChats(false);
    }

    init();

    return () => {
      active = false;
      controller.abort();
      chatLoadAbortRef.current?.abort();
      sendAbortRef.current?.abort();
    };
  }, [addToast]);

  // Close top-right menu on outside click or Escape
  useEffect(() => {
    if (!menuOpen) return;
    const handlePointerDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        menuPanelRef.current &&
        !menuPanelRef.current.contains(target) &&
        !menuBtnRef.current?.contains(target)
      ) {
        setMenuOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKey);
    };
  }, [menuOpen]);

  // Mobile native <dialog> lifecycle
  useEffect(() => {
    const dialog = mobileDialogRef.current;
    if (!dialog) return;

    if (mobileDrawerOpen && !dialog.open) {
      suppressMobileCloseRef.current = false;
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
    } else if (!mobileDrawerOpen && dialog.open) {
      suppressMobileCloseRef.current = true;
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        suppressMobileCloseRef.current = false;
        dialog.removeAttribute("open");
      }
    }
  }, [mobileDrawerOpen]);

  const handleMobileClose = () => {
    if (mobileDialogRef.current) {
      mobileDialogRef.current.returnValue = "";
    }
    if (suppressMobileCloseRef.current || !mobileOpenRef.current) {
      suppressMobileCloseRef.current = false;
      return;
    }
    setMobileDrawerOpen(false);
  };

  // Scroll smoothly when messages update
  useEffect(() => {
    if (typeof bottomRef.current?.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({
        behavior: prefersReducedMotion ? "auto" : "smooth",
        block: "end",
      });
    }
  }, [messages.length, isSending, isLoadingChat, prefersReducedMotion]);

  const handleSelectChat = useCallback(
    async (chatId: string) => {
      if (isSending) return;
      setMobileDrawerOpen(false);

      if (activeChatIdRef.current === chatId && messages.length > 0) {
        return;
      }

      chatLoadAbortRef.current?.abort();
      const seq = ++chatLoadSeqRef.current;
      const controller = new AbortController();
      chatLoadAbortRef.current = controller;

      activeChatIdRef.current = chatId;
      setActiveChatId(chatId);
      setIsLoadingChat(true);

      try {
        const detail = await getChat(chatId, controller.signal);
        if (
          chatLoadSeqRef.current !== seq ||
          activeChatIdRef.current !== chatId
        ) {
          return;
        }
        setMessages(detail.messages);
      } catch (err) {
        if (isAbortError(err) || chatLoadSeqRef.current !== seq) {
          return;
        }
        addToast(
          "error",
          getErrorMessage(err, "Не удалось загрузить диалог."),
        );

        if (err instanceof ApiError && err.status === 404) {
          activeChatIdRef.current = null;
          setActiveChatId(null);
          setMessages([]);
          listChats()
            .then(setChats)
            .catch(() => {});
        }
      } finally {
        if (chatLoadSeqRef.current === seq) {
          setIsLoadingChat(false);
        }
      }
    },
    [addToast, isSending, messages.length],
  );

  const handleNewChat = useCallback(() => {
    if (isSending) return;
    chatLoadAbortRef.current?.abort();
    chatLoadSeqRef.current += 1;
    activeChatIdRef.current = null;
    setActiveChatId(null);
    setMessages([]);
    setIsLoadingChat(false);
    setMobileDrawerOpen(false);
    setMenuOpen(false);
  }, [isSending]);

  const handleDeleteChat = useCallback(
    async (chatId: string) => {
      if (isSending || deletingChatId) return;
      setDeletingChatId(chatId);

      try {
        await deleteChat(chatId);
        setChats((prev) => prev.filter((c) => c.chat_id !== chatId));

        if (activeChatIdRef.current === chatId) {
          chatLoadAbortRef.current?.abort();
          chatLoadSeqRef.current += 1;
          activeChatIdRef.current = null;
          setActiveChatId(null);
          setMessages([]);
          setIsLoadingChat(false);
        }

        addToast("info", "Диалог удалён.");
      } catch (err) {
        if (!isAbortError(err)) {
          addToast(
            "error",
            getErrorMessage(err, "Не удалось удалить диалог."),
          );
        }
      } finally {
        setDeletingChatId(null);
      }
    },
    [addToast, deletingChatId, isSending],
  );

  const handleSendMessage = useCallback(async () => {
    const question = inputValue.trim();
    if (!question || isSending || isLoadingChat) {
      return;
    }

    setInputValue(question);
    setIsSending(true);

    const pendingKey = `pending-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const optimisticUserMessage: UiChatMessage = {
      id: -Date.now(),
      role: "user",
      content: question,
      created_at: new Date().toISOString(),
      sources: [],
      pending: true,
      localKey: pendingKey,
    };

    setMessages((prev) => [...prev, optimisticUserMessage]);

    const sendController = new AbortController();
    sendAbortRef.current = sendController;

    let targetChatId = activeChatIdRef.current;

    if (!targetChatId) {
      try {
        const derivedTitle = deriveChatTitle(question);
        const created = await createChat(derivedTitle, sendController.signal);
        targetChatId = created.chat_id;
        activeChatIdRef.current = created.chat_id;
        setActiveChatId(created.chat_id);

        const optimisticChatItem: ChatListItem = {
          chat_id: created.chat_id,
          title: created.title,
          updated_at: new Date().toISOString(),
          last_message: null,
        };
        setChats((prev) => [
          optimisticChatItem,
          ...prev.filter((c) => c.chat_id !== created.chat_id),
        ]);
      } catch (err) {
        setMessages((prev) => prev.filter((m) => m.localKey !== pendingKey));
        setInputValue(question);
        setIsSending(false);
        if (!isAbortError(err)) {
          addToast(
            "error",
            getErrorMessage(err, "Не удалось создать новый диалог."),
          );
        }
        return;
      }
    }

    try {
      const res = await sendMessage(
        targetChatId,
        question,
        sendController.signal,
      );
      const nowIso = new Date().toISOString();

      const confirmedUserMsg: UiChatMessage = {
        id: res.user_message_id,
        role: "user",
        content: question,
        created_at: nowIso,
        sources: [],
      };
      const assistantMsg: UiChatMessage = {
        id: res.assistant_message_id,
        role: "assistant",
        content: res.answer,
        created_at: nowIso,
        sources: res.sources ?? [],
      };

      setMessages((prev) => [
        ...prev.filter((m) => m.localKey !== pendingKey),
        confirmedUserMsg,
        assistantMsg,
      ]);
      setInputValue("");

      listChats()
        .then(setChats)
        .catch(() => {});
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.localKey !== pendingKey));
      setInputValue(question);

      if (err instanceof ApiError && err.status === 404) {
        activeChatIdRef.current = null;
        setActiveChatId(null);
        listChats()
          .then(setChats)
          .catch(() => {});
      }

      if (!isAbortError(err)) {
        addToast(
          "error",
          getErrorMessage(
            err,
            "Не удалось получить ответ от ассистента. Попробуйте отправить вопрос повторно.",
          ),
        );
      }
    } finally {
      setIsSending(false);
      if (sendAbortRef.current === sendController) {
        sendAbortRef.current = null;
      }
    }
  }, [addToast, inputValue, isLoadingChat, isSending]);

  const handleOpenSource = useCallback((source: MessageSource) => {
    if (!source.chunk_id && !source.doc_id) {
      return;
    }

    if (isSyntheticWholeChunk(source.chunk_id) && source.doc_id) {
      setActiveModal({
        type: "source",
        docId: source.doc_id,
        chunkId: null,
      });
      return;
    }

    setActiveModal({
      type: "source",
      chunkId: source.chunk_id,
      docId: source.doc_id,
    });
  }, []);

  const exportCurrentChat = () => {
    setMenuOpen(false);
    try {
      const payload = JSON.stringify(messages, null, 2);
      const blob = new Blob([payload], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const date = new Date().toISOString().split("T")[0];
      link.download = `psb-legal-chat-${date}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      addToast("error", "Не удалось экспортировать диалог.");
    }
  };

  const sourceModalTarget = useMemo<SourceModalTarget | null>(
    () =>
      activeModal?.type === "source"
        ? {
            chunkId: activeModal.chunkId,
            docId: activeModal.docId,
            returnToKb: activeModal.returnToKb,
          }
        : null,
    [activeModal],
  );

  const hasMessages =
    messages.length > 0 || isSending || isLoadingChat;

  const renderChatListItems = () => {
    if (isLoadingChats) {
      return (
        <div className="space-y-1.5 py-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-9 rounded-lg bg-white/[0.04] animate-pulse"
            />
          ))}
        </div>
      );
    }

    if (chats.length === 0) {
      return (
        <p className="text-xs text-faint py-3">История диалогов пуста</p>
      );
    }

    return (
      <ul className="space-y-0.5 overflow-y-auto psb-scrollbar pr-1 flex-1 min-h-0">
        {chats.map((chat) => {
          const isActive = activeChatId === chat.chat_id;
          const isDeleting = deletingChatId === chat.chat_id;
          return (
            <li key={chat.chat_id}>
              <div
                className={cn(
                  "group/item w-full flex items-center justify-between rounded-md transition-colors text-[13.5px]",
                  isActive
                    ? "bg-white/[0.08] text-fg font-medium"
                    : "text-mute hover:bg-white/[0.04] hover:text-fg",
                )}
              >
                <button
                  type="button"
                  disabled={isSending}
                  onClick={() => void handleSelectChat(chat.chat_id)}
                  className="flex-1 min-w-0 flex items-center gap-2 px-2.5 py-1.5 text-left cursor-pointer disabled:opacity-50"
                >
                  <span className="truncate">{chat.title || "Новый чат"}</span>
                </button>
                <button
                  type="button"
                  disabled={isSending || isDeleting}
                  aria-label={`Удалить чат ${chat.title || "Новый чат"}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleDeleteChat(chat.chat_id);
                  }}
                  className="text-faint hover:text-fg opacity-0 group-hover/item:opacity-100 focus:opacity-100 p-1.5 shrink-0 transition-opacity cursor-pointer disabled:opacity-30"
                >
                  <Trash2 className="size-3.5" aria-hidden="true" />
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <div className="min-h-dvh w-full bg-ink psb-backdrop text-fg flex flex-col relative">
      {/* Desktop Left Hover Edge & Slide-Over History Sidebar */}
      <div
        className="hidden md:block fixed left-0 top-0 h-full z-40"
        style={{ width: showHistory ? 256 : 16 }}
        onMouseEnter={() => setShowHistory(true)}
        onMouseLeave={() => setShowHistory(false)}
      >
        <button
          type="button"
          onClick={() => setShowHistory((prev) => !prev)}
          aria-label={
            showHistory ? "Скрыть историю чатов" : "Открыть историю чатов"
          }
          aria-expanded={showHistory}
          className={cn(
            "flex fixed top-4 z-40 size-8 rounded-md items-center justify-center text-mute hover:text-fg hover:bg-white/[0.06] transition-[left,color,background-color] duration-200 cursor-pointer",
            showHistory ? "left-[264px]" : "left-4",
          )}
        >
          {showHistory ? (
            <ChevronLeft className="size-4" aria-hidden="true" />
          ) : (
            <ChevronRight className="size-4" aria-hidden="true" />
          )}
        </button>

        <AnimatePresence>
          {showHistory && (
            <motion.aside
              aria-label="История чатов"
              initial={prefersReducedMotion ? { opacity: 0 } : { x: -260 }}
              animate={prefersReducedMotion ? { opacity: 1 } : { x: 0 }}
              exit={prefersReducedMotion ? { opacity: 0 } : { x: -260 }}
              transition={{ type: "tween", duration: 0.18 }}
              className="flex flex-col fixed left-0 top-0 h-full w-64 border-r border-white/[0.06] bg-raise p-3"
            >
              <div className="flex items-center justify-between mb-2 px-1 py-1 shrink-0">
                <h2 className="text-[11px] font-medium uppercase tracking-[0.06em] text-faint">
                  Чаты
                </h2>
                <button
                  type="button"
                  disabled={isSending}
                  onClick={handleNewChat}
                  className="text-xs font-medium rounded-md hover:bg-white/[0.06] px-2 py-1 text-mute hover:text-fg transition-colors cursor-pointer disabled:opacity-50"
                >
                  Новый чат
                </button>
              </div>
              {renderChatListItems()}
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {/* Mobile Top-Left Drawer Trigger */}
      <button
        type="button"
        onClick={() => setMobileDrawerOpen(true)}
        aria-label="Открыть историю чатов"
        className="md:hidden fixed top-4 left-4 z-50 size-8 rounded-md flex items-center justify-center text-mute hover:text-fg hover:bg-white/[0.06] transition-colors cursor-pointer"
      >
        <ChevronRight className="size-4" aria-hidden="true" />
      </button>

      {/* Top-Right Flat Notion Menu */}
      <button
        ref={menuBtnRef}
        type="button"
        onClick={() => setMenuOpen((prev) => !prev)}
        aria-label="Меню"
        aria-expanded={menuOpen}
        className="fixed top-4 right-4 z-50 size-8 rounded-md flex items-center justify-center text-mute hover:text-fg hover:bg-white/[0.06] cursor-pointer transition-colors"
      >
        {menuOpen ? (
          <X className="size-4" aria-hidden="true" />
        ) : (
          <MenuIcon className="size-4" aria-hidden="true" />
        )}
      </button>

      <AnimatePresence>
        {menuOpen && (
          <motion.div
            ref={menuPanelRef}
            initial={
              prefersReducedMotion
                ? { opacity: 0 }
                : { opacity: 0, scale: 0.97, y: -4 }
            }
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={
              prefersReducedMotion
                ? { opacity: 0 }
                : { opacity: 0, scale: 0.97, y: -4 }
            }
            transition={{ duration: 0.14 }}
            className="fixed top-14 right-4 z-50 w-48 rounded-lg border border-white/[0.08] bg-[#252525] p-1 flex flex-col gap-0.5 shadow-[0_8px_24px_rgba(0,0,0,0.45)]"
          >
            <button
              type="button"
              onClick={handleNewChat}
              disabled={isSending}
              className="flex items-center gap-2.5 w-full px-2.5 py-1.5 text-[13px] rounded-md hover:bg-white/[0.06] text-fg/90 transition-colors cursor-pointer disabled:opacity-50"
            >
              <Plus className="size-4 text-mute" aria-hidden="true" />
              <span>Новый чат</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setActiveModal({ type: "kb" });
              }}
              className="flex items-center gap-2.5 w-full px-2.5 py-1.5 text-[13px] rounded-md hover:bg-white/[0.06] text-fg/90 transition-colors cursor-pointer"
            >
              <BookOpen className="size-4 text-mute" aria-hidden="true" />
              <span>База знаний</span>
            </button>
            {messages.length > 0 && (
              <button
                type="button"
                onClick={exportCurrentChat}
                className="flex items-center gap-2.5 w-full px-2.5 py-1.5 text-[13px] rounded-md hover:bg-white/[0.06] text-mute hover:text-fg transition-colors cursor-pointer"
              >
                <Download className="size-4 text-mute" aria-hidden="true" />
                <span>Экспорт чата</span>
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main Layout */}
      <div
        className={
          !hasMessages
            ? "flex-1 flex flex-col w-full justify-center py-16"
            : "flex-1 flex flex-col w-full"
        }
      >
        <main
          className={
            !hasMessages
              ? "w-full max-w-[44rem] mx-auto px-4 sm:px-6 flex flex-col items-center"
              : "flex-1 w-full max-w-[44rem] mx-auto px-4 sm:px-6 pt-16 pb-6"
          }
        >
          {!hasMessages ? (
            <motion.div
              initial={prefersReducedMotion ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, ease: "easeOut" }}
              className="w-full flex flex-col items-center"
            >
              <h1 className="text-[26px] sm:text-[32px] font-semibold tracking-[-0.02em] text-fg text-center">
                Чем помочь сегодня?
              </h1>
              <p className="mt-2 text-[14px] text-mute text-center">
                Задайте юридический вопрос по договорам или законам РФ
              </p>
            </motion.div>
          ) : (
            <>
              <MessageThread
                messages={messages}
                isLoadingChat={isLoadingChat}
                isSending={isSending}
                reducedMotion={prefersReducedMotion}
                onOpenSource={handleOpenSource}
              />
              <div ref={bottomRef} className="h-2" />
            </>
          )}
        </main>

        <footer
          className={
            hasMessages
              ? "sticky bottom-0 z-20 w-full bg-gradient-to-t from-ink via-ink/95 to-transparent pt-5 pb-5 px-4 sm:px-6"
              : "w-full mt-7 px-4 sm:px-6"
          }
        >
          <div className="max-w-[44rem] mx-auto">
            <Composer
              ref={textareaRef}
              value={inputValue}
              onChange={setInputValue}
              onSubmit={() => void handleSendMessage()}
              disabled={isSending || isLoadingChat}
              isSending={isSending}
            />
          </div>
        </footer>
      </div>

      {/* Mobile Slide-Over Native <dialog> Drawer */}
      <dialog
        ref={mobileDialogRef}
        closedby="any"
        aria-label="История чатов"
        onClose={handleMobileClose}
        onPointerDown={(e) => {
          if (
            !("closedBy" in HTMLDialogElement.prototype) &&
            e.currentTarget === mobileDialogRef.current
          ) {
            mobilePressedOutsideRef.current = isPointOutsideDialog(
              e.clientX,
              e.clientY,
              e.currentTarget,
            );
          }
        }}
        onPointerCancel={() => {
          mobilePressedOutsideRef.current = false;
        }}
        onClick={(e) => {
          if (
            !("closedBy" in HTMLDialogElement.prototype) &&
            e.currentTarget === mobileDialogRef.current
          ) {
            const wasOutside = mobilePressedOutsideRef.current;
            mobilePressedOutsideRef.current = false;
            if (
              wasOutside &&
              isPointOutsideDialog(e.clientX, e.clientY, e.currentTarget)
            ) {
              e.currentTarget.close();
            }
          }
        }}
        className="md:hidden m-0 mr-auto h-dvh max-h-dvh w-[min(18rem,85vw)] p-0 border-0 border-r border-white/[0.06] bg-raise text-fg shadow-2xl overflow-hidden"
      >
        <div className="h-full flex flex-col p-3">
          <div className="flex items-center justify-between mb-2 px-1 py-1 shrink-0">
            <h2 className="text-[11px] font-medium uppercase tracking-[0.06em] text-faint">
              Чаты
            </h2>
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={isSending}
                onClick={handleNewChat}
                className="text-xs font-medium rounded-md hover:bg-white/[0.06] px-2 py-1 text-mute hover:text-fg cursor-pointer"
              >
                Новый чат
              </button>
              <button
                type="button"
                autoFocus
                onClick={() => mobileDialogRef.current?.close()}
                aria-label="Закрыть чаты"
                className="p-1.5 rounded-md text-mute hover:text-fg hover:bg-white/[0.06] cursor-pointer"
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </div>
          </div>
          {renderChatListItems()}
        </div>
      </dialog>

      {/* Non-Stacking Native Modals */}
      <KnowledgeBaseModal
        open={activeModal?.type === "kb"}
        onClose={() => setActiveModal(null)}
        onDocumentsLoaded={setDocCount}
        onSelectDocument={(docId) =>
          setActiveModal({
            type: "source",
            docId,
            chunkId: null,
            returnToKb: true,
          })
        }
      />

      <SourceViewerModal
        target={sourceModalTarget}
        onClose={() => setActiveModal(null)}
        onBackToKb={() => setActiveModal({ type: "kb" })}
      />

      <ToastRegion
        toasts={toasts}
        onDismiss={dismissToast}
        suppressed={activeModal !== null}
      />
    </div>
  );
}
