// Proxies research runs to the Python worker and passes its NDJSON stream straight through,
// so the browser never needs the worker's address and the worker never needs CORS.
const WORKER_URL = process.env.WORKER_URL ?? "http://127.0.0.1:8000";

// A live run spends paid credits, so only this app's own pages may start one. Another site
// open in the same browser could otherwise post a plain-text body here without a preflight.
function fromThisApp(request: Request): boolean {
  const site = request.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") return false;
  const origin = request.headers.get("origin");
  return !origin || origin === new URL(request.url).origin;
}

export async function POST(request: Request) {
  if (!fromThisApp(request)) {
    return Response.json({ detail: "Research runs can only be started from this app." }, { status: 403 });
  }
  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return Response.json({ detail: "Send the research request as JSON." }, { status: 415 });
  }
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "The research request isn't valid JSON." }, { status: 400 });
  }
  // Forward only the fields the worker accepts; it validates their values.
  const { product, max_leads, mode } = body ?? {};

  let upstream: Response;
  try {
    upstream = await fetch(`${WORKER_URL}/research`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product, max_leads, mode }),
    });
  } catch {
    return Response.json(
      { detail: "The research worker isn't running. In worker/, start it with: uv run uvicorn main:app --port 8000" },
      { status: 502 },
    );
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}
