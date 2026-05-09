from core.memory.memory_models import MemoryRecord


class MemoryIndex:
    def rank(self, query: str, records: list[MemoryRecord]) -> list[MemoryRecord]:
        """
        Ranks memories deterministically based on:
        1. Exact match (case-insensitive)
        2. Recency (created_at)
        3. Confidence
        """
        if not query:
            return sorted(records, key=lambda r: (r.created_at, r.confidence), reverse=True)

        def score_record(record: MemoryRecord) -> tuple:
            query_lower = query.lower()
            content_lower = record.content.lower()

            # Exact match score
            exact_match = 1 if query_lower in content_lower else 0

            # Tie-break with recency and confidence
            return (exact_match, record.created_at, record.confidence)

        return sorted(records, key=score_record, reverse=True)
