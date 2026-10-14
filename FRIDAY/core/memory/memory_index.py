from __future__ import annotations

import math
import re
import time

from core.memory.memory_models import MemoryRecord, MemoryType


class MemoryIndex:
    RELEVANCE_HALF_LIFE_SECONDS = 30 * 24 * 60 * 60
    MIN_RELEVANCE_DECAY = 0.35
    _STOP_WORDS = {"a", "an", "and", "are", "for", "i", "is", "it", "of", "the", "to", "was", "with"}
    _TYPE_WEIGHTS = {
        MemoryType.PINNED_NOTE: 0.35,
        MemoryType.PREFERENCE: 0.30,
        MemoryType.APPROVED_FACT: 0.30,
        MemoryType.ALIAS: 0.15,
        MemoryType.CONVERSATION_SUMMARY: 0.10,
    }

    @classmethod
    def relevance_decay(cls, age_seconds: float) -> float:
        """Apply a 30-day half-life, bounded between 0.35 and 1.0."""
        age = max(0.0, age_seconds)
        return max(cls.MIN_RELEVANCE_DECAY, 2 ** (-age / cls.RELEVANCE_HALF_LIFE_SECONDS))

    @classmethod
    def _terms(cls, text: str) -> set[str]:
        return {
            term
            for term in re.findall(r"[\w'-]+", text.casefold())
            if term not in cls._STOP_WORDS and len(term) > 1
        }

    def is_relevant(self, query: str, record: MemoryRecord) -> bool:
        return self.text_is_relevant(query, record.content)

    @classmethod
    def _terms_match(cls, query_term: str, content_term: str) -> bool:
        if query_term == content_term:
            return True
        if len(query_term) < 3 or len(content_term) < 3:
            return False

        if len(query_term) <= 4 and len(content_term) > len(query_term):
            candidate = content_term[: len(query_term)]
        elif abs(len(query_term) - len(content_term)) <= 1:
            candidate = content_term
        else:
            return False

        if abs(len(query_term) - len(candidate)) > 1:
            return False

        left = right = edits = 0
        while left < len(query_term) and right < len(candidate):
            if query_term[left] == candidate[right]:
                left += 1
                right += 1
                continue
            edits += 1
            if edits > 1:
                return False
            if len(query_term) > len(candidate):
                left += 1
            elif len(candidate) > len(query_term):
                right += 1
            else:
                left += 1
                right += 1

        edits += int(left < len(query_term) or right < len(candidate))
        return edits <= 1

    @classmethod
    def _matched_term_count(cls, query_terms: set[str], content_terms: set[str]) -> int:
        return sum(
            1
            for query_term in query_terms
            if any(cls._terms_match(query_term, content_term) for content_term in content_terms)
        )

    @classmethod
    def text_is_relevant(cls, query: str, content: str) -> bool:
        query_terms = cls._terms(query)
        content_terms = cls._terms(content)
        if not query_terms:
            return False
        required_matches = max(1, math.ceil(len(query_terms) * 0.25))
        return cls._matched_term_count(query_terms, content_terms) >= required_matches

    def rank(self, query: str, records: list[MemoryRecord]) -> list[MemoryRecord]:
        query_terms = self._terms(query)
        if not query_terms:
            return sorted(
                records,
                key=lambda record: (record.created_at, record.id),
                reverse=True,
            )

        normalized_query = " ".join(self._terms_in_order(query))
        now = time.time()

        def score_record(record: MemoryRecord) -> tuple[int, int, float, float, str]:
            normalized_content = " ".join(self._terms_in_order(record.content))
            content_terms = self._terms(record.content)
            matched_terms = self._matched_term_count(query_terms, content_terms)
            exact_phrase = int(bool(normalized_query) and f" {normalized_query} " in f" {normalized_content} ")
            age_seconds = max(0.0, now - record.updated_at)
            decay = self.relevance_decay(age_seconds)
            trust_score = (
                self._TYPE_WEIGHTS.get(record.type, 0.0)
                + max(0.0, min(record.confidence, 1.0)) * 0.5
                + (0.75 if record.explicit_user_approved else 0.0)
            )
            coverage_score = matched_terms / len(query_terms)
            return (
                matched_terms,
                exact_phrase,
                (coverage_score + trust_score) * decay,
                record.updated_at,
                record.id,
            )

        return sorted(records, key=score_record, reverse=True)

    @staticmethod
    def _terms_in_order(text: str) -> list[str]:
        return re.findall(r"[\w'-]+", text.casefold())
