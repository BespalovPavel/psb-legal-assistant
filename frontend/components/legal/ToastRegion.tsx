"use client";

import React, { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { AlertCircle, CheckCircle2, X } from "lucide-react";

export interface ToastItem {
  id: string;
  tone: "error" | "info";
  message: string;
}

interface ToastCardProps {
  toast: ToastItem;
  suppressed: boolean;
  onDismiss: (id: string) => void;
}

function ToastCard({ toast, suppressed, onDismiss }: ToastCardProps) {
  const prefersReducedMotion = useReducedMotion();
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (suppressed || paused) {
      return;
    }

    const duration = toast.tone === "error" ? 6500 : 3800;
    const timer = window.setTimeout(() => {
      onDismiss(toast.id);
    }, duration);

    return () => window.clearTimeout(timer);
  }, [toast.id, toast.tone, suppressed, paused, onDismiss]);

  const isError = toast.tone === "error";

  return (
    <motion.div
      layout
      initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.96 }}
      transition={{ duration: 0.18 }}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
          setPaused(false);
        }
      }}
      className={`pointer-events-auto flex items-start gap-2.5 rounded-lg border px-3.5 py-2.5 shadow-[0_8px_24px_rgba(0,0,0,0.45)] max-w-sm w-full ${
        isError
          ? "bg-[#252525] border-psb-orange/35 text-fg"
          : "bg-[#252525] border-white/[0.09] text-fg"
      }`}
    >
      <span
        aria-hidden="true"
        className={`mt-0.5 shrink-0 ${
          isError ? "text-psb-orange" : "text-mute"
        }`}
      >
        {isError ? (
          <AlertCircle className="size-4" />
        ) : (
          <CheckCircle2 className="size-4" />
        )}
      </span>
      <p className="flex-1 text-[13.5px] leading-snug text-fg break-words">
        {toast.message}
      </p>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Закрыть уведомление"
        className="shrink-0 inline-flex items-center justify-center min-w-7 min-h-7 rounded-md text-mute hover:text-fg hover:bg-white/[0.06] transition-colors cursor-pointer"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </motion.div>
  );
}

interface ToastRegionProps {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
  suppressed: boolean;
}

export function ToastRegion({
  toasts,
  onDismiss,
  suppressed,
}: ToastRegionProps) {
  const latestError = suppressed
    ? ""
    : [...toasts].reverse().find((t) => t.tone === "error")?.message ?? "";
  const latestInfo = suppressed
    ? ""
    : [...toasts].reverse().find((t) => t.tone === "info")?.message ?? "";

  return (
    <div
      role="region"
      aria-label="Уведомления"
      className="pointer-events-none fixed bottom-24 right-4 sm:right-6 z-40 flex flex-col items-end gap-2.5 w-[calc(100vw-2rem)] sm:w-auto"
    >
      <div className="sr-only" aria-live="assertive" aria-atomic="true">
        {latestError}
      </div>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {latestInfo}
      </div>

      {!suppressed && (
        <AnimatePresence initial={false}>
          {toasts.map((toast) => (
            <ToastCard
              key={toast.id}
              toast={toast}
              suppressed={suppressed}
              onDismiss={onDismiss}
            />
          ))}
        </AnimatePresence>
      )}
    </div>
  );
}
