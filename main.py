from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import entities, verses, chandas, ai
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Bhagavatam Knowledge Graph", version="0.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(entities.router)
app.include_router(verses.router)
app.include_router(chandas.router)
app.include_router(ai.router)

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
