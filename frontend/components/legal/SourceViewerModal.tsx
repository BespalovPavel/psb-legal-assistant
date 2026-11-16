"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  RotateCcw,
  X,
} from "lucide-react";
import {
  ApiError,
  getChunk,
  getDocument,
  getErrorMessage,
  isAbortError,
} from "@/lib/legal-api";
import {
  formatDocTypeLabel,
  formatLegalDateRu,
  getDocStatusMeta,
  getDocumentFullText,
  isSyntheticWholeChunk,
  sanitizeSourceText,
} from "@/lib/legal-format";
import type { ChunkWithDoc, DocumentDetail } from "@/types/legal";

export interface SourceModalTarget {
  chunkId?: string | null;
  docId?: string | null;
  returnToKb?: boolean;
}

type ViewerState =
  | { mode: "chunk"; chunkId: string; docId?: string | null }
  | { mode: "document"; docId: string; lastChunkId?: string | null };

function isPointOutsideDialog(
  clientX: number,
  clientY: number,
  dialog: HTMLDialogElement,
): boolean {
  const rect = dialog.getBoundingClientRect();
  return (
    clientX < rect.left ||
    clientX > rect.right ||
    clientY < rect.top ||
    clientY > rect.bottom
  );
}

function StatusBadge({ status }: { status: string | null | undefined }) {
  const meta = getDocStatusMeta(status);
  const dotColor =
    meta.tone === "active"
      ? "bg-emerald-400/80"
      : meta.tone === "expired"
        ? "bg-psb-orange"
        : "bg-faint";
  const textColor = meta.tone === "expired" ? "text-[#e5844e]" : "text-mute";

  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[12px] font-medium ${textColor}`}
    >
      <span
        aria-hidden="true"
        className={`size-1.5 rounded-full ${dotColor}`}
      />
      <span>{meta.label}</span>
    </span>
  );
}

interface SourceViewerModalProps {
  target: SourceModalTarget | null;
  onClose: () => void;
  onBackToKb: () => void;
}

export function SourceViewerModal({
  target,
  onClose,
  onBackToKb,
}: SourceViewerModalProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const pressedOutsideRef = useRef(false);
  const titleId = useId();

  const [viewer, setViewer] = useState<ViewerState | null>(null);
  const [chunkData, setChunkData] = useState<ChunkWithDoc | null>(null);
  const [docData, setDocData] = useState<DocumentDetail | null>(null);
  const [docTab, setDocTab] = useState<"text" | "chunks">("text");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  const open = target !== null;
  const openRef = useRef(open);
  openRef.current = open;
  const suppressCloseEventRef = useRef(false);
  const targetChunkId = target?.chunkId ?? null;
  const targetDocId = target?.docId ?? null;

  // Synchronize initial view state when modal opens with a new target
  useEffect(() => {
    if (!open) {
      setViewer(null);
      setChunkData(null);
      setDocData(null);
      setError(null);
      setLoading(false);
      return;
    }

    setDocTab("text");
    setError(null);

    if (targetChunkId && !isSyntheticWholeChunk(targetChunkId)) {
      setViewer({
        mode: "chunk",
        chunkId: targetChunkId,
        docId: targetDocId,
      });
    } else if (targetDocId) {
      setViewer({
        mode: "document",
        docId: targetDocId,
      });
    } else {
      setViewer(null);
      setError("Не указан идентификатор фрагмента или документа.");
    }
  }, [open, targetChunkId, targetDocId]);

  // Open/close native <dialog> declaratively via showModal()
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      suppressCloseEventRef.current = false;
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
    } else if (!open && dialog.open) {
      suppressCloseEventRef.current = true;
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        suppressCloseEventRef.current = false;
        dialog.removeAttribute("open");
      }
    }
  }, [open]);

  const viewerMode = viewer?.mode ?? null;
  const viewerChunkId = viewer?.mode === "chunk" ? viewer.chunkId : null;
  const viewerDocId = viewer?.docId ?? null;

  // Load chunk or full document whenever viewer state or retry changes
  useEffect(() => {
    if (!open || !viewerMode) return;

    const controller = new AbortController();
    let active = true;
    let switchedToFallback = false;

    async function load() {
      setLoading(true);
      setError(null);

      try {
        if (viewerMode === "chunk" && viewerChunkId) {
          const data = await getChunk(viewerChunkId, controller.signal);
          if (!active) return;
          setChunkData(data);
          setDocData(null);
        } else if (viewerMode === "document" && viewerDocId) {
          const data = await getDocument(viewerDocId, controller.signal);
          if (!active) return;
          setDocData(data);
        }
      } catch (err) {
        if (!active || isAbortError(err)) return;

        if (
          viewerMode === "chunk" &&
          err instanceof ApiError &&
          err.status === 404 &&
          viewerDocId
        ) {
          switchedToFallback = true;
          setViewer({ mode: "document", docId: viewerDocId });
          return;
        }

        setError(getErrorMessage(err, "Не удалось загрузить источник."));
      } finally {
        if (active && !switchedToFallback) {
          setLoading(false);
        }
      }
    }

    load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [open, viewerMode, viewerChunkId, viewerDocId, retryNonce]);

  const handleDialogClose = () => {
    if (dialogRef.current) {
      dialogRef.current.returnValue = "";
    }
    if (suppressCloseEventRef.current || !openRef.current) {
      suppressCloseEventRef.current = false;
      return;
    }
    onClose();
  };

  const isChunkMode = viewer?.mode === "chunk";
  const currentChunk = chunkData?.chunk ?? null;
  const currentChunkDoc = chunkData?.document ?? null;
  const effectiveDocId =
    currentChunk?.doc_id ??
    currentChunkDoc?.doc_id ??
    (viewer?.mode === "chunk" ? viewer.docId : viewer?.docId) ??
    null;

  const modalTitle = isChunkMode
    ? sanitizeSourceText(currentChunkDoc?.title) || "Просмотр фрагмента"
    : sanitizeSourceText(docData?.document.title) || "Просмотр документа";

  const breadcrumbPath = isChunkMode
    ? sanitizeSourceText(currentChunk?.path) || "Фрагмент"
    : "Полный текст";

  const fullDocumentText = docData ? getDocumentFullText(docData) : "";

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby={titleId}
      onClose={handleDialogClose}
      onPointerDown={(e) => {
        if (
          !("closedBy" in HTMLDialogElement.prototype) &&
          e.currentTarget === dialogRef.current
        ) {
          pressedOutsideRef.current = isPointOutsideDialog(
            e.clientX,
            e.clientY,
            e.currentTarget,
          );
        }
      }}
      onPointerCancel={() => {
        pressedOutsideRef.current = false;
      }}
      onClick={(e) => {
        if (
          !("closedBy" in HTMLDialogElement.prototype) &&
          e.currentTarget === dialogRef.current
        ) {
          const wasOutside = pressedOutsideRef.current;
          pressedOutsideRef.current = false;
          if (
            wasOutside &&
            isPointOutsideDialog(e.clientX, e.clientY, e.currentTarget)
          ) {
            e.currentTarget.close();
          }
        }
      }}
      className="m-auto p-0 border-0 rounded-xl bg-transparent text-fg w-[min(48rem,calc(100vw-1.5rem))] max-h-[84dvh] shadow-2xl overflow-hidden"
    >
      <div className="flex flex-col max-h-[84dvh] w-full rounded-xl border border-white/[0.08] bg-raise shadow-[0_24px_64px_rgba(0,0,0,0.65)]">
        {/* Modal Header */}
        <header className="shrink-0 flex items-start justify-between gap-4 px-5 py-4 border-b border-white/[0.07]">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5 mb-1.5">
              {target?.returnToKb && (
                <button
                  type="button"
                  onClick={onBackToKb}
                  className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 -ml-2 text-xs font-medium text-mute hover:bg-white/[0.06] hover:text-fg transition-colors cursor-pointer"
                >
                  <ArrowLeft className="size-3.5" aria-hidden="true" />
                  <span>База знаний</span>
                </button>
              )}

              {!isChunkMode &&
                viewer?.mode === "document" &&
                viewer.lastChunkId && (
                  <button
                    type="button"
                    onClick={() =>
                      setViewer({
                        mode: "chunk",
                        chunkId: viewer.lastChunkId!,
                        docId: viewer.docId,
                      })
                    }
                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-mute hover:bg-white/[0.06] hover:text-fg transition-colors cursor-pointer"
                  >
                    <ArrowLeft className="size-3.5" aria-hidden="true" />
                    <span>К фрагменту</span>
                  </button>
                )}

              {isChunkMode && currentChunkDoc && (
                <StatusBadge
                  status={currentChunk?.status ?? currentChunkDoc.status}
                />
              )}
              {!isChunkMode && docData && (
                <StatusBadge status={docData.document.status} />
              )}
            </div>

            <h2
              id={titleId}
              className="text-base sm:text-[17px] font-semibold tracking-[-0.01em] text-fg leading-snug break-words"
            >
              {modalTitle}
            </h2>

            <p className="mt-1 text-xs text-mute break-words">
              {modalTitle} / {breadcrumbPath}
            </p>
          </div>

          <button
            type="button"
            autoFocus
            onClick={() => dialogRef.current?.close()}
            aria-label="Закрыть окно просмотра источника"
            className="shrink-0 inline-flex items-center justify-center size-7 rounded-md text-mute hover:bg-white/[0.06] hover:text-fg transition-colors cursor-pointer"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </header>

        {/* Modal Body */}
        <div className="flex-1 min-h-0 overflow-y-auto psb-scrollbar px-5 py-5 space-y-4">
          {loading ? (
            <div
              role="status"
              aria-live="polite"
              className="flex flex-col gap-2.5 py-10 items-center justify-center text-mute"
            >
              <Loader2
                className="size-4 animate-spin text-mute"
                aria-hidden="true"
              />
              <p className="text-xs">Загрузка материала из базы знаний...</p>
            </div>
          ) : error ? (
            <div className="rounded-lg border border-psb-orange/30 bg-raise-2 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start gap-2.5">
                <AlertTriangle
                  className="size-4 shrink-0 text-psb-orange mt-0.5"
                  aria-hidden="true"
                />
                <div>
                  <p className="text-sm font-medium text-fg">
                    Ошибка загрузки
                  </p>
                  <p className="text-xs text-mute mt-0.5">{error}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setRetryNonce((n) => n + 1)}
                className="shrink-0 inline-flex items-center gap-1.5 min-h-8 rounded-md border border-white/[0.1] bg-white/[0.05] px-3 py-1 text-xs font-medium text-fg hover:bg-white/[0.1] transition-colors cursor-pointer"
              >
                <RotateCcw className="size-3.5" aria-hidden="true" />
                <span>Повторить</span>
              </button>
            </div>
          ) : isChunkMode && currentChunk ? (
            <div className="space-y-3.5">
              {currentChunk.section && (
                <p className="text-xs font-medium text-mute">
                  Раздел: {currentChunk.section}
                </p>
              )}

              <div className="rounded-lg border border-white/[0.06] bg-ink p-4 sm:p-5">
                <p className="text-[14.5px] leading-[1.75] whitespace-pre-wrap break-words font-[inherit] text-fg/95">
                  {currentChunk.text}
                </p>
              </div>

              {currentChunk.note && (
                <div className="rounded-lg border border-white/[0.08] bg-raise-2 px-4 py-3 text-xs leading-relaxed text-fg/90 whitespace-pre-wrap break-words font-[inherit]">
                  <span className="font-semibold text-fg block mb-1">
                    Примечание редакции
                  </span>
                  {currentChunk.note}
                </div>
              )}
            </div>
          ) : !isChunkMode && docData ? (
            <div className="space-y-4">
              {/* Notion-style key/value metadata strip */}
              <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-mute pb-1">
                {docData.document.doc_type && (
                  <span>
                    <span className="text-faint">Тип:</span>{" "}
                    {formatDocTypeLabel(docData.document.doc_type)}
                  </span>
                )}
                {docData.document.number && (
                  <span>
                    <span className="text-faint">№</span> {docData.document.number}
                  </span>
                )}
                {docData.document.valid_from && (
                  <span>
                    <span className="text-faint">Действует с:</span>{" "}
                    {formatLegalDateRu(docData.document.valid_from)}
                  </span>
                )}
                {docData.document.valid_to && (
                  <span className="text-[#e5844e]">
                    Утратил силу с: {formatLegalDateRu(docData.document.valid_to)}
                  </span>
                )}
                {Array.isArray(docData.document.parties) &&
                  docData.document.parties.length > 0 && (
                    <span>
                      <span className="text-faint">Стороны:</span>{" "}
                      {docData.document.parties.join(", ")}
                    </span>
                  )}
              </div>

              {/* Notion underline tabs: Full text vs Chunks */}
              <div
                role="tablist"
                aria-label="Режим просмотра документа"
                className="flex items-center gap-5 border-b border-white/[0.07]"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={docTab === "text"}
                  onClick={() => setDocTab("text")}
                  className={`pb-2 text-[13px] font-medium border-b-2 -mb-px transition-colors cursor-pointer ${
                    docTab === "text"
                      ? "border-psb-orange text-fg"
                      : "border-transparent text-mute hover:text-fg"
                  }`}
                >
                  Текст документа
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={docTab === "chunks"}
                  onClick={() => setDocTab("chunks")}
                  className={`pb-2 text-[13px] font-medium border-b-2 -mb-px transition-colors cursor-pointer ${
                    docTab === "chunks"
                      ? "border-psb-orange text-fg"
                      : "border-transparent text-mute hover:text-fg"
                  }`}
                >
                  Фрагменты ({docData.chunks.length})
                </button>
              </div>

              {docTab === "text" ? (
                <div className="rounded-lg border border-white/[0.06] bg-ink p-4 sm:p-5">
                  <p className="text-[14.5px] leading-[1.75] whitespace-pre-wrap break-words font-[inherit] text-fg/95">
                    {fullDocumentText || "Текст документа отсутствует."}
                  </p>
                </div>
              ) : docData.chunks.length === 0 ? (
                <p className="text-sm text-mute py-4">
                  Фрагменты для этого документа не выделены.
                </p>
              ) : (
                <ul className="divide-y divide-white/[0.05]">
                  {docData.chunks.map((ch) => (
                    <li key={ch.chunk_id}>
                      <button
                        type="button"
                        onClick={() =>
                          setViewer({
                            mode: "chunk",
                            chunkId: ch.chunk_id,
                            docId: docData.document.doc_id,
                          })
                        }
                        className="group w-full text-left rounded-md hover:bg-white/[0.04] px-3 py-2.5 transition-colors cursor-pointer"
                      >
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <span className="text-xs font-medium text-fg group-hover:underline underline-offset-4 decoration-white/25">
                            {sanitizeSourceText(ch.path) ||
                              `Фрагмент #${ch.ord + 1}`}
                          </span>
                          <span className="text-[11px] text-faint opacity-0 group-hover:opacity-100 transition-opacity">
                            Открыть →
                          </span>
                        </div>
                        <p className="text-xs text-mute line-clamp-3 whitespace-pre-wrap break-words font-[inherit]">
                          {ch.text}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </div>

        {/* Modal Footer for Chunk Navigation */}
        {isChunkMode && (
          <footer className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-5 py-3 border-t border-white/[0.07]">
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={!currentChunk?.prev_id || loading}
                onClick={() => {
                  if (currentChunk?.prev_id) {
                    setViewer({
                      mode: "chunk",
                      chunkId: currentChunk.prev_id,
                      docId: effectiveDocId,
                    });
                  }
                }}
                className="inline-flex items-center gap-1 min-h-8 rounded-md px-2.5 py-1 text-xs font-medium text-mute hover:bg-white/[0.06] hover:text-fg transition-colors disabled:opacity-35 disabled:cursor-not-allowed cursor-pointer"
              >
                <ChevronLeft className="size-3.5" aria-hidden="true" />
                <span>Предыдущий фрагмент</span>
              </button>

              <button
                type="button"
                disabled={!currentChunk?.next_id || loading}
                onClick={() => {
                  if (currentChunk?.next_id) {
                    setViewer({
                      mode: "chunk",
                      chunkId: currentChunk.next_id,
                      docId: effectiveDocId,
                    });
                  }
                }}
                className="inline-flex items-center gap-1 min-h-8 rounded-md px-2.5 py-1 text-xs font-medium text-mute hover:bg-white/[0.06] hover:text-fg transition-colors disabled:opacity-35 disabled:cursor-not-allowed cursor-pointer"
              >
                <span>Следующий фрагмент</span>
                <ChevronRight className="size-3.5" aria-hidden="true" />
              </button>
            </div>

            <button
              type="button"
              disabled={!effectiveDocId || loading}
              onClick={() => {
                if (effectiveDocId) {
                  setViewer({
                    mode: "document",
                    docId: effectiveDocId,
                    lastChunkId: currentChunk?.chunk_id ?? null,
                  });
                }
              }}
              className="inline-flex items-center gap-1.5 min-h-8 rounded-md border border-white/[0.1] bg-raise-2 hover:bg-[#2e2e2e] px-3 py-1 text-xs font-medium text-fg transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              <FileText className="size-3.5 text-mute" aria-hidden="true" />
              <span>Открыть документ целиком</span>
            </button>
          </footer>
        )}
      </div>
    </dialog>
  );
}
