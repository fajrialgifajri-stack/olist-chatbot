"""
Ingest review Olist -> Qdrant. Aman di-rerun (ID deterministik, dokumen yang sudah ada dilewati).

Contoh:
  python utils/qdrant/ingest.py --collection olist_data_3 --full --plan     # cek saja, tanpa tulis
  python utils/qdrant/ingest.py --collection olist_test --limit 100         # dry-run kecil
  python utils/qdrant/ingest.py --collection olist_data_3 --full            # ingest penuh
"""
import argparse
import logging
import os
import sys
import time
import uuid
from pathlib import Path

import pandas as pd
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = "/data/final/"
EMBED_MODEL = "text-embedding-3-small"
DIM = 1536
NAMESPACE = uuid.UUID("6f1d5a0e-3c1b-4a53-9a57-0d5d1f3c2b11")
REQUIRED_PREFIX = "olist"  # hanya collection berawalan ini yang boleh ditulis


def setup_logging():
    (HERE / "log").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(HERE / "log" / "ingest.log", mode="a"), logging.StreamHandler()],
    )


def build_docs():
    review = pd.read_csv(DATA_DIR + "olist_review_dataset_final.csv")
    items = pd.read_csv(DATA_DIR + "olist_order_items_dataset_final.csv")
    prod = pd.read_csv(DATA_DIR + "olist_product_dataset_final.csv")
    df = review.merge(items, on="order_id", how="left").merge(prod, on="product_id", how="left")
    df = df.dropna(subset=["product_category_name"])
    df = df.drop_duplicates(subset=["review_id"]).reset_index(drop=True)
    df = df[df["review_translate"].notna()].reset_index(drop=True)

    docs = []
    for r in df.itertuples(index=False):
        category = str(r.product_category_name_english).strip()
        text = str(r.review_translate).strip()
        docs.append({
            "id": str(uuid.uuid5(NAMESPACE, str(r.review_id))),
            "text": f"[product category: {category}] [review: {text}]",
            "metadata": {
                "review_id": str(r.review_id),
                "order_id": str(r.order_id),
                "product_id": str(r.product_id),
                "Product_category": str(r.product_category_name_english),
                "review_score": int(r.review_score),
            },
        })
    return docs


def check_target(client, name):
    """Return (exists, points). Abort kalau target berbahaya."""
    if not name.startswith(REQUIRED_PREFIX):
        sys.exit(f"ABORT: nama collection harus berawalan '{REQUIRED_PREFIX}' (terbaca: '{name}').")
    existing = [c.name for c in client.get_collections().collections]
    if name not in existing:
        return False, 0
    info = client.get_collection(name)
    size = getattr(info.config.params.vectors, "size", None)
    if size != DIM:
        sys.exit(f"ABORT: collection '{name}' sudah ada tapi dimensi vektor bukan {DIM} (terbaca: {size}).")
    pts = info.points_count or 0
    if pts > 0:
        sample, _ = client.scroll(name, limit=1, with_payload=True, with_vectors=False)
        meta = (sample[0].payload or {}).get("metadata", {}) if sample else {}
        if "review_id" not in meta:
            sys.exit(f"ABORT: collection '{name}' berisi data yang bukan format Olist.")
    return True, pts


def find_missing(client, name, docs, exists):
    if not exists:
        return docs
    missing = []
    for i in range(0, len(docs), 500):
        chunk = docs[i:i + 500]
        got = client.retrieve(name, ids=[d["id"] for d in chunk], with_payload=False, with_vectors=False)
        have = {str(p.id) for p in got}
        missing.extend(d for d in chunk if d["id"] not in have)
    return missing


def embed(oa, texts):
    for attempt in range(5):
        try:
            resp = oa.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in resp.data]
        except Exception as e:
            logging.warning(f"embedding gagal (percobaan {attempt + 1}/5): {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)
    raise RuntimeError("embedding gagal setelah 5 percobaan, berhenti. Run ulang untuk melanjutkan.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--plan", action="store_true", help="cek saja: tanpa embed, tanpa tulis")
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--max-tokens", type=int, default=1_200_000)
    ap.add_argument("--grpc", action="store_true", help="pakai gRPC (opt-in)")
    a = ap.parse_args()

    if not a.collection:
        sys.exit("ABORT: nama collection kosong (isi --collection atau QDRANT_COLLECTION di .env).")
    if a.limit and a.full:
        sys.exit("ABORT: pilih salah satu: --limit atau --full.")
    if not (a.limit or a.full):
        sys.exit("ABORT: wajib --limit N atau --full.")

    setup_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    docs = build_docs()
    if a.limit:
        docs = docs[:a.limit]
    logging.info(f"Dokumen disiapkan: {len(docs)} | target collection: {a.collection}")

    client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API"), timeout=60, prefer_grpc=a.grpc)
    exists, pts = check_target(client, a.collection)
    logging.info(f"Collection ada: {exists} | point saat ini: {pts}")

    todo = find_missing(client, a.collection, docs, exists)
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = sum(len(enc.encode(d["text"])) for d in todo)
    logging.info(f"Perlu di-embed: {len(todo)} dokumen | {tokens} token | estimasi ${tokens / 1e6 * 0.02:.4f}")

    if a.plan:
        logging.info("Mode --plan: selesai, tidak ada yang ditulis.")
        return
    if tokens > a.max_tokens:
        sys.exit(f"ABORT: {tokens} token melebihi --max-tokens {a.max_tokens}.")
    if not exists:
        client.create_collection(
            collection_name=a.collection,
            vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        )
        logging.info(f"Collection '{a.collection}' dibuat.")

    client.create_payload_index(
        collection_name=a.collection,
        field_name="metadata.Product_category",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    logging.info("Payload index metadata.Product_category dipastikan ada.")

    if not todo:
        logging.info("Tidak ada yang perlu di-ingest.")
        return

    oa = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    done = 0
    for i in range(0, len(todo), a.batch_size):
        batch = todo[i:i + a.batch_size]
        t0 = time.time()
        vectors = embed(oa, [d["text"] for d in batch])
        t1 = time.time()
        points = [
            PointStruct(id=d["id"], vector=v, payload={"page_content": d["text"], "metadata": d["metadata"]})
            for d, v in zip(batch, vectors)
        ]
        client.upsert(collection_name=a.collection, points=points, wait=True)
        t2 = time.time()
        done += len(batch)
        logging.info(f"Progres: {done}/{len(todo)} | embed {t1 - t0:.1f}s | upsert {t2 - t1:.1f}s")

    final = client.get_collection(a.collection).points_count
    logging.info(f"Selesai. Point di '{a.collection}': {final}")


if __name__ == "__main__":
    main()
