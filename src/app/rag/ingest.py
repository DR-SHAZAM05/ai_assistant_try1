import asyncio
import sys
from src.app.rag.ingestion import IngestionPipeline
from src.app.core.logging import setup_logging, logger

setup_logging()


async def main():
    logger.info("Starting Knowledge Base Ingestion Pipeline...")
    pipeline = IngestionPipeline()
    result = await pipeline.ingest_all()
    
    print("\n==========================================")
    print("  KNOWLEDGE BASE INGESTION REPORT")
    print("==========================================")
    print(f"Total documents found:  {result.get('total_documents', 0)}")
    print(f"Processed documents:    {result.get('processed_documents', 0)}")
    print(f"Skipped / Unchanged:    {result.get('skipped_documents', 0)}")
    print(f"Total chunks created:   {result.get('total_chunks', 0)}")
    print(f"Vectors upserted:       {result.get('upserted_vectors', 0)}")
    print("==========================================\n")


if __name__ == "__main__":
    asyncio.run(main())
