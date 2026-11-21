"""Bid documents: download PDFs, split into chunks with page numbers, embed, search by meaning.
This is a tiny vector store you write yourself (numpy + one JSON file per opportunity)."""
import io
import json
import re

import numpy as np
from openai import OpenAI
from pypdf import PdfReader

import config
from net import HTTPError, request_with_retry

_client = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _store_path(opp_id: str):
    return config.DOCS_DIR / (re.sub(r"[^A-Za-z0-9_-]", "_", opp_id) + ".json")


def pdf_pages(pdf_bytes: bytes) -> list[tuple[int, str]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(i + 1, (page.extract_text() or "").strip()) for i, page in enumerate(reader.pages)]


def chunk_pages(pages, max_chars: int = 3000, overlap: int = 300) -> list[dict]:
    """~3,000 characters is roughly 750 tokens. Overlap so a sentence cut in half still appears whole once."""
    chunks = []
    for page_no, text in pages:
        text = re.sub(r"\s+", " ", text)
        start = 0
        while start < len(text):
            piece = text[start:start + max_chars]
            if piece.strip():
                chunks.append({"page": page_no, "text": piece})
            if start + max_chars >= len(text):
                break
            start += max_chars - overlap
    return chunks


def embed(texts: list[str]) -> np.ndarray:
    vectors = []
    for i in range(0, len(texts), 100):                      # send in batches of 100
        resp = client().embeddings.create(model=config.EMBED_MODEL, input=texts[i:i + 100])
        vectors.extend(d.embedding for d in resp.data)
    return np.array(vectors, dtype=np.float32)


def rank(matrix: np.ndarray, query: np.ndarray, k: int) -> list[tuple[int, float]]:
    """Cosine similarity: how closely each chunk's meaning points the same way as the question."""
    scores = (matrix @ query) / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query) + 1e-9)
    top = np.argsort(scores)[::-1][:k]
    return [(int(i), float(scores[i])) for i in top]


def index_document(opp_id: str, attachments: list[str], max_files: int = 3) -> dict:
    """Download, read, chunk and embed a notice's PDFs once. After that, it's read from disk for free."""
    path = _store_path(opp_id)
    if path.exists():
        return json.loads(path.read_text())               # already indexed: no download, no cost
    chunks, skipped, failed = [], [], []
    for url in attachments[:max_files]:
        params = {"api_key": config.SAM_API_KEY} if "sam.gov" in url else None
        try:
            content = request_with_retry("GET", url, params=params, timeout=60).content
        except HTTPError as exc:
            failed.append(str(exc))                       # one bad file shouldn't stop the others
            continue
        if not content.startswith(b"%PDF"):
            skipped.append(url)                           # v1 reads PDFs only: say so, don't pretend
            continue
        for c in chunk_pages(pdf_pages(content)):
            c["source_url"] = url
            chunks.append(c)
    vectors = embed([c["text"] for c in chunks]).tolist() if chunks else []
    store = {"opp_id": opp_id, "chunks": chunks, "vectors": vectors, "skipped": skipped, "failed": failed}
    if not failed:                                        # don't cache a partial result: retry next time
        config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store))
    return store


def search(store: dict, question: str, k: int | None = None) -> list[dict]:
    k = k or config.TOP_K_CHUNKS
    if not store["chunks"]:
        return []
    matrix = np.array(store["vectors"], dtype=np.float32)
    hits = rank(matrix, embed([question])[0], k)
    return [{"page": store["chunks"][i]["page"], "score": round(s, 3), "text": store["chunks"][i]["text"]}
            for i, s in hits]
