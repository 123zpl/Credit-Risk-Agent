"""
Milvus RAG 初始化脚本
读取指定目录下 .md / .txt 文件 -> 切片 -> Embedding -> 写入 Milvus

示例:
  python scripts/init_rag.py --collection regulation_docs --docs-dir docs/regulations
  python scripts/init_rag.py --collection credit_policies --docs-dir docs/policies

入库前建议运行: python scripts/validate_policy_consistency.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from src.config import settings

EMBEDDING_DIM = 1024


def connect_milvus():
    connections.connect("default", host=settings.milvus_host, port=settings.milvus_port)
    print(f"Connected to Milvus at {settings.milvus_host}:{settings.milvus_port}")


def create_collection(collection_name: str):
    if utility.has_collection(collection_name):
        print(f"Dropping existing collection '{collection_name}'...")
        utility.drop_collection(collection_name)

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=2000),
        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=200),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]
    schema = CollectionSchema(fields, description="RAG document vectors")
    collection = Collection(collection_name, schema)
    print(f"Created collection '{collection_name}'")
    return collection


def load_and_split_docs(docs_dir: Path) -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", "。", "；", " "],
    )

    chunks = []
    doc_files = sorted(set(docs_dir.glob("*.md")) | set(docs_dir.glob("*.txt")))
    if not doc_files:
        print(f"No .md or .txt files found in {docs_dir}")
        return chunks

    for file_path in doc_files:
        content = file_path.read_text(encoding="utf-8")
        doc_chunks = splitter.split_text(content)
        for chunk in doc_chunks:
            chunks.append({"text": chunk.strip(), "source": file_path.stem})
        print(f"  {file_path.name}: {len(doc_chunks)} chunks")

    print(f"Total: {len(chunks)} chunks from {len(doc_files)} files")
    return chunks


def embed_and_insert(collection: Collection, chunks: list[dict]):
    embeddings_model = OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        check_embedding_ctx_length=False,
    )

    texts = [c["text"] for c in chunks]
    sources = [c["source"] for c in chunks]

    batch_size = 6
    total_inserted = 0

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        batch_sources = sources[i : i + batch_size]
        vectors = embeddings_model.embed_documents(batch_texts)
        collection.insert([batch_texts, batch_sources, vectors])
        total_inserted += len(batch_texts)
        print(f"  Inserted batch {i // batch_size + 1}: {total_inserted}/{len(texts)} chunks")

    collection.flush()
    print(f"Flushed. Total documents: {collection.num_entities}")

    index_params = {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128},
    }
    collection.create_index("embedding", index_params)
    collection.load()
    print("Index created and collection loaded")


def main():
    parser = argparse.ArgumentParser(description="Initialize Milvus RAG collection from text docs")
    parser.add_argument(
        "--collection",
        default=settings.milvus_collection,
        help="Milvus collection name (default: regulation_docs)",
    )
    parser.add_argument(
        "--docs-dir",
        default=str(settings.project_root / "docs" / "regulations"),
        help="Directory containing .txt policy/regulation files",
    )
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    collection_name = args.collection

    print("=" * 60)
    print(f"Milvus RAG 初始化: {collection_name}")
    print(f"Docs: {docs_dir}")
    print("=" * 60)

    connect_milvus()
    collection = create_collection(collection_name)
    chunks = load_and_split_docs(docs_dir)

    if not chunks:
        print("No documents to process. Exiting.")
        return

    embed_and_insert(collection, chunks)
    print("\nDone! RAG knowledge base is ready.")


if __name__ == "__main__":
    main()
