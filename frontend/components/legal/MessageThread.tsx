"use client";

import React from "react";
import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { formatSourceChipLabel } from "@/lib/legal-format";
import type { MessageSource, UiChatMessage } from "@/types/legal";
import { cn } from "@/lib/utils";

function AssistantMark() {
  return (
    <div className="mb-2 flex items-center gap-2 text-[12.5px] font-medium text-mute select-none">
      <span
        aria-hidden="true"
        className="size-1.5 rounded-[2px] bg-psb-orange"
      />
      <span>Ассистент ПСБ</span>
    </div>
  );
}

function SourceList({
  sources,
  keyPrefix,
  onOpenSource,
}: {
  sources: MessageSource[];
  keyPrefix: string;
  onOpenSource: (source: MessageSource) => void;
}) {
  return (
    <div className="mt-4 pt-3 border-t border-white/[0.07]">
      <p className="mb-1 text-[11.5px] font-medium text-faint">
        Источники
      </p>
      <ol className="space-y-0.5">
        {sources.map((src, i) => {
          const formatted = formatSourceChipLabel(src);
          const sepIndex = formatted.indexOf(" • ");
          const title = sepIndex >= 0 ? formatted.slice(0, sepIndex) : formatted;
          const path = sepIndex >= 0 ? formatted.slice(sepIndex + 3) : "";
          const navigable = Boolean(src.chunk_id || src.doc_id);

          return (
            <li key={`${keyPrefix}-src-${src.chunk_id ?? src.doc_id ?? i}-${i}`}>
              <button
                type="button"
                disabled={!navigable}
                onClick={() => onOpenSource(src)}
                aria-label={formatted}
                className="group/src -mx-2 flex w-[calc(100%+1rem)] items-baseline gap-2.5 rounded-md px-2 py-1 text-left text-[13.5px] text-mute transition-colors enabled:cursor-pointer enabled:hover:bg-white/[0.04] enabled:hover:text-fg disabled:opacity-50"
              >
                <span className="w-3.5 shrink-0 text-[12px] tabular-nums text-faint group-hover/src:text-psb-orange transition-colors">
                  {i + 1}.
                </span>
                <span className="min-w-0 flex-1 break-words group-hover/src:underline underline-offset-4 decoration-white/25">
                  {title}
                  {path && <span className="text-faint"> • {path}</span>}
                </span>
                {navigable && (
                  <ArrowUpRight
                    className="size-3.5 shrink-0 self-center text-faint opacity-0 transition-opacity group-hover/src:opacity-100 group-hover/src:text-mute"
                    aria-hidden="true"
                  />
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

interface MessageThreadProps {
  messages: UiChatMessage[];
  isLoadingChat: boolean;
  isSending: boolean;
  reducedMotion: boolean;
  onOpenSource: (source: MessageSource) => void;
}

export function MessageThread({
  messages,
  isLoadingChat,
  isSending,
  reducedMotion,
  onOpenSource,
}: MessageThreadProps) {
  if (isLoadingChat) {
    return (
      <div role="status" aria-live="polite" className="space-y-4 py-6">
        <span className="sr-only">Загрузка диалога...</span>
        <div className="ml-auto h-10 w-1/2 rounded-[20px] bg-white/[0.04] animate-pulse" />
        <div className="h-3 w-5/6 rounded bg-white/[0.04] animate-pulse" />
        <div className="h-3 w-4/6 rounded bg-white/[0.04] animate-pulse" />
        <div className="h-3 w-3/6 rounded bg-white/[0.04] animate-pulse" />
      </div>
    );
  }

  return (
    <div className="space-y-9">
      {messages.map((message, index) => {
        const key = message.localKey ?? `${message.role}-${message.id}-${index}`;

        if (message.role === "user") {
          return (
            <motion.div
              key={key}
              initial={reducedMotion ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className="flex justify-end"
            >
              <p
                className={cn(
                  "max-w-[78%] whitespace-pre-wrap break-words font-[inherit] rounded-xl rounded-br-sm border border-white/[0.07] bg-raise-2 px-3.5 py-2.5 text-[14.5px] leading-6 text-fg",
                  message.pending && "opacity-75",
                )}
              >
                {message.content}
              </p>
            </motion.div>
          );
        }

        return (
          <motion.article
            key={key}
            initial={reducedMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.24 }}
          >
            <AssistantMark />
            <p className="whitespace-pre-wrap break-words font-[inherit] text-[15px] leading-[1.7] text-fg/92">
              {message.content}
            </p>
            {Array.isArray(message.sources) && message.sources.length > 0 && (
              <SourceList
                sources={message.sources}
                keyPrefix={key}
                onOpenSource={onOpenSource}
              />
            )}
          </motion.article>
        );
      })}

      {isSending && (
        <motion.div
          initial={reducedMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <AssistantMark />
          <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 text-[14px] text-mute"
          >
            <span>Поиск ответа в базе знаний...</span>
            <span aria-hidden="true" className="inline-flex items-center gap-1 pt-0.5">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="size-1 rounded-full bg-mute"
                  animate={
                    reducedMotion
                      ? { opacity: 0.7 }
                      : { opacity: [0.25, 1, 0.25] }
                  }
                  transition={{
                    duration: 1.1,
                    repeat: reducedMotion ? 0 : Infinity,
                    delay: i * 0.16,
                    ease: "easeInOut",
                  }}
                />
              ))}
            </span>
          </div>
        </motion.div>
      )}
    </div>
  );
}
