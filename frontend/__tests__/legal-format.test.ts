import { describe, expect, it } from "vitest";
import {
  deriveChatTitle,
  formatDocTypeLabel,
  formatLegalDateRu,
  formatSourceChipLabel,
  getDocStatusMeta,
  getDocumentFullText,
  isSyntheticWholeChunk,
  sanitizeSourceText,
} from "@/lib/legal-format";
import type { DocumentDetail, MessageSource } from "@/types/legal";

describe("lib/legal-format", () => {
  describe("sanitizeSourceText", () => {
    it("returns empty string for nullish, empty, or literal null/undefined strings", () => {
      expect(sanitizeSourceText(null)).toBe("");
      expect(sanitizeSourceText(undefined)).toBe("");
      expect(sanitizeSourceText("")).toBe("");
      expect(sanitizeSourceText("   ")).toBe("");
      expect(sanitizeSourceText("null")).toBe("");
      expect(sanitizeSourceText("NULL")).toBe("");
      expect(sanitizeSourceText("undefined")).toBe("");
    });

    it("strips internal retrieval header markers such as ДОКУМЕНТ #1, === ДОКУМЕНТ #2: ... ===, and документ №3", () => {
      expect(
        sanitizeSourceText("ДОКУМЕНТ #1: Договор аренды № А-08/2024"),
      ).toBe("Договор аренды № А-08/2024");
      expect(sanitizeSourceText("ДОКУМЕНТ #1 Договор аренды")).toBe(
        "Договор аренды",
      );
      expect(
        sanitizeSourceText("=== ДОКУМЕНТ #2: [Файл: test.txt] ==="),
      ).toBe("");
      expect(
        sanitizeSourceText(
          "=== ДОКУМЕНТ #2: служебный блок === Договор поставки № П-17/2024",
        ),
      ).toBe("Договор поставки № П-17/2024");
      expect(sanitizeSourceText("документ №3 п. 6.3")).toBe("п. 6.3");
      expect(sanitizeSourceText("документ № 12: ст. 70")).toBe("ст. 70");
    });

    it("preserves normal legal document titles and clause paths", () => {
      expect(
        sanitizeSourceText("Договор аренды А-08-2024 Северный Склад"),
      ).toBe("Договор аренды А-08-2024 Северный Склад");
      expect(sanitizeSourceText("ст. 9, ч. 2")).toBe("ст. 9, ч. 2");
    });
  });

  describe("formatSourceChipLabel", () => {
    it("formats doc_title and path separated by bullet", () => {
      const source: MessageSource = {
        doc_id: "dogovor-arendy-a-08-2024",
        chunk_id: "dogovor-arendy-a-08-2024:p-6-3",
        doc_title: "Договор аренды № А-08/2024",
        path: "п. 6.3",
        snippet: "6.3. При прекращении...",
      };
      expect(formatSourceChipLabel(source)).toBe(
        "Договор аренды № А-08/2024 • п. 6.3",
      );
    });

    it("handles null path and null doc_title without ever emitting 'null'", () => {
      expect(
        formatSourceChipLabel({
          doc_id: "doc-1",
          chunk_id: "doc-1:p-1",
          doc_title: "ТК РФ, ст. 70",
          path: null,
          snippet: null,
        }),
      ).toBe("ТК РФ, ст. 70");

      expect(
        formatSourceChipLabel({
          doc_id: "doc-1",
          chunk_id: "doc-1:p-1",
          doc_title: null,
          path: "п. 3.1",
          snippet: null,
        }),
      ).toBe("п. 3.1");

      expect(
        formatSourceChipLabel({
          doc_id: "doc-1",
          chunk_id: "doc-1:p-1",
          doc_title: null,
          path: null,
          snippet: null,
        }),
      ).toBe("Документ базы знаний");

      expect(
        formatSourceChipLabel({
          doc_id: "doc-1",
          chunk_id: "doc-1:p-1",
          doc_title: "null",
          path: "null",
          snippet: null,
        }),
      ).toBe("Документ базы знаний");
    });

    it("strips technical ДОКУМЕНТ markers from chip labels", () => {
      expect(
        formatSourceChipLabel({
          doc_id: "doc-1",
          chunk_id: "doc-1:p-1",
          doc_title: "ДОКУМЕНТ #1: Договор поставки П-17/2024",
          path: "документ №3 п. 5.2",
          snippet: null,
        }),
      ).toBe("Договор поставки П-17/2024 • п. 5.2");

      expect(
        formatSourceChipLabel({
          doc_id: "doc-2",
          chunk_id: "doc-2:p-1",
          doc_title: "=== ДОКУМЕНТ #2: [Файл: a.txt] ===",
          path: "п. 1.1",
          snippet: null,
        }),
      ).toBe("п. 1.1");
    });
  });

  describe("isSyntheticWholeChunk", () => {
    it("detects null, empty, and ':whole' synthetic chunk identifiers", () => {
      expect(isSyntheticWholeChunk(null)).toBe(true);
      expect(isSyntheticWholeChunk(undefined)).toBe(true);
      expect(isSyntheticWholeChunk("")).toBe(true);
      expect(isSyntheticWholeChunk("   ")).toBe(true);
      expect(isSyntheticWholeChunk("doc-1:whole")).toBe(true);
      expect(isSyntheticWholeChunk("  doc-1:whole  ")).toBe(true);
    });

    it("returns false for regular chunk identifiers", () => {
      expect(isSyntheticWholeChunk("dogovor-arendy-a-08-2024:p-6-3")).toBe(
        false,
      );
    });
  });

  describe("deriveChatTitle", () => {
    it("falls back to 'Новый чат' on blank input", () => {
      expect(deriveChatTitle("")).toBe("Новый чат");
      expect(deriveChatTitle("   \n\t  ")).toBe("Новый чат");
    });

    it("collapses whitespace and keeps short titles intact", () => {
      expect(
        deriveChatTitle("  Какой   срок\nиспытания у   бухгалтера?  "),
      ).toBe("Какой срок испытания у бухгалтера?");
    });

    it("truncates long titles cleanly at word boundary within 72 characters", () => {
      const longQuestion =
        "Какой максимальный срок испытания можно установить главному бухгалтеру при приёме на работу в коммерческую организацию?";
      const title = deriveChatTitle(longQuestion);
      expect(title.length).toBeLessThanOrEqual(72);
      expect(title.endsWith("…")).toBe(true);
      expect(title).not.toContain("организац");
    });
  });

  describe("getDocStatusMeta", () => {
    it("classifies active, expired, and neutral statuses in Russian", () => {
      expect(getDocStatusMeta("действует")).toEqual({
        label: "действует",
        tone: "active",
      });
      expect(getDocStatusMeta("действующая редакция")).toEqual({
        label: "действующая редакция",
        tone: "active",
      });
      expect(getDocStatusMeta("утратил силу")).toEqual({
        label: "утратил силу",
        tone: "expired",
      });
      expect(getDocStatusMeta("Утратила силу с 01.03.2025")).toEqual({
        label: "Утратила силу с 01.03.2025",
        tone: "expired",
      });
      expect(getDocStatusMeta(null)).toEqual({
        label: "Статус не указан",
        tone: "neutral",
      });
      expect(getDocStatusMeta("проект")).toEqual({
        label: "проект",
        tone: "neutral",
      });
    });
  });

  describe("getDocumentFullText", () => {
    const baseDetail: DocumentDetail = {
      document: {
        doc_id: "doc-1",
        file: "doc-1.txt",
        title: "Тестовый договор",
        raw_text: "Полный текст документа.",
      },
      chunks: [
        {
          chunk_id: "doc-1:p-1",
          ord: 0,
          path: "п. 1",
          text: "Первый пункт.",
          is_heading: false,
        },
        {
          chunk_id: "doc-1:p-2",
          ord: 1,
          path: "п. 2",
          text: "Второй пункт.",
          is_heading: false,
        },
      ],
    };

    it("returns raw_text directly when present and non-empty", () => {
      expect(getDocumentFullText(baseDetail)).toBe("Полный текст документа.");
    });

    it("falls back to joining non-empty chunks when raw_text is null or blank", () => {
      const detailWithNullRaw: DocumentDetail = {
        ...baseDetail,
        document: { ...baseDetail.document, raw_text: null },
      };
      expect(getDocumentFullText(detailWithNullRaw)).toBe(
        "Первый пункт.\n\nВторой пункт.",
      );

      const detailWithWhitespaceRaw: DocumentDetail = {
        document: { ...baseDetail.document, raw_text: "   \n  " },
        chunks: [
          ...baseDetail.chunks,
          {
            chunk_id: "doc-1:p-3",
            ord: 2,
            path: "п. 3",
            text: "   ",
            is_heading: false,
          },
        ],
      };
      expect(getDocumentFullText(detailWithWhitespaceRaw)).toBe(
        "Первый пункт.\n\nВторой пункт.",
      );
    });
  });

  describe("formatDocTypeLabel and formatLegalDateRu", () => {
    it("translates backend doc_type values and ISO dates", () => {
      expect(formatDocTypeLabel("contract")).toBe("Договор");
      expect(formatDocTypeLabel("addendum")).toBe("Доп. соглашение");
      expect(formatDocTypeLabel("law")).toBe("Нормативный акт");
      expect(formatDocTypeLabel(null)).toBe("Документ");
      expect(formatLegalDateRu("2025-03-01")).toBe("01.03.2025");
      expect(formatLegalDateRu(null)).toBe("");
    });
  });
});
