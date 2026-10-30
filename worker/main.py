from fastapi import FastAPI

app = FastAPI(title="GTM Engine worker")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
