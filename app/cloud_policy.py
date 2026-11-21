"""Prepare or search an expiring OpenAI-hosted index of the two synthetic policy editions."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import sys

from openai import APIError, OpenAI
from document_text import read_document
from policy_rag import PACKS, ROOT, embed, passages

STATE = ROOT / ".local" / "rag" / "managed-store-id"


def store_id():
    value = os.environ.get("OPENAI_VECTOR_STORE_ID")
    if not value and STATE.is_file():
        value = STATE.read_text().strip()
    if not value:
        raise ValueError("Prepare the hosted index first: uv run --locked --env-file .env python app/cloud_policy.py")
    return value


def source_manifest():
    docs = []
    for pack, (_, edition) in PACKS.items():
        policy = read_document(ROOT / "fixtures" / "complex" / f"{pack}-policy.pdf")
        docs.extend((edition, p) for p in passages(policy, "P"))
    return docs


def prepare(client):
    docs = source_manifest()
    fingerprint = hashlib.sha256("\n".join(
        f"{e} {p.ref} {p.digest} {p.text}" for e,p in docs).encode()).hexdigest()
    configured = os.getenv("OPENAI_VECTOR_STORE_ID")
    if configured:
        store = client.vector_stores.retrieve(configured)
        if (store.metadata or {}).get("manifest") != fingerprint or store.status != "completed" or store.file_counts.completed != len(docs):
            raise ValueError("Configured store does not contain the completed policy edition manifest")
        return store.id
    # Discover an existing matching index when a teammate has a fresh checkout.
    store = next((s for s in client.vector_stores.list(limit=100)
                  if (s.metadata or {}).get("manifest") == fingerprint and s.status == "completed"
                  and s.file_counts.completed == len(docs)), None)
    if store is None:
        store = client.vector_stores.create(name="ZeroUpfront synthetic policy research", metadata={"manifest":fingerprint},
                                           expires_after={"anchor":"last_active_at","days":7})
        def upload(pair):
            edition, p = pair
            name = f"{edition}-{p.ref}.txt"
            f = client.files.create(file=(name,p.text.encode(),"text/plain"),purpose="assistants",
                                    expires_after={"anchor":"created_at","seconds":30*86400})
            return {"file_id":f.id,"attributes":{"edition":edition,"sha256":p.digest,"ref":p.ref,"page":p.page}}
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                files = list(executor.map(upload,docs))
            batch = client.vector_stores.file_batches.create_and_poll(
                store.id,files=files,poll_interval_ms=1000)
            if batch.status != "completed" or batch.file_counts.completed != len(docs):
                raise ValueError("Hosted policy indexing incomplete. Run setup again before searching.")
        except BaseException:
            client.vector_stores.delete(store.id)
            raise
    STATE.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w",dir=STATE.parent,delete=False) as f:
        f.write(store.id+"\n")
    os.replace(f.name,STATE)
    return store.id


def cloud_retrieve(client, question, edition, chunks, k=4):
    local = {p.ref:p for p in chunks}
    digests = {p.digest for p in chunks}
    if len(digests) != 1:
        raise ValueError("Cloud search requires one pinned policy revision")
    digest = digests.pop()
    results = client.vector_stores.search(store_id(),query=question,max_num_results=min(20,max(3*k,k)),
        filters={"type":"and","filters":[{"type":"eq","key":"edition","value":edition},
                                        {"type":"eq","key":"sha256","value":digest}]})
    candidates = []
    seen = set()
    for hit in results.data:
        meta = hit.attributes or {}
        p = local.get(meta.get("ref"))
        if (p is None or p.page != meta.get("page") or meta.get("sha256") != digest
                or meta.get("edition") != edition):
            raise ValueError("Hosted result does not match the pinned policy source")
        if p.ref not in seen:
            candidates.append(p)
            seen.add(p.ref)
    hosted_count = len(candidates)
    # A Thai query can yield an empty or very short managed shortlist on an
    # English policy. For a small edition, rank all remaining indexed pages too.
    if len(chunks) <= 20 and len(candidates) < len(chunks):
        for attachment in client.vector_stores.files.list(store_id(),filter="completed",limit=100):
            meta = attachment.attributes or {}
            ref = meta.get("ref")
            p = local.get(ref)
            if (p and ref not in seen and meta.get("edition") == edition and
                    meta.get("sha256") == digest and meta.get("page") == p.page):
                candidates.append(p)
                seen.add(ref)
    if not candidates:
        raise ValueError("No indexed evidence for the requested policy revision")
    # The API computes both kinds of vector. Fuse the exact model's cosine order
    # with the hosted search order to retain lexical hits for policy identifiers.
    model = os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-large"
    query, *vectors = embed(client,model,[question]+[p.text for p in candidates])
    cosine = [sum(a*b for a,b in zip(query,v,strict=True)) for v in vectors]
    order = sorted(range(len(candidates)),key=cosine.__getitem__,reverse=True)
    # Missing hosted ranks share the same floor; attachment listing order has
    # no retrieval meaning. Favor the measured bilingual embedding for ordering.
    scores = {i:1/(61+min(i,hosted_count)) + 2/(61+rank) for rank,i in enumerate(order)}
    return [candidates[i] for i in sorted(scores,key=lambda i:(scores[i],cosine[i]),reverse=True)[:k]]


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("Set OPENAI_API_KEY and run with uv run --env-file .env.")
    try:
        ident = prepare(OpenAI(timeout=75,max_retries=1))
        print("Hosted policy index ready. This checkout is configured.")
        print("For another checkout in the same API project, run setup again or set OPENAI_VECTOR_STORE_ID="+ident)
    except APIError as exc:
        sys.exit(f"OpenAI index setup failed: {type(exc).__name__} HTTP {getattr(exc,'status_code','unknown')} ({getattr(exc,'code',None)})")
    except ValueError as exc:
        sys.exit(str(exc))
