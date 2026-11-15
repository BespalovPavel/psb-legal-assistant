"use client";

import React, { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { ArrowUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  isSending: boolean;
}

export const Composer = forwardRef<HTMLTextAreaElement | null, ComposerProps>(
  function Composer({ value, onChange, onSubmit, disabled, isSending }, ref) {
    const textareaRef = useRef<HTMLTextAreaElement | null>(null);
    useImperativeHandle(ref, () => textareaRef.current as HTMLTextAreaElement);

    const canSend = value.trim().length > 0 && !disabled;

    useEffect(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      const nextHeight =
        value.length === 0 ? 36 : Math.min(Math.max(el.scrollHeight, 36), 192);
      el.style.height = `${nextHeight}px`;
    }, [value]);

    return (
      <div className="w-full rounded-xl border border-white/[0.09] bg-raise transition-colors focus-within:border-white/[0.18]">
        <div className="flex items-end gap-2 p-2 pl-4">
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter" || e.shiftKey) return;
              if (e.nativeEvent.isComposing || e.keyCode === 229) return;
              e.preventDefault();
              if (canSend) onSubmit();
            }}
            disabled={disabled}
            aria-label="Юридический вопрос"
            placeholder="Задайте вопрос по договорам, регламентам или законам РФ..."
            className="max-h-48 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[14.5px] leading-6 text-fg placeholder:text-faint focus:outline-none focus-visible:outline-none disabled:opacity-55"
            style={{ overflow: value.length > 180 ? "auto" : "hidden" }}
          />
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSend}
            aria-label="Отправить вопрос"
            className={cn(
              "grid size-9 shrink-0 place-items-center rounded-lg transition-colors",
              canSend
                ? "bg-psb-orange text-white hover:bg-[#ff7433] cursor-pointer"
                : "bg-white/[0.06] text-faint cursor-not-allowed",
            )}
          >
            {isSending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <ArrowUp className="size-4" strokeWidth={2} aria-hidden="true" />
            )}
          </button>
        </div>
      </div>
    );
  },
);
