"""Related-claim retrieval.

Preferred backend: local Sentence Transformers embeddings indexed with FAISS.
If either is unavailable (not installed, or the model cannot be downloaded),
falls back to TF-IDF vectors with numpy cosine similarity. The behaviour of
`related()` is identical either way, so the rest of the app never branches.
"""
# How to read this file
# ---------------------
# related(query, corpus) is the only function the agents need: it returns the corpus
# entries that mean the most similar thing to `query`, with a 0..1 score.
#   embeddings backend: each text becomes a 384-number vector (all-MiniLM-L6-v2) and
#                       FAISS finds the nearest vectors (cosine similarity).
#   TF-IDF backend:     word and 4-letter-chunk counts weighted by rarity, compared
#                       with numpy; used when the model isn't available (e.g. on Render).

from __future__ import annotations

import re
import threading
from collections import Counter
from collections.abc import Sequence

import numpy as np

# The model is loaded once, on first use, by whichever request needs it first.
_lock = threading.Lock()
_model = None
_backend = "unknown"
_tried = False

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _load() -> None:
    """Try to load Sentence Transformers + FAISS once; fall back to TF-IDF if unavailable."""
    global _model, _backend, _tried
    with _lock:
        if _tried:
            return
        _tried = True
        try:
            import faiss  # noqa: F401
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(MODEL_NAME)
            _backend = "embeddings"
        except Exception:
            _model = None
            _backend = "tfidf"


def backend() -> str:
    """'embeddings' or 'tfidf', whichever is active."""
    _load()
    return _backend


def backend_label() -> str:
    """Human-readable name of the active retrieval backend."""
    return "Sentence Transformers + FAISS" if backend() == "embeddings" else "TF-IDF + cosine (fallback)"


# ---------------------------------------------------------------- embeddings
def _embed(texts: Sequence[str]) -> np.ndarray:
    """Normalised sentence embeddings for a list of texts."""
    vecs = _model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype="float32")


def _faiss_search(corpus_vecs: np.ndarray, query_vecs: np.ndarray, k: int):
    """Top-k inner-product (cosine) search with a flat FAISS index."""
    import faiss

    index = faiss.IndexFlatIP(corpus_vecs.shape[1])
    index.add(corpus_vecs)
    return index.search(query_vecs, min(k, corpus_vecs.shape[0]))


# ------------------------------------------------------------------- TF-IDF
_TOKEN = re.compile(r"[a-z0-9']+")
# Very common words that carry no meaning for matching.
_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "we", "i", "you", "they", "it", "is", "are",
    "be", "to", "of", "for", "on", "in", "at", "with", "that", "this", "as", "so", "do",
    "should", "can", "will", "would", "our", "their", "there", "then", "than", "have", "has",
}


def _stem(word: str) -> str:
    """Very small suffix stripper so 'guests' and 'guest' match."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> list[str]:
    """Stemmed words plus character 4-grams.

    The character grams let the fallback match wording the word index misses
    ("checkout" vs "check out", "guest" vs "guests").
    """
    # Words without stop words, plus 4-letter chunks of the text with spaces removed.
    words = [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]
    squashed = "".join(_TOKEN.findall(text.lower()))
    grams = [f"#{squashed[i:i + 4]}" for i in range(max(0, len(squashed) - 3))]
    return words + grams


def _tfidf_matrix(docs: Sequence[str]) -> tuple[np.ndarray, dict[str, int], np.ndarray]:
    """TF-IDF matrix (rows normalised) plus vocabulary and IDF weights for the fallback."""
    toks = [_tokens(d) for d in docs]
    vocab: dict[str, int] = {}
    for t in toks:
        for w in t:
            vocab.setdefault(w, len(vocab))
    n = len(docs)
    df = np.zeros(len(vocab))
    for t in toks:
        for w in set(t):
            df[vocab[w]] += 1
    # Rare words weigh more (inverse document frequency); each row is then
    # term frequency x IDF, scaled to length 1 so a dot product is the cosine.
    idf = np.log((1 + n) / (1 + df)) + 1.0
    mat = np.zeros((n, len(vocab)), dtype="float32")
    for i, t in enumerate(toks):
        counts = Counter(t)
        if not counts:
            continue
        for w, c in counts.items():
            mat[i, vocab[w]] = (c / len(t)) * idf[vocab[w]]
        norm = np.linalg.norm(mat[i])
        if norm:
            mat[i] /= norm
    return mat, vocab, idf


def _tfidf_vector(text: str, vocab: dict[str, int], idf: np.ndarray) -> np.ndarray:
    """TF-IDF vector of one text in an existing vocabulary."""
    t = _tokens(text)
    v = np.zeros(len(vocab), dtype="float32")
    if not t:
        return v
    counts = Counter(t)
    for w, c in counts.items():
        if w in vocab:
            v[vocab[w]] = (c / len(t)) * idf[vocab[w]]
    norm = np.linalg.norm(v)
    return v / norm if norm else v


# -------------------------------------------------------------------- public
def related(
    query: str,
    corpus: Sequence[tuple[str, str]],
    k: int = 5,
    min_score: float = 0.18,
) -> list[tuple[str, float]]:
    """Return [(corpus_id, similarity)] most related to `query`, best first."""
    # Ignore empty texts; nothing to compare means no results.
    corpus = [(cid, text) for cid, text in corpus if (text or "").strip()]
    if not corpus or not (query or "").strip():
        return []
    texts = [t for _, t in corpus]
    ids = [c for c, _ in corpus]

    # Preferred: embeddings + FAISS. Any failure falls through to TF-IDF below.
    if backend() == "embeddings":
        try:
            cvecs = _embed(texts)
            qvec = _embed([query])
            scores, idxs = _faiss_search(cvecs, qvec, k)
            out = [(ids[i], float(s)) for s, i in zip(scores[0], idxs[0], strict=True) if i != -1]
            return [(i, s) for i, s in out if s >= min_score]
        except Exception:
            pass  # fall through to TF-IDF

    # Fallback: TF-IDF vectors; the best k above min_score, best first.
    mat, vocab, idf = _tfidf_matrix(texts)
    qv = _tfidf_vector(query, vocab, idf)
    sims = mat @ qv
    order = np.argsort(-sims)[:k]
    return [(ids[int(i)], float(sims[int(i)])) for i in order if sims[int(i)] >= min_score]


def pairwise_duplicates(
    docs: Sequence[tuple[str, str]], threshold: float = 0.45
) -> list[tuple[str, str, float]]:
    """Return [(id_a, id_b, score)] for every pair above `threshold`."""
    docs = [(d, t) for d, t in docs if (t or "").strip()]
    if len(docs) < 2:
        return []
    ids = [d for d, _ in docs]
    texts = [t for _, t in docs]

    mat = None
    if backend() == "embeddings":
        try:
            mat = _embed(texts)
        except Exception:
            mat = None
    if mat is None:
        mat, _, _ = _tfidf_matrix(texts)

    sims = mat @ mat.T
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            s = float(sims[i, j])
            if s >= threshold:
                pairs.append((ids[i], ids[j], s))
    pairs.sort(key=lambda p: -p[2])
    return pairs


def similarity(a: str, b: str) -> float:
    """Similarity of two texts (0..1) using the active backend."""
    res = related(a, [("b", b)], k=1, min_score=-1.0)
    return res[0][1] if res else 0.0
