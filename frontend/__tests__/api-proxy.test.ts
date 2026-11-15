// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DELETE, GET, HEAD, POST } from "@/app/api/[...path]/route";

function makeContext(path: string[]) {
  return {
    params: Promise.resolve({ path }),
  };
}

describe("app/api/[...path]/route.ts BFF proxy", () => {
  const originalApiUrl = process.env.PSB_API_URL;
  const originalTimeout = process.env.PSB_PROXY_TIMEOUT_MS;

  beforeEach(() => {
    process.env.PSB_API_URL = "http://backend.internal:8000";
    process.env.PSB_PROXY_TIMEOUT_MS = "15000";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    if (originalApiUrl === undefined) {
      delete process.env.PSB_API_URL;
    } else {
      process.env.PSB_API_URL = originalApiUrl;
    }
    if (originalTimeout === undefined) {
      delete process.env.PSB_PROXY_TIMEOUT_MS;
    } else {
      process.env.PSB_PROXY_TIMEOUT_MS = originalTimeout;
    }
  });

  it("forwards GET requests with Next 15 async params, encoded segments, query string, and omits body", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const req = new NextRequest(
      "http://localhost:3000/api/chunks/dogovor:p-6-3?foo=bar&lang=ru",
      {
        method: "GET",
        headers: { accept: "application/json" },
      },
    );

    const res = await GET(req, makeContext(["chunks", "dogovor:p-6-3"]));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [targetUrl, init] = fetchMock.mock.calls[0]!;
    expect(targetUrl).toBe(
      "http://backend.internal:8000/api/chunks/dogovor%3Ap-6-3?foo=bar&lang=ru",
    );
    expect(init?.method).toBe("GET");
    expect(init?.body).toBeUndefined();
    expect(new Headers(init?.headers).get("accept")).toBe("application/json");
  });

  it("rejects '.' and '..' path traversal segments and empty paths with 400 without calling fetch", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);

    for (const badPath of [["chats", ".."], ["."], [".."], []]) {
      const req = new NextRequest("http://localhost:3000/api/chats", {
        method: "GET",
      });
      const res = await GET(req, makeContext(badPath));
      expect(res.status).toBe(400);
      const body = (await res.json()) as { detail?: string };
      expect(body.detail).toBeTruthy();
    }

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("omits body and strips Content-Type header on bodyless POST /api/chats", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ chat_id: "c-1", title: "Новый чат" }),
        {
          status: 201,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const req = new NextRequest("http://localhost:3000/api/chats", {
      method: "POST",
      headers: { "content-type": "application/json" },
    });

    const res = await POST(req, makeContext(["chats"]));
    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ chat_id: "c-1", title: "Новый чат" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0]!;
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
    expect(new Headers(init?.headers).has("content-type")).toBe(false);
  });

  it("forwards JSON body and Content-Type header when POST has non-empty payload", async () => {
    const payload = JSON.stringify({ content: "Какой срок испытания?" });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          user_message_id: 1,
          assistant_message_id: 2,
          answer: "Три месяца.",
          sources: [],
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const req = new NextRequest("http://localhost:3000/api/chats/c-1/messages", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: payload,
    });

    const res = await POST(req, makeContext(["chats", "c-1", "messages"]));
    expect(res.status).toBe(200);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [targetUrl, init] = fetchMock.mock.calls[0]!;
    expect(targetUrl).toBe(
      "http://backend.internal:8000/api/chats/c-1/messages",
    );
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("content-type")).toBe(
      "application/json",
    );
    expect(init?.body).toBeInstanceOf(ArrayBuffer);
    const decoded = new TextDecoder().decode(init?.body as ArrayBuffer);
    expect(decoded).toBe(payload);
  });

  it("omits body on HEAD and DELETE requests and returns null body for HEAD", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(null, {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "deleted" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const headReq = new NextRequest("http://localhost:3000/api/documents", {
      method: "HEAD",
    });
    const headRes = await HEAD(headReq, makeContext(["documents"]));
    expect(headRes.status).toBe(200);
    expect(await headRes.text()).toBe("");
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("HEAD");
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBeUndefined();

    const delReq = new NextRequest("http://localhost:3000/api/chats/c-1", {
      method: "DELETE",
    });
    const delRes = await DELETE(delReq, makeContext(["chats", "c-1"]));
    expect(delRes.status).toBe(200);
    expect(await delRes.json()).toEqual({ status: "deleted" });
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe("DELETE");
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBeUndefined();
  });

  it("strips content-encoding and content-length while preserving content-type", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify([{ chat_id: "c-1" }]), {
        status: 200,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "content-encoding": "gzip",
          "content-length": "999",
          "cache-control": "private, max-age=0",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const req = new NextRequest("http://localhost:3000/api/chats", {
      method: "GET",
    });
    const res = await GET(req, makeContext(["chats"]));

    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe(
      "application/json; charset=utf-8",
    );
    expect(res.headers.get("cache-control")).toBe("private, max-age=0");
    expect(res.headers.get("content-encoding")).toBeNull();
    expect(res.headers.get("content-length")).toBeNull();
  });

  it("maps upstream TimeoutError to 504 and network errors to 502", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new DOMException("Timed out", "TimeoutError"))
      .mockRejectedValueOnce(new TypeError("fetch failed"));
    vi.stubGlobal("fetch", fetchMock);

    const timeoutReq = new NextRequest("http://localhost:3000/api/chats", {
      method: "GET",
    });
    const timeoutRes = await GET(timeoutReq, makeContext(["chats"]));
    expect(timeoutRes.status).toBe(504);
    const timeoutBody = (await timeoutRes.json()) as { detail: string };
    expect(timeoutBody.detail).toContain("время ожидания");

    const netReq = new NextRequest("http://localhost:3000/api/chats", {
      method: "GET",
    });
    const netRes = await GET(netReq, makeContext(["chats"]));
    expect(netRes.status).toBe(502);
    const netBody = (await netRes.json()) as { detail: string };
    expect(netBody.detail).toContain("недоступен");
  });
});
