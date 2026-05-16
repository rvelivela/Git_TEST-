import os
from pathlib import Path

from docx import Document
from bs4 import BeautifulSoup

from sentence_transformers import SentenceTransformer
import numpy as np
import faiss
import ollama


# =========================
# CONFIG
# =========================
BASE_PATH = rCUsersrvOneDriveDesktopORACLE_STUDY
EMBED_MODEL_NAME = sentence-transformersall-MiniLM-L6-v2
OLLAMA_MODEL = llama3

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 120

DEFAULT_K = 8
SHORT_QUERY_K = 12

DEBUG = True


# =========================
# FILE DISCOVERY
# =========================
def get_all_files(base_path str)
    base = Path(base_path)
    return [str(p) for p in base.rglob() if p.suffix.lower() in {.docx, .html}]


# =========================
# TEXT EXTRACTION
# =========================
def extract_text_from_docx(file_path str) - str
    doc = Document(file_path)
    return n.join(p.text.strip() for p in doc.paragraphs if p.text and p.text.strip())


def extract_text_from_html(file_path str) - str
    with open(file_path, r, encoding=utf-8, errors=ignore) as f
        soup = BeautifulSoup(f, html.parser)

    # remove common noisy elements
    for tag in soup([script, style, nav, footer])
        tag.decompose()

    text = soup.get_text(separator=n)
    lines = [ln.strip() for ln in text.split(n) if ln.strip()]
    return n.join(lines)


# =========================
# TOPIC DETECTION (ROBUST folder-based)
# =========================
def topic_from_path(file_path str) - str
    parts = [p.lower() for p in Path(file_path).parts]

    # normalize common misspellings in folder names
    if data gaurd in parts or data guard in parts or dataguard in parts
        return DATAGUARD
    if rac in parts
        return RAC
    if asm in parts
        return ASM
    if goldengate in parts
        return GOLDENGATE
    if exadata in parts
        return EXADATA
    if db arc in parts or db_arc in parts or architecture in parts
        return DB_ARCH

    return GENERAL


# =========================
# CHUNKING
# =========================
def chunk_text(text str, chunk_size int = CHUNK_SIZE, overlap int = CHUNK_OVERLAP) - list[str]
    chunks = []
    start = 0
    n = len(text)

    while start  n
        end = min(start + chunk_size, n)
        chunk = text[startend].strip()
        if chunk
            chunks.append(chunk)

        start = end - overlap
        if start  0
            start = 0
        if end == n
            break

    return chunks


# =========================
# ROUTER (AGENT)
# =========================
ALIASES = {
    # Data Guard
    dataguard DATAGUARD,
    data guard DATAGUARD,
    datagaurd DATAGUARD,
    dg DATAGUARD,
    standby DATAGUARD,
    redo transport DATAGUARD,
    switchover DATAGUARD,
    failover DATAGUARD,

    # RAC
    rac RAC,
    cache fusion RAC,
    gc  RAC,  # gc cr..., gc current...
    wait event RAC,
    gv$ RAC,
    v$ RAC,
    scan RAC,
    vip RAC,

    # ASM
    asm ASM,
    diskgroup ASM,
    disk group ASM,
    rebalance ASM,

    # GoldenGate
    goldengate GOLDENGATE,
    golden gate GOLDENGATE,
    extract GOLDENGATE,
    replicat GOLDENGATE,

    # Exadata
    exadata EXADATA,

    # DB Architecture
    db architecture DB_ARCH,
    oracle db architecture DB_ARCH,
    sga DB_ARCH,
    pga DB_ARCH,
    controlfile DB_ARCH,
    control file DB_ARCH,
    redo log DB_ARCH,
    background process DB_ARCH,
    dbwr DB_ARCH,
    lgwr DB_ARCH,
    pmon DB_ARCH,
    smon DB_ARCH,
}


def route_topic(query str) - str
    q = query.lower()

    for key, topic in ALIASES.items()
        if key in q
            return topic

    # heuristic if they mention architecture explicitly, treat as DB architecture
    if architecture in q
        return DB_ARCH

    return GENERAL


# =========================
# QUERY EXPANSION (AGENT) — SAFE (NO SQL)
# =========================
def should_expand(query str) - bool
    q = query.lower()

    # If query is already detailed, don't expand
    if len(query.split())  6
        return False

    # Never expand queries with these tokens (they trigger NL2SQL behavior)
    if gv$ in q or v$ in q
        return False
    if architecture in q
        return False

    return True


def _first_sentence(text str) - str
    # take first non-empty line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines
        return text.strip()

    s = lines[0].strip()

    # If model returns Here is ... and then the query on next line, try last line
    if s.lower().startswith((here, sure, rewritten, rewrite, here's, heres)) and len(lines)  1
        s = lines[-1].strip()

    # Keep it short one sentence max
    for sep in [n, . , ؟,  ]
        if sep in s
            s = s.split(sep)[0].strip()

    return s.strip().strip('').strip(')


def expand_query(query str) - str
    prompt = f
You are an Oracle DBA assistant.
Rewrite the user query into ONE short natural-language QUESTION suitable for semantic search.

STRICT RULES
- NEVER generate SQL
- NEVER generate code
- NEVER include SELECT  FROM  WHERE  JOIN
- Return ONE sentence only (no bullet points)

User query {query}
Rewritten query
.strip()

    resp = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{role user, content prompt}]
    )

    expanded_raw = resp[message][content]
    expanded = _first_sentence(expanded_raw)

    # HARD BLOCK if it still looks like SQLcode, skip expansion
    banned = [select, from, where, join, ;, order by, group by]
    if any(b in expanded.lower() for b in banned)
        if DEBUG
            print([DEBUG] SQL-like expansion detected → using original query)
        return query

    # If expansion is empty or weird, fallback
    if len(expanded)  3
        return query

    return expanded


# =========================
# BUILD CORPUS
# =========================
def build_corpus()
    files = get_all_files(BASE_PATH)
    documents = []

    for file_path in files
        try
            if file_path.lower().endswith(.docx)
                text = extract_text_from_docx(file_path)
            else
                text = extract_text_from_html(file_path)

            if not text.strip()
                continue

            documents.append({
                text text,
                source file_path,
                topic topic_from_path(file_path)
            })

        except Exception as e
            print(fError processing {file_path} {e})

    print(Total documents, len(documents))

    chunked = []
    for doc in documents
        for ch in chunk_text(doc[text])
            chunked.append({
                text ch,
                source doc[source],
                topic doc[topic]
            })

    print(Total chunks, len(chunked))
    return chunked


# =========================
# FAISS INDEXING (per-topic)
# =========================
def build_indexes(chunked)
    embed_model = SentenceTransformer(EMBED_MODEL_NAME)

    texts = [c[text] for c in chunked]
    meta = [{source c[source], topic c[topic]} for c in chunked]

    # normalized embeddings → cosine search using inner product
    emb = embed_model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype(float32)

    topic_to_ids = {}
    for i, m in enumerate(meta)
        topic_to_ids.setdefault(m[topic], []).append(i)

    topic_indexes = {}
    for topic, ids in topic_to_ids.items()
        sub = emb[ids]
        idx = faiss.IndexFlatIP(sub.shape[1])  # cosine on normalized vectors
        idx.add(sub)
        topic_indexes[topic] = (idx, ids)

    print(Indexes built for topics, sorted(topic_indexes.keys()))
    return embed_model, texts, meta, topic_indexes


# =========================
# RETRIEVAL
# =========================
def retrieve(query str, embed_model, texts, meta, topic_indexes, k int = DEFAULT_K, topic str  None = None, force_broad bool = False)
    q_emb = embed_model.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype(float32)

    if not force_broad
        if topic is None
            topic = route_topic(query)

        # If topic exists, search that topic
        if topic in topic_indexes
            idx, ids = topic_indexes[topic]
            D, I = idx.search(q_emb, k)
            results = []
            for local_id in I[0]
                if local_id == -1
                    continue
                global_id = ids[local_id]
                results.append({
                    text texts[global_id],
                    source meta[global_id][source],
                    topic meta[global_id][topic]
                })
            return results, topic

    # BROAD search across topics (merge top few from each)
    merged = []
    for t, (idx, ids) in topic_indexes.items()
        D, I = idx.search(q_emb, min(4, k))
        for local_id in I[0]
            if local_id == -1
                continue
            global_id = ids[local_id]
            merged.append({
                text texts[global_id],
                source meta[global_id][source],
                topic meta[global_id][topic]
            })

    # De-dup
    seen = set()
    out = []
    for r in merged
        key = (r[source], r[text][80])
        if key not in seen
            seen.add(key)
            out.append(r)

    return out[k], BROAD


# =========================
# QA (Agentic loop)
# =========================
def ask_question(user_query str, embed_model, texts, meta, topic_indexes)
    # Decide whether to expand
    if should_expand(user_query)
        expanded = expand_query(user_query)
        if DEBUG
            print(n[DEBUG] Expanded Query, expanded)
    else
        expanded = user_query
        if DEBUG
            print(n[DEBUG] Skipped expansion)

    # Adaptive k for short queries
    k = SHORT_QUERY_K if len(user_query.split()) = 4 else DEFAULT_K

    # First retrieval (topic routed)
    results, routed = retrieve(expanded, embed_model, texts, meta, topic_indexes, k=k)

    context = nn.join(r[text] for r in results)

    prompt = f
You are an Oracle DBA expert.
Answer ONLY using the context below.
If the context does not contain the answer, say exactly Not enough information found.

Context
{context}

Question
{user_query}
.strip()

    resp = ollama.chat(model=OLLAMA_MODEL, messages=[{role user, content prompt}])
    answer = resp[message][content].strip()

    # Retry if weak answer
    if not enough information found in answer.lower()
        if DEBUG
            print([DEBUG] Retry triggered → BROAD search)

        broad_results, _ = retrieve(expanded, embed_model, texts, meta, topic_indexes, k=12, force_broad=True)
        context2 = nn.join(r[text] for r in broad_results)

        prompt2 = f
You are an Oracle DBA expert.
Answer ONLY using the context below.
If the context does not contain the answer, say exactly Not enough information found.

Context
{context2}

Question
{user_query}
.strip()

        resp2 = ollama.chat(model=OLLAMA_MODEL, messages=[{role user, content prompt2}])
        answer = resp2[message][content].strip()
        results = broad_results
        routed = BROAD

    return answer, results, routed


# =========================
# CHAT LOOP
# =========================
def chat()
    chunked = build_corpus()
    embed_model, texts, meta, topic_indexes = build_indexes(chunked)

    print(✅ Oracle Agentic RAG Ready)
    print(Type 'exit' to quitn)

    while True
        q = input(You ).strip()
        if q.lower() in {exit, quit, bye}
            print(Bot Goodbye 👋)
            break

        answer, results, topic = ask_question(q, embed_model, texts, meta, topic_indexes)

        print(nBotn, answer)
        print(nTopic, topic)

        print(nSources)
        for s in sorted(set(r[source] for r in results))
            print(-, s)

        print(n + =  60 + n)


if __name__ == __main__
    chat()


