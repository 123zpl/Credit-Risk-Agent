"""Unified Milvus semantic search for regulation and credit policy collections."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_milvus_collection(collection_name: str) -> Any | None:
    """Connect to a Milvus collection; return None if unavailable."""
    try:
        from pymilvus import Collection, connections, utility

        from src.config import settings

        connections.connect(
            "default",
            host=settings.milvus_host,
            port=settings.milvus_port,
            timeout=3,
        )
        if not utility.has_collection(collection_name):
            logger.warning("Collection '%s' does not exist", collection_name)
            return None
        return Collection(collection_name)
    except Exception as e:
        logger.warning("Milvus connection failed: %s", e)
        return None


def search_milvus(collection_name: str, query: str, top_k: int = 5) -> list[dict]:
    """Semantic search on a Milvus collection.

    Each hit: {"text": str, "source": str, "score": float}

    Returns empty list when Milvus or embeddings are unavailable.
    """
    collection = get_milvus_collection(collection_name)
    if collection is None:
        return []

    try:
        from langchain_openai import OpenAIEmbeddings

        from src.config import settings

        embeddings = OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            check_embedding_ctx_length=False,
        )
        query_vector = embeddings.embed_query(query)

        collection.load()
        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"nprobe": 16}},
            limit=top_k,
            output_fields=["text", "source"],
        )

        hits: list[dict] = []
        for hit in results[0]:
            hits.append({
                "text": hit.entity.get("text"),
                "source": hit.entity.get("source"),
                "score": round(hit.distance, 4),
            })
        return hits
    except Exception as e:
        logger.warning("Milvus search failed on '%s': %s", collection_name, e)
        return []
