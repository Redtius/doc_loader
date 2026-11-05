"""Does splitting on titles retrieve more relevant chunks than splitting by size only?

Same Markdown text, same chunk size, three ways of cutting:
  A  size only: titles left as plain text, RecursiveCharacterTextSplitter
  B  titles: split on #/##/### first, then by size
  C  titles + path: B, with "[Document > Section > Sub-section]" prepended to each chunk

A question counts as found when its reference phrase is in a retrieved chunk. Retrieval
is done over all documents' chunks together, with a local embedding model and with BM25.

Usage:
    python chunking_experiment.py <markdown folder> <questions.json>
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge convention
TOP_K = (1, 3, 5)

splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
by_titles = MarkdownHeaderTextSplitter([("#", "h1"), ("##", "h2"), ("###", "h3")], strip_headers=False)


def norm(text: str) -> str:
    return " ".join(text.replace("\\#", "#").split()).lower()


def chunks_size_only(doc: str, markdown: str) -> list[tuple[str, str, str]]:
    plain = re.sub(r"(?m)^#{1,6} ", "", markdown)
    return [(doc, c, c) for c in splitter.split_text(plain)]


def chunks_by_titles(doc: str, markdown: str, with_path: bool) -> list[tuple[str, str, str]]:
    result = []
    for section in by_titles.split_text(markdown):
        path = " > ".join(section.metadata[k] for k in ("h1", "h2", "h3") if k in section.metadata)
        for body in splitter.split_text(section.page_content):
            indexed = f"[{path}]\n{body}" if with_path and path else body
            result.append((doc, body, indexed))  # (document, body for scoring, text indexed)
    return result


def evaluate(chunks, questions, model):
    bodies = [norm(body) for _, body, _ in chunks]
    indexed = [text for _, _, text in chunks]
    vectors = model.encode(indexed, normalize_embeddings=True, batch_size=32)
    bm25 = BM25Okapi([re.findall(r"\w+", t.lower()) for t in indexed])
    findable = [any(norm(q["phrase"]) in b for b in bodies) for q in questions]

    scores = {"embeddings": [], "bm25": []}
    for q in questions:
        query_vec = model.encode([QUERY_PREFIX + q["question"]], normalize_embeddings=True)[0]
        ranked = {
            "embeddings": np.argsort(-(vectors @ query_vec)),
            "bm25": np.argsort(-bm25.get_scores(re.findall(r"\w+", q["question"].lower()))),
        }
        phrase = norm(q["phrase"])
        for method, order in ranked.items():
            rank = next((r for r, i in enumerate(order[:20], start=1) if phrase in bodies[i]), None)
            scores[method].append(rank)
    return findable, scores


def main() -> None:
    folder, questions_file = Path(sys.argv[1]), Path(sys.argv[2])
    questions = json.loads(questions_file.read_text())
    docs = {name: (folder / f"{name}.md").read_text(encoding="utf-8") for name in {q["doc"] for q in questions}}
    model = SentenceTransformer(EMBEDDING_MODEL)

    variants = {
        "A size only": lambda d, m: chunks_size_only(d, m),
        "B titles": lambda d, m: chunks_by_titles(d, m, with_path=False),
        "C titles + path": lambda d, m: chunks_by_titles(d, m, with_path=True),
    }
    print(f"{len(questions)} questions, {len(docs)} documents, chunk size {CHUNK_SIZE}, overlap {CHUNK_OVERLAP}\n")
    header = f"{'variant':16} {'chunks':>6} {'avg len':>7} {'findable':>8} | " + " | ".join(
        f"{m}: " + " ".join(f"top{k:<2}" for k in TOP_K) + "  MRR" for m in ("embeddings", "bm25")
    )
    print(header)
    for name, make in variants.items():
        chunks = [c for doc, md in docs.items() for c in make(doc, md)]
        findable, scores = evaluate(chunks, questions, model)
        avg_len = sum(len(b) for _, b, _ in chunks) / len(chunks)
        parts = []
        for method in ("embeddings", "bm25"):
            ranks = scores[method]
            hits = " ".join(f"{sum(1 for r in ranks if r and r <= k):>5}" for k in TOP_K)
            mrr = sum(1 / r for r in ranks if r) / len(ranks)
            parts.append(f"{' ' * len(method)}  {hits}  {mrr:.2f}")
        print(f"{name:16} {len(chunks):>6} {avg_len:>7.0f} {sum(findable):>5}/{len(questions):<2} | " + " | ".join(parts))


if __name__ == "__main__":
    main()
