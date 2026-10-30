// Proxies research runs to the Python worker and passes its NDJSON stream straight through,
// so the browser never needs the worker's address and the worker never needs CORS.
const WORKER_URL = process.env.WORKER_URL ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  let upstream: Response;
  try {
    upstream = await fetch(`${WORKER_URL}/research`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
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
