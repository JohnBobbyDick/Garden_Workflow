from fastapi import FastAPI

app = FastAPI(title="AI Security Workflow API", version="0.1.0", docs_url="/docs", openapi_url="/openapi.json")


@app.get("/api/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
