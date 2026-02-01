"""
Builds receipt_embeddings from receipts.body content.

Stub implementation: requires OpenAI client and pgvector. Fill in embedding provider
and batching strategy before running in production.
"""

import os


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")

    # TODO: Implement embedding pipeline.
    # - Requires openai>=1.0 (or alternate provider)
    # - Requires pgvector extension on Postgres
    # - Define receipt text extraction + hashing strategy
    raise NotImplementedError(
        "Embedding job not implemented. Install provider SDK and implement batching."
    )


if __name__ == "__main__":
    main()
