"""Quick check that Milvus collections match src.config settings."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pymilvus import Collection, connections, utility

from src.config import settings
from src.infra.rag_search import search_milvus
from src.underwriting.policy_retrieval import retrieve_policies_payload


def main() -> int:
    connections.connect("default", host=settings.milvus_host, port=settings.milvus_port)

    expected = {
        "regulation (milvus_collection)": settings.milvus_collection,
        "credit_policy (credit_policy_collection)": settings.credit_policy_collection,
    }
    print("Config collection names:")
    for label, name in expected.items():
        exists = utility.has_collection(name)
        count = Collection(name).num_entities if exists else 0
        print(f"  {label}: {name!r} exists={exists} entities={count}")

    sample = {
        "product_type": "借呗",
        "purpose": "家庭装修",
        "requested_amount": 150000,
        "dti": 48,
    }
    payload = retrieve_policies_payload(sample)
    print(f"\nretrieve_policies_payload hits: {payload['命中条款数']}")
    for hit in payload["检索结果"][:3]:
        print(f"  - [{hit.get('collection')}] {hit.get('source')} score={hit.get('score')}")

    q = "利率定价 风险定价 36%"
    reg = search_milvus(settings.milvus_collection, q, top_k=1)
    pol = search_milvus(settings.credit_policy_collection, q, top_k=1)
    if not reg or not pol:
        print("\nERROR: semantic search returned empty for one or both collections")
        return 1

    print("\nOK: both collections searchable and aligned with policy_retrieval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
