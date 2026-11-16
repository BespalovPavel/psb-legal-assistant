import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
const DEFAULT_TIMEOUT_MS = 200_000;
const CONTROL_CHARS_RE = /[\u0000-\u001f\u007f]/;
const BODY_METHODS = new Set(["POST", "PUT", "PATCH"]);
const UNSAFE_RESPONSE_HEADERS = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
]);
const SAFE_RESPONSE_HEADERS = ["content-type", "cache-control"] as const;

function validateAndEncodePath(segments: unknown): string[] | null {
  if (!Array.isArray(segments) || segments.length === 0) {
    return null;
  }

  const encoded: string[] = [];
  for (const segment of segments) {
    if (
      typeof segment !== "string" ||
      segment.length === 0 ||
      segment === "." ||
      segment === ".." ||
      CONTROL_CHARS_RE.test(segment)
    ) {
      return null;
    }
    encoded.push(encodeURIComponent(segment));
  }

  return encoded;
}

function resolveTimeoutMs(): number {
  const parsed = Number(process.env.PSB_PROXY_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
}

async function proxyRequest(
  req: NextRequest,
  context: RouteContext,
): Promise<NextResponse> {
  const { path: rawSegments } = await context.params;
  const encodedSegments = validateAndEncodePath(rawSegments);

  if (!encodedSegments) {
    return NextResponse.json(
      { detail: "Некорректный путь запроса" },
      { status: 400 },
    );
  }

  const baseUrl = process.env.PSB_API_URL || DEFAULT_BACKEND_URL;
  const targetUrl = new URL(`/api/${encodedSegments.join("/")}`, baseUrl);
  targetUrl.search = req.nextUrl?.search ?? new URL(req.url).search;

  const forwardHeaders = new Headers();
  const accept = req.headers.get("accept");
  if (accept) {
    forwardHeaders.set("accept", accept);
  }

  const fetchInit: RequestInit = {
    method: req.method,
    headers: forwardHeaders,
    signal: AbortSignal.timeout(resolveTimeoutMs()),
    cache: "no-store",
  };

  if (BODY_METHODS.has(req.method)) {
    const bodyBuf = await req.arrayBuffer();
    if (bodyBuf.byteLength > 0) {
      fetchInit.body = bodyBuf;
      const contentType = req.headers.get("content-type");
      if (contentType) {
        forwardHeaders.set("content-type", contentType);
      }
    }
  }

  try {
    const upstreamResponse = await fetch(targetUrl.toString(), fetchInit);

    const responseHeaders = new Headers();
    for (const headerName of SAFE_RESPONSE_HEADERS) {
      if (UNSAFE_RESPONSE_HEADERS.has(headerName)) {
        continue;
      }
      const value = upstreamResponse.headers.get(headerName);
      if (value !== null) {
        responseHeaders.set(headerName, value);
      }
    }

    const isNullBody =
      req.method === "HEAD" ||
      upstreamResponse.status === 204 ||
      upstreamResponse.status === 304 ||
      (upstreamResponse.status >= 100 && upstreamResponse.status < 200);

    const responseBody = isNullBody
      ? null
      : (upstreamResponse.body ?? (await upstreamResponse.arrayBuffer()));

    return new NextResponse(responseBody, {
      status: upstreamResponse.status,
      headers: responseHeaders,
    });
  } catch (error) {
    const errorName = (error as { name?: string } | null)?.name;
    if (errorName === "TimeoutError" || errorName === "AbortError") {
      return NextResponse.json(
        { detail: "Превышено время ожидания ответа от сервера" },
        { status: 504 },
      );
    }

    return NextResponse.json(
      { detail: "Бэкенд ПСБ Юридического ассистента недоступен" },
      { status: 502 },
    );
  }
}

export async function GET(req: NextRequest, context: RouteContext) {
  return proxyRequest(req, context);
}

export async function HEAD(req: NextRequest, context: RouteContext) {
  return proxyRequest(req, context);
}

export async function POST(req: NextRequest, context: RouteContext) {
  return proxyRequest(req, context);
}

export async function PUT(req: NextRequest, context: RouteContext) {
  return proxyRequest(req, context);
}

export async function PATCH(req: NextRequest, context: RouteContext) {
  return proxyRequest(req, context);
}

export async function DELETE(req: NextRequest, context: RouteContext) {
  return proxyRequest(req, context);
}

export async function OPTIONS(req: NextRequest, context: RouteContext) {
  return proxyRequest(req, context);
}
