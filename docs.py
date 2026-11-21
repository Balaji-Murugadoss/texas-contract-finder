"""Bid documents: download PDFs, split into chunks with page numbers, embed, search by meaning.
Hybrid search (meaning + exact words) is available but off by default: it lost on our measured test.
A tiny vector store you write yourself: numpy + one JSON file per opportunity."""
import io
import json
import math
import re
from urllib.parse import unquote_plus

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


def _file_name(resp, n: int) -> str:
    """The server's file name (from the Content-Disposition header), for citations like 'SF1442.pdf p.3'."""
    match = re.search(r'filename="?([^";]+)', resp.headers.get("content-disposition", ""))
    return match.group(1) if match else f"file {n}"


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


STOP = {"a", "an", "and", "are", "at", "be", "by", "do", "does", "for", "from", "how", "in", "is", "it",
        "must", "of", "on", "or", "shall", "that", "the", "this", "to", "what", "when", "which", "will", "with"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9$]+", text.lower())) - STOP


def keyword_rank(texts: list[str], question: str) -> list[int]:
    """Exact-word search. A word that appears in few chunks (like 'magnitude') counts more than a common one."""
    q, chunk_words = _words(question), [_words(t) for t in texts]
    idf = {w: math.log(len(texts) / (1 + sum(w in cw for cw in chunk_words))) + 1 for w in q}
    scores = [sum(idf[w] for w in q if w in cw) for cw in chunk_words]
    return sorted(range(len(texts)), key=lambda i: scores[i], reverse=True)


def fuse(*orders: list[int], k: int) -> list[int]:
    """Reciprocal rank fusion: merge rankings by position, so meaning and exact words both get a vote."""
    fused: dict[int, float] = {}
    for order in orders:
        for position, i in enumerate(order):
            fused[i] = fused.get(i, 0) + 1 / (60 + position)
    return sorted(fused, key=fused.get, reverse=True)[:k]


def index_document(opp_id: str, attachments: list[str], max_files: int = 8) -> dict:
    """Download, read, chunk and embed a notice's PDFs once. After that, it's read from disk for free."""
    path = _store_path(opp_id)
    if path.exists():
        return json.loads(path.read_text())               # already indexed: no download, no cost
    chunks, skipped, failed = [], [], []
    for n, url in enumerate(attachments[:max_files], start=1):
        params = {"api_key": config.SAM_API_KEY} if "sam.gov" in url else None
        try:
            resp = request_with_retry("GET", url, params=params, timeout=60)
        except HTTPError as exc:
            failed.append(str(exc))                       # one bad file shouldn't stop the others
            continue
        name = _file_name(resp, n)
        if not resp.content.startswith(b"%PDF"):
            skipped.append(name)                          # v1 reads PDFs only: say so, don't pretend
            continue
        for c in chunk_pages(pdf_pages(resp.content)):
            c["file"] = name
            chunks.append(c)
    vectors = embed([c["text"] for c in chunks]).tolist() if chunks else []
    store = {"opp_id": opp_id, "chunks": chunks, "vectors": vectors, "skipped": skipped, "failed": failed,
             "files_total": len(attachments), "files_read": min(len(attachments), max_files)}
    if not failed:                                        # don't cache a partial result: retry next time
        config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store))
    return store


def search(store: dict, question: str, k: int | None = None, hybrid: bool = False) -> list[dict]:
    """Meaning search by default. hybrid=True also ranks by exact words and fuses the two rankings.
    Measured on 3 known answers: meaning-only put 3/3 in the top 5, hybrid 2/3 (it pushed the
    deadline chunk from rank 1 to rank 11). So meaning-only is the default until a bigger test says otherwise."""
    k = k or config.TOP_K_CHUNKS
    chunks = store["chunks"]
    if not chunks:
        return []
    by_meaning = rank(np.array(store["vectors"], dtype=np.float32), embed([question])[0], k=len(chunks))
    similarity = dict(by_meaning)
    order = [i for i, _ in by_meaning]
    if hybrid:
        order = fuse(order, keyword_rank([c["text"] for c in chunks], question), k=len(chunks))
    return [{"file": unquote_plus(chunks[i].get("file") or ""),      # '1+-+Solicitation.pdf' -> '1 - Solicitation.pdf'
             "page": chunks[i]["page"], "similarity": round(similarity[i], 3), "text": chunks[i]["text"]}
            for i in order[:k]]