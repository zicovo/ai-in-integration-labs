"""What index.py and measure.py share: the corpus, the chunking rules, the embedding call and the
database. ground-the-assistant's scripts import it too, so there is one definition of a chunk in these labs.

Read it once. Nothing here is clever, and the one line that matters is marked: the title and the
heading are prepended to the chunk body before it is embedded, so that a chunk read on its own
still says what it is about. That is the stranger test from the study text, in code.
"""

from __future__ import annotations

import os
import pathlib
import re
from dataclasses import dataclass

import psycopg
import requests
import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
CORPUS = pathlib.Path(os.environ.get("AQUAFLUX_CORPUS", REPO / "labs" / "corpus" / "index-the-manuals"))
DB = os.environ.get("AQUAFLUX_DB", "postgres://aquaflux:aquaflux@db.aquaflux.internal:5432/aquaflux")
MODELS = os.environ.get("AQUAFLUX_GATEWAY", "https://models.aquaflux.internal:4000")
MODEL_KEY = os.environ.get("LAB_GATEWAY_KEY", "sk-aquaflux-lab")
EMBED_MODEL = os.environ.get("AQUAFLUX_EMBED", "aquaflux-embed")


@dataclass
class Document:
    id: str
    version: int
    title: str
    department: str
    valid_from: str
    superseded_by: str | None
    body: str  # markdown after the front matter, without the level-1 title line

    @property
    def label(self) -> str:
        return f"{self.id} v{self.version}"


@dataclass
class Chunk:
    doc: Document
    chunk_no: int
    heading: str | None
    body: str

    def text_to_embed(self) -> str:
        # The stranger test. A chunk that arrives alone in a prompt must still say which document
        # and which section it came from; the vector has to carry that too, or the chunk about
        # greasing every twelve months sits beside every other chunk about greasing.
        heading = f" / {self.heading}" if self.heading else ""
        return f"{self.doc.title}{heading}\n\n{self.body}"


def load_corpus(directory: pathlib.Path = CORPUS, include_superseded: bool = False) -> list[Document]:
    """Every document under documents/, and under superseded/ when asked."""
    paths = sorted((directory / "documents").glob("*.md"))
    if include_superseded:
        paths += sorted((directory / "superseded").glob("*.md"))
    return [read_document(path) for path in paths]


def read_document(path: pathlib.Path) -> Document:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not match:
        raise ValueError(f"{path} has no front matter")
    meta = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    body = re.sub(r"^# .*\n+", "", body, count=1)  # the title line is in the front matter already
    superseded = meta.get("superseded_by")
    return Document(str(meta["id"]), int(meta["version"]), str(meta["title"]), str(meta["department"]),
                    str(meta["valid_from"]), None if superseded in (None, "null") else str(superseded), body)


def chunk_by_headings(doc: Document) -> list[Chunk]:
    """Structure-aware: one chunk per level-2 section, heading kept with its body. The text before
    the first heading is a chunk of its own with no heading."""
    chunks: list[Chunk] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            chunks.append(Chunk(doc, len(chunks), heading, body))
        buffer.clear()

    for line in doc.body.splitlines():
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
        else:
            buffer.append(line)
    flush()
    return chunks


def chunk_fixed(doc: Document, size_tokens: int = 300) -> list[Chunk]:
    """Fixed-size: about `size_tokens` words per chunk, cutting wherever the count lands, headings
    treated as ordinary text. What a generic splitter does, and what the study text warns about."""
    words = doc.body.split()
    chunks: list[Chunk] = []
    for start in range(0, len(words), size_tokens):
        chunks.append(Chunk(doc, len(chunks), None, " ".join(words[start:start + size_tokens])))
    return chunks


RULES = {
    "headings": chunk_by_headings,
    "fixed-300": lambda doc: chunk_fixed(doc, 300),
}


def embed(texts: list[str], model: str = EMBED_MODEL) -> tuple[list[list[float]], str]:
    """Embed through the model gateway. Returns the vectors and the model name the gateway reports.
    Batched, because the gateway and the runtime both prefer a few large calls to many small ones."""
    vectors: list[list[float]] = []
    reported = model
    for start in range(0, len(texts), 32):
        response = requests.post(
            f"{MODELS}/v1/embeddings",
            headers={"Authorization": f"Bearer {MODEL_KEY}"},
            json={"model": model, "input": texts[start:start + 32]},
            timeout=300,
        )
        response.raise_for_status()
        data = response.json()
        reported = data.get("model") or model
        vectors.extend(item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"]))
    return vectors, reported


def connect() -> psycopg.Connection:
    return psycopg.connect(DB)


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"


def load_questions(path: pathlib.Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def load_relevance(path: pathlib.Path) -> dict[int, list[str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["relevance"]
    return {int(k): list(v) for k, v in raw.items()}
