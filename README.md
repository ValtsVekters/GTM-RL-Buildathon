# GTM-RL-Buildathon

AI go-to-market engine: describe what you sell, and it finds real companies to sell to, shows warm intro paths, drafts outreach for a human to approve, and tracks every lead on a pipeline dashboard.

Status: early skeleton. The pages are placeholders, and the discovery, outreach and billing features aren't built yet.

## Stack

- Next.js (App Router), TypeScript, Tailwind CSS
- Prisma with SQLite
- Python FastAPI worker for the AI side

## Setup

Requires Node.js 20+ and [uv](https://docs.astral.sh/uv/).

```bash
npm install
cp .env.example .env   # then fill in your keys
npx prisma migrate dev
npm run dev            # http://localhost:3000
```

Run the worker in a second terminal:

```bash
cd worker
uv run uvicorn main:app --port 8000
```

Check it with `http://localhost:8000/health`.

## Environment

`.env.example` lists every key the app uses. Never commit `.env`.
