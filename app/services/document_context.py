"""Bounded-memory passage retrieval over the whole available document."""
import heapq
import random
import re
import os
from collections import Counter


STOP_WORDS = frozenset(
    "a an and are as at be by can could did do does for from had has have how i "
    "in is it its me more my of on or please should so tell than that the their "
    "them there these they this those to us was were what when where which who "
    "why will with would you your explain summarize summary overview overall".split()
)


def terms(text):
    return {word for word in re.findall(r"[^\W_]{2,}", text.casefold()) if word not in STOP_WORDS}


def normalize_history(history):
    if not isinstance(history, (list, tuple)):
        return []
    messages = []
    for entry in (history or [])[-6:]:
        if not isinstance(entry, dict) or entry.get("role") not in ("user", "assistant"):
            continue
        content = entry.get("content")
        if isinstance(content, str) and content.strip():
            messages.append({"role": entry["role"], "content": content[:800]})
    return messages


def _parts(document_text, filepath):
    if filepath:
        from app.services.content_analyzer import ContentAnalyzer
        if os.path.splitext(filepath)[1].lower() in ContentAnalyzer.TEXT_EXTENSIONS | {".pdf"}:
            yield from ContentAnalyzer.iter_document_text(filepath)
            return
    for start in range(0, len(document_text), 4096):
        yield document_text[start:start + 4096]


def _chunks(parts, size=1200, overlap=200):
    buffer = ""
    for part in parts:
        buffer += part
        while len(buffer) >= size:
            yield buffer[:size]
            buffer = buffer[size - overlap:]
    if buffer.strip():
        yield buffer


def retrieve_context(document_text, query, history=None, filepath=None, budget=6000):
    query_terms = terms(query)
    history_terms = terms(" ".join(message["content"] for message in normalize_history(history)[-3:]))
    ranked = []
    samples = []
    randomizer = random.Random(0)
    last = None
    for index, chunk in enumerate(_chunks(_parts(document_text, filepath))):
        counts = Counter(re.findall(r"[^\W_]{2,}", chunk.casefold()))
        score = sum(3 + min(counts[word], 3) for word in query_terms if word in counts)
        if score:
            score += 1000  # Current-question matches outrank history-only passages.
        score += sum(0.01 for word in history_terms if word in counts)
        if score:
            heapq.heappush(ranked, (score, -index, chunk))
            if len(ranked) > 4:
                heapq.heappop(ranked)
        last = (index, chunk)
        if len(samples) < 3:
            samples.append(last)
        else:
            position = randomizer.randrange(index + 1)
            if position < len(samples):
                samples[position] = last
    if ranked:
        selected = sorted([(-entry[1], entry[2]) for entry in ranked])
    else:
        # Broad questions receive representative passages, including the end,
        # rather than always receiving the beginning of the document.
        selected = sorted(dict(samples + ([last] if last else [])).items())
    return "\n\n".join(
        f"[Document excerpt {index + 1}]\n{chunk}" for index, chunk in selected
    )[:budget]
