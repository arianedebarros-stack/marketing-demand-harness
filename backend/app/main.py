from fastapi import FastAPI

app = FastAPI(title="Marketing Demand Harness")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
