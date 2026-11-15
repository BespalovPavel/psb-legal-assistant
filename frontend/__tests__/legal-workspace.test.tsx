import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LegalWorkspace } from "@/components/legal/LegalWorkspace";
import type {
  ChatDetail,
  ChatListItem,
  ChunkWithDoc,
  DocumentDetail,
  DocumentListItem,
} from "@/types/legal";

type MockFetchHandler = (
  url: string,
  init?: RequestInit,
) => Promise<Response> | Response;

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function parseUrlPath(input: RequestInfo | URL): string {
  const raw =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
  try {
    return new URL(raw, "http://localhost:3000").pathname;
  } catch {
    return raw;
  }
}

describe("LegalWorkspace integration", () => {
  beforeEach(() => {
    HTMLDialogElement.prototype.showModal = function showModal(
      this: HTMLDialogElement,
    ) {
      this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close = function close(
      this: HTMLDialogElement,
      returnValue?: string,
    ) {
      if (returnValue !== undefined) {
        this.returnValue = returnValue;
      }
      const wasOpen = this.hasAttribute("open");
      this.removeAttribute("open");
      if (wasOpen) {
        this.dispatchEvent(new Event("close"));
      }
    };
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function installFetchMock(handler: MockFetchHandler) {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = parseUrlPath(input);
        return handler(path, init);
      },
    );
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
    return fetchMock;
  }

  it("renders minimal hero and filters Knowledge Base company documents (doc_type !== 'law')", async () => {
    const docs: DocumentListItem[] = [
      {
        doc_id: "dogovor-arendy",
        title: "Договор аренды А-08-2024 Северный Склад",
        doc_type: "contract",
        status: "действует",
        valid_from: "2024-02-01",
        valid_to: null,
        n_chunks: 10,
      },
      {
        doc_id: "dop-soglashenie-1",
        title: "Доп соглашение 1 к договору П-17-2024",
        doc_type: "addendum",
        status: "действует",
        valid_from: "2024-06-01",
        valid_to: null,
        n_chunks: 4,
      },
      {
        doc_id: "tk-st-70",
        title: "ТК ст70 действующая",
        doc_type: "law",
        status: "действующая редакция",
        valid_from: null,
        valid_to: null,
        n_chunks: 5,
      },
    ];

    installFetchMock((path) => {
      if (path === "/api/chats") {
        return jsonResponse([] satisfies ChatListItem[]);
      }
      if (path === "/api/documents") {
        return jsonResponse(docs);
      }
      return jsonResponse({ detail: "Not found" }, 404);
    });

    render(<LegalWorkspace />);

    expect(
      await screen.findByRole("heading", {
        name: "Чем помочь сегодня?",
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Меню" }));
    fireEvent.click(screen.getByRole("button", { name: /База знаний/i }));

    const kbDialog = await screen.findByRole("dialog", {
      name: "База знаний ПСБ",
    });
    expect(
      await within(kbDialog).findByText("Договор аренды А-08-2024 Северный Склад"),
    ).toBeInTheDocument();
    expect(
      within(kbDialog).getByText("Доп соглашение 1 к договору П-17-2024"),
    ).toBeInTheDocument();
    expect(within(kbDialog).getByText("ТК ст70 действующая")).toBeInTheDocument();

    fireEvent.click(
      within(kbDialog).getByRole("button", { name: "Документы компании" }),
    );

    expect(
      within(kbDialog).getByText("Договор аренды А-08-2024 Северный Склад"),
    ).toBeInTheDocument();
    expect(
      within(kbDialog).getByText("Доп соглашение 1 к договору П-17-2024"),
    ).toBeInTheDocument();
    expect(
      within(kbDialog).queryByText("ТК ст70 действующая"),
    ).not.toBeInTheDocument();
  });

  it("executes two-step send, disables inputs while pending, renders assistant text literally without Markdown, and cleans ДОКУМЕНТ #1 from source chips", async () => {
    const messageDeferred = createDeferred<Response>();

    const fetchMock = installFetchMock((path, init) => {
      const method = init?.method ?? "GET";
      if (path === "/api/chats" && method === "GET") {
        return jsonResponse([]);
      }
      if (path === "/api/documents" && method === "GET") {
        return jsonResponse([]);
      }
      if (path === "/api/chats" && method === "POST") {
        return jsonResponse(
          { chat_id: "chat-101", title: "Какой срок испытания?" },
          201,
        );
      }
      if (path === "/api/chats/chat-101/messages" && method === "POST") {
        return messageDeferred.promise;
      }
      return jsonResponse({ detail: "Not found" }, 404);
    });

    const { container } = render(<LegalWorkspace />);
    await screen.findByRole("heading", {
      name: "Чем помочь сегодня?",
    });

    const textarea = screen.getByLabelText("Юридический вопрос");
    const sendButton = screen.getByRole("button", { name: "Отправить вопрос" });

    fireEvent.change(textarea, { target: { value: "Какой срок испытания?" } });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(textarea).toBeDisabled();
      expect(sendButton).toBeDisabled();
    });

    expect(
      await screen.findByText("Поиск ответа в базе знаний..."),
    ).toBeInTheDocument();

    messageDeferred.resolve(
      jsonResponse({
        user_message_id: 1,
        assistant_message_id: 2,
        answer: "Согласно **ст. 70 ТК РФ**, испытание до **6 месяцев**.",
        sources: [
          {
            doc_id: "tk-st-70",
            chunk_id: "tk-st-70:ch-5",
            doc_title: "ДОКУМЕНТ #1: ТК РФ, ст. 70",
            path: "ч. 5",
            snippet: "Для руководителей...",
          },
        ],
      }),
    );

    expect(
      await screen.findByText(
        "Согласно **ст. 70 ТК РФ**, испытание до **6 месяцев**.",
      ),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("strong").length).toBe(0);

    await waitFor(() => {
      expect(textarea).not.toBeDisabled();
      expect(textarea).toHaveValue("");
    });

    const sourceButton = screen.getByRole("button", {
      name: /ТК РФ, ст\. 70 • ч\. 5/,
    });
    expect(sourceButton).toHaveTextContent("ТК РФ, ст. 70 • ч. 5");
    expect(sourceButton.textContent).not.toContain("ДОКУМЕНТ #1");

    const postChatsCalls = fetchMock.mock.calls.filter(
      ([u, i]) => parseUrlPath(u) === "/api/chats" && i?.method === "POST",
    );
    expect(postChatsCalls).toHaveLength(1);
  });

  it("shows Toast on 503 error, preserves question in textarea, unlocks input, and retries on the SAME chat_id without calling POST /api/chats twice", async () => {
    let messagePostAttempts = 0;

    const fetchMock = installFetchMock((path, init) => {
      const method = init?.method ?? "GET";
      if (path === "/api/chats" && method === "GET") {
        return jsonResponse([]);
      }
      if (path === "/api/documents" && method === "GET") {
        return jsonResponse([]);
      }
      if (path === "/api/chats" && method === "POST") {
        return jsonResponse(
          { chat_id: "chat-202", title: "Срок возврата помещения?" },
          201,
        );
      }
      if (path === "/api/chats/chat-202/messages" && method === "POST") {
        messagePostAttempts += 1;
        if (messagePostAttempts === 1) {
          return jsonResponse({ detail: "Сервис не инициализирован" }, 503);
        }
        return jsonResponse({
          user_message_id: 10,
          assistant_message_id: 11,
          answer: "Возврат оформляется по акту приема-передачи.",
          sources: [],
        });
      }
      return jsonResponse({ detail: "Not found" }, 404);
    });

    render(<LegalWorkspace />);
    await screen.findByRole("heading", {
      name: "Чем помочь сегодня?",
    });

    const question = "Срок возврата помещения?";
    const textarea = screen.getByLabelText("Юридический вопрос");
    const sendButton = screen.getByRole("button", { name: "Отправить вопрос" });

    fireEvent.change(textarea, { target: { value: question } });
    fireEvent.click(sendButton);

    const toastRegion = screen.getByRole("region", { name: "Уведомления" });
    expect(
      await within(toastRegion).findAllByText("Сервис не инициализирован"),
    ).not.toHaveLength(0);

    await waitFor(() => {
      expect(textarea).not.toBeDisabled();
      expect(textarea).toHaveValue(question);
      expect(sendButton).not.toBeDisabled();
    });

    fireEvent.click(sendButton);

    expect(
      await screen.findByText("Возврат оформляется по акту приема-передачи."),
    ).toBeInTheDocument();

    const createChatCalls = fetchMock.mock.calls.filter(
      ([u, i]) => parseUrlPath(u) === "/api/chats" && i?.method === "POST",
    );
    const sendMessageCalls = fetchMock.mock.calls.filter(
      ([u, i]) =>
        parseUrlPath(u) === "/api/chats/chat-202/messages" &&
        i?.method === "POST",
    );

    expect(createChatCalls).toHaveLength(1);
    expect(sendMessageCalls).toHaveLength(2);
  });

  it("opens SourceViewerModal for chunk navigation, full document view, :whole shortcut, and 404 chunk fallback", async () => {
    const chats: ChatListItem[] = [
      {
        chat_id: "chat-1",
        title: "Аренда и акты",
        updated_at: "2026-11-15T18:00:00Z",
        last_message: "Ответ по источникам",
      },
    ];

    const chatDetail: ChatDetail = {
      chat_id: "chat-1",
      title: "Аренда и акты",
      messages: [
        {
          id: 1,
          role: "user",
          content: "Проверьте источники",
          created_at: "2026-11-15T18:00:00Z",
          sources: [],
        },
        {
          id: 2,
          role: "assistant",
          content: "Проверьте приложенные материалы.",
          created_at: "2026-11-15T18:00:02Z",
          sources: [
            {
              doc_id: "doc-rent",
              chunk_id: "doc-rent:p-6-3",
              doc_title: "Договор аренды А-08-2024",
              path: "п. 6.3",
              snippet: "6.3. Возврат...",
            },
            {
              doc_id: "doc-memo",
              chunk_id: "doc-memo:whole",
              doc_title: "Служебная записка об архиве",
              path: "документ целиком",
              snippet: "Служебная записка...",
            },
            {
              doc_id: "doc-404",
              chunk_id: "doc-404:missing",
              doc_title: "Письмо К-12",
              path: "п. 1",
              snippet: "Письмо...",
            },
          ],
        },
      ],
    };

    const chunk63: ChunkWithDoc = {
      chunk: {
        chunk_id: "doc-rent:p-6-3",
        doc_id: "doc-rent",
        ord: 1,
        path: "п. 6.3",
        section: "6. Возврат помещения",
        text: "Текст пункта 6.3 договора аренды.",
        note: null,
        is_heading: false,
        prev_id: "doc-rent:p-6-2",
        next_id: "doc-rent:p-6-4",
      },
      document: {
        doc_id: "doc-rent",
        file: "rent.txt",
        title: "Договор аренды А-08-2024",
        status: "действует",
        raw_text: null,
      },
    };

    const chunk64: ChunkWithDoc = {
      chunk: {
        chunk_id: "doc-rent:p-6-4",
        doc_id: "doc-rent",
        ord: 2,
        path: "п. 6.4",
        section: "6. Возврат помещения",
        text: "Текст пункта 6.4 договора аренды.",
        note: null,
        is_heading: false,
        prev_id: "doc-rent:p-6-3",
        next_id: null,
      },
      document: chunk63.document,
    };

    const docRentDetail: DocumentDetail = {
      document: {
        doc_id: "doc-rent",
        file: "rent.txt",
        title: "Договор аренды А-08-2024",
        doc_type: "contract",
        status: "действует",
        raw_text: "ПОЛНЫЙ ТЕКСТ ДОГОВОРА АРЕНДЫ А-08-2024",
      },
      chunks: [],
    };

    const docMemoDetail: DocumentDetail = {
      document: {
        doc_id: "doc-memo",
        file: "memo.txt",
        title: "Служебная записка об архиве",
        doc_type: "memo",
        status: "действует",
        raw_text: "ПОЛНЫЙ ТЕКСТ СЛУЖЕБНОЙ ЗАПИСКИ",
      },
      chunks: [],
    };

    const doc404Detail: DocumentDetail = {
      document: {
        doc_id: "doc-404",
        file: "k12.txt",
        title: "Письмо К-12",
        doc_type: "letter",
        status: "действует",
        raw_text: "ПОЛНЫЙ ТЕКСТ ПИСЬМА К-12",
      },
      chunks: [],
    };

    const fetchMock = installFetchMock((path) => {
      if (path === "/api/chats") return jsonResponse(chats);
      if (path === "/api/documents") return jsonResponse([]);
      if (path === "/api/chats/chat-1") return jsonResponse(chatDetail);
      if (path === "/api/chunks/doc-rent%3Ap-6-3") return jsonResponse(chunk63);
      if (path === "/api/chunks/doc-rent%3Ap-6-4") return jsonResponse(chunk64);
      if (path === "/api/documents/doc-rent") return jsonResponse(docRentDetail);
      if (path === "/api/documents/doc-memo") return jsonResponse(docMemoDetail);
      if (path === "/api/chunks/doc-404%3Amissing") {
        return jsonResponse({ detail: "Чанк не найден" }, 404);
      }
      if (path === "/api/documents/doc-404") return jsonResponse(doc404Detail);
      return jsonResponse({ detail: "Not found" }, 404);
    });

    render(<LegalWorkspace />);

    const [toggleSidebarBtn] = await screen.findAllByRole("button", {
      name: "Открыть историю чатов",
    });
    fireEvent.click(toggleSidebarBtn);

    const chatBtn = await screen.findByRole("button", { name: /^Аренда и акты/ });
    fireEvent.click(chatBtn);

    expect(
      await screen.findByText("Проверьте приложенные материалы."),
    ).toBeInTheDocument();

    // 1. Regular chunk -> breadcrumbs + prev/next + full document
    fireEvent.click(
      screen.getByRole("button", { name: /Договор аренды А-08-2024 • п\. 6\.3/ }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText("Текст пункта 6.3 договора аренды."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("Договор аренды А-08-2024 / п. 6.3"),
    ).toBeInTheDocument();

    const prevBtn = within(dialog).getByRole("button", {
      name: /Предыдущий фрагмент/,
    });
    const nextBtn = within(dialog).getByRole("button", {
      name: /Следующий фрагмент/,
    });
    expect(prevBtn).not.toBeDisabled();
    expect(nextBtn).not.toBeDisabled();

    fireEvent.click(nextBtn);
    expect(
      await within(dialog).findByText("Текст пункта 6.4 договора аренды."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("Договор аренды А-08-2024 / п. 6.4"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /Следующий фрагмент/ }),
    ).toBeDisabled();

    fireEvent.click(
      within(dialog).getByRole("button", { name: /Предыдущий фрагмент/ }),
    );
    expect(
      await within(dialog).findByText("Текст пункта 6.3 договора аренды."),
    ).toBeInTheDocument();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Открыть документ целиком" }),
    );
    expect(
      await within(dialog).findByText("ПОЛНЫЙ ТЕКСТ ДОГОВОРА АРЕНДЫ А-08-2024"),
    ).toBeInTheDocument();

    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Закрыть окно просмотра источника",
      }),
    );

    // 2. Synthetic :whole chunk_id opens document directly without calling /api/chunks/...:whole
    fireEvent.click(
      screen.getByRole("button", {
        name: /Служебная записка об архиве • документ целиком/,
      }),
    );
    const memoDialog = await screen.findByRole("dialog");
    expect(
      await within(memoDialog).findByText("ПОЛНЫЙ ТЕКСТ СЛУЖЕБНОЙ ЗАПИСКИ"),
    ).toBeInTheDocument();
    const wholeChunkCalls = fetchMock.mock.calls.filter(([u]) =>
      parseUrlPath(u).includes("doc-memo%3Awhole"),
    );
    expect(wholeChunkCalls).toHaveLength(0);

    fireEvent.click(
      within(memoDialog).getByRole("button", {
        name: "Закрыть окно просмотра источника",
      }),
    );

    // 3. 404 chunk falls back to GET /api/documents/{doc_id}
    fireEvent.click(
      screen.getByRole("button", { name: /Письмо К-12 • п\. 1/ }),
    );
    const fallbackDialog = await screen.findByRole("dialog");
    expect(
      await within(fallbackDialog).findByText("ПОЛНЫЙ ТЕКСТ ПИСЬМА К-12"),
    ).toBeInTheDocument();
  });

  it("transitions cleanly from KnowledgeBaseModal to SourceViewerModal and back without auto-closing", async () => {
    const docs: DocumentListItem[] = [
      {
        doc_id: "dogovor-arendy",
        title: "Договор аренды А-08-2024 Северный Склад",
        doc_type: "contract",
        status: "действует",
        valid_from: "2024-02-01",
        valid_to: null,
        n_chunks: 10,
      },
    ];
    const docDetail: DocumentDetail = {
      document: {
        doc_id: "dogovor-arendy",
        file: "rent.txt",
        title: "Договор аренды А-08-2024 Северный Склад",
        doc_type: "contract",
        status: "действует",
        raw_text: "ПОЛНЫЙ ТЕКСТ ДОГОВОРА АРЕНДЫ",
      },
      chunks: [],
    };

    installFetchMock((path) => {
      if (path === "/api/chats") return jsonResponse([]);
      if (path === "/api/documents") return jsonResponse(docs);
      if (path === "/api/documents/dogovor-arendy") {
        return jsonResponse(docDetail);
      }
      return jsonResponse({ detail: "Not found" }, 404);
    });

    render(<LegalWorkspace />);
    await screen.findByRole("heading", {
      name: "Чем помочь сегодня?",
    });

    fireEvent.click(screen.getByRole("button", { name: "Меню" }));
    fireEvent.click(screen.getByRole("button", { name: /База знаний/i }));
    const kbDialog = await screen.findByRole("dialog", {
      name: "База знаний ПСБ",
    });

    const docItemBtn = await within(kbDialog).findByRole("button", {
      name: /Договор аренды А-08-2024 Северный Склад/,
    });
    fireEvent.click(docItemBtn);

    const sourceDialog = await screen.findByRole("dialog", {
      name: /Договор аренды А-08-2024 Северный Склад/,
    });
    expect(
      await within(sourceDialog).findByText("ПОЛНЫЙ ТЕКСТ ДОГОВОРА АРЕНДЫ"),
    ).toBeInTheDocument();

    fireEvent.click(
      within(sourceDialog).getByRole("button", { name: "База знаний" }),
    );
    expect(
      await screen.findByRole("dialog", { name: "База знаний ПСБ" }),
    ).toBeInTheDocument();
  });
});
