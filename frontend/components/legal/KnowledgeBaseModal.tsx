"use client";

import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  FileText,
  Loader2,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import {
  getErrorMessage,
  isAbortError,
  listDocuments,
} from "@/lib/legal-api";
import {
  formatDocTypeLabel,
  formatLegalDateRu,
  getDocStatusMeta,
} from "@/lib/legal-format";
import type { DocumentListItem } from "@/types/legal";

type KbFilter = "all" | "company" | "law" | "expired";

const FILTER_OPTIONS: { id: KbFilter; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "company", label: "Документы компании" },
  { id: "law", label: "Законы" },
  { id: "expired", label: "Утратили силу" },
];

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

interface KnowledgeBaseModalProps {
  open: boolean;
  onClose: () => void;
  onSelectDocument: (docId: string) => void;
  onDocumentsLoaded?: (count: number) => void;
}

export function KnowledgeBaseModal({
  open,
  onClose,
  onSelectDocument,
  onDocumentsLoaded,
}: KnowledgeBaseModalProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const pressedOutsideRef = useRef(false);
  const openRef = useRef(open);
  openRef.current = open;
  const suppressCloseEventRef = useRef(false);
  const onDocumentsLoadedRef = useRef(onDocumentsLoaded);
  onDocumentsLoadedRef.current = onDocumentsLoaded;
  const titleId = useId();
  const searchInputId = useId();

  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [filter, setFilter] = useState<KbFilter>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

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
      searchInputRef.current?.focus();
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

  useEffect(() => {
    if (!open) return;

    const controller = new AbortController();
    let active = true;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const docs = await listDocuments(controller.signal);
        if (!active) return;
        setDocuments(docs);
        onDocumentsLoadedRef.current?.(docs.length);
      } catch (err) {
        if (!active || isAbortError(err)) return;
        setError(
          getErrorMessage(err, "Не удалось загрузить список документов."),
        );
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [open, retryNonce]);

  const filteredDocuments = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();

    return documents.filter((doc) => {
      if (filter === "company" && doc.doc_type === "law") {
        return false;
      }
      if (filter === "law" && doc.doc_type !== "law") {
        return false;
      }
      if (
        filter === "expired" &&
        getDocStatusMeta(doc.status).tone !== "expired"
      ) {
        return false;
      }

      if (!q) {
        return true;
      }

      return (
        doc.title.toLowerCase().includes(q) ||
        doc.doc_id.toLowerCase().includes(q)
      );
    });
  }, [documents, filter, searchQuery]);

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
        {/* Header */}
        <header className="shrink-0 flex items-start justify-between gap-3 px-5 pt-4 pb-3">
          <div className="min-w-0">
            <h2
              id={titleId}
              className="text-[15px] font-semibold tracking-[-0.01em] text-fg truncate"
            >
              База знаний ПСБ
            </h2>
            <p className="mt-0.5 text-xs text-mute">
              Договоры, внутренние регламенты и нормы законодательства РФ
            </p>
          </div>

          <button
            type="button"
            onClick={() => dialogRef.current?.close()}
            aria-label="Закрыть базу знаний"
            className="shrink-0 inline-flex items-center justify-center size-7 rounded-md text-mute hover:bg-white/[0.06] hover:text-fg transition-colors cursor-pointer"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </header>

        {/* Search & Notion View Tabs */}
        <div className="shrink-0 px-5 border-b border-white/[0.07]">
          <div role="search">
            <label htmlFor={searchInputId} className="sr-only">
              Поиск документов по названию или идентификатору
            </label>
            <div className="relative flex items-center">
              <Search
                className="size-4 text-faint absolute left-3 pointer-events-none"
                aria-hidden="true"
              />
              <input
                ref={searchInputRef}
                id={searchInputId}
                type="search"
                autoFocus
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Поиск по названию или ID..."
                className="w-full min-h-9 rounded-md border border-white/[0.08] bg-ink/80 pl-9 pr-3 py-1.5 text-sm text-fg placeholder:text-faint focus:border-white/[0.2] focus:outline-none"
              />
            </div>
          </div>

          <div className="mt-2.5 flex items-center justify-between gap-3">
            <div
              className="flex items-center gap-4 overflow-x-auto"
              role="group"
              aria-label="Фильтр документов"
            >
              {FILTER_OPTIONS.map((opt) => {
                const isActive = filter === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    aria-pressed={isActive}
                    onClick={() => setFilter(opt.id)}
                    className={`pb-2 text-[13px] font-medium border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                      isActive
                        ? "border-psb-orange text-fg"
                        : "border-transparent text-mute hover:text-fg"
                    }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>

            {!loading && !error && (
              <span className="pb-2 text-xs tabular-nums text-faint shrink-0">
                {filteredDocuments.length} из {documents.length}
              </span>
            )}
          </div>
        </div>

        {/* Document List */}
        <div className="flex-1 min-h-0 overflow-y-auto psb-scrollbar px-2 py-2">
          {loading ? (
            <div
              role="status"
              aria-live="polite"
              className="space-y-1.5 px-3 py-2"
            >
              <div className="flex items-center gap-2 text-xs text-mute mb-2">
                <Loader2
                  className="size-3.5 animate-spin text-mute"
                  aria-hidden="true"
                />
                <span>Загрузка документов базы знаний...</span>
              </div>
              {[0, 1, 2, 3, 4].map((idx) => (
                <div
                  key={idx}
                  className="h-9 rounded-md bg-white/[0.04] animate-pulse"
                />
              ))}
            </div>
          ) : error ? (
            <div className="m-3 rounded-lg border border-psb-orange/30 bg-raise-2 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start gap-2.5">
                <AlertTriangle
                  className="size-4 shrink-0 text-psb-orange mt-0.5"
                  aria-hidden="true"
                />
                <div>
                  <p className="text-sm font-medium text-fg">
                    Не удалось загрузить базу знаний
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
          ) : filteredDocuments.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-sm font-medium text-fg">
                Документы по вашему запросу не найдены
              </p>
              <p className="mt-1 text-xs text-mute">
                Попробуйте изменить поисковый запрос или сбросить фильтр.
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-white/[0.05]">
              {filteredDocuments.map((doc) => {
                const statusMeta = getDocStatusMeta(doc.status);
                const dotColor =
                  statusMeta.tone === "active"
                    ? "bg-emerald-400/80"
                    : statusMeta.tone === "expired"
                      ? "bg-psb-orange"
                      : "bg-faint";
                const statusText =
                  statusMeta.tone === "expired" ? "text-[#e5844e]" : "text-mute";
                const dateLabel = doc.valid_to
                  ? `до ${formatLegalDateRu(doc.valid_to)}`
                  : doc.valid_from
                    ? `с ${formatLegalDateRu(doc.valid_from)}`
                    : "";

                return (
                  <li key={doc.doc_id}>
                    <button
                      type="button"
                      onClick={() => onSelectDocument(doc.doc_id)}
                      className="group w-full text-left flex items-center justify-between gap-4 px-3 py-2.5 rounded-md hover:bg-white/[0.04] transition-colors cursor-pointer"
                    >
                      <div className="flex items-center gap-2.5 min-w-0 flex-1">
                        <FileText
                          className="size-4 shrink-0 text-faint group-hover:text-mute transition-colors"
                          aria-hidden="true"
                        />
                        <span className="text-[13.5px] font-medium text-fg truncate">
                          {doc.title}
                        </span>
                      </div>

                      <div className="flex items-center gap-3.5 shrink-0 text-[12px]">
                        <span className="hidden sm:inline text-faint">
                          {formatDocTypeLabel(doc.doc_type)}
                        </span>
                        {dateLabel && (
                          <span className="hidden md:inline tabular-nums text-faint">
                            {dateLabel}
                          </span>
                        )}
                        <span
                          className={`inline-flex items-center gap-1.5 ${statusText}`}
                        >
                          <span
                            aria-hidden="true"
                            className={`size-1.5 rounded-full ${dotColor}`}
                          />
                          <span>{statusMeta.label}</span>
                        </span>
                        <span className="tabular-nums text-faint w-14 text-right">
                          {doc.n_chunks} фр.
                        </span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </dialog>
  );
}
