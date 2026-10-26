import asyncio
import html
import logging
import re
import json
from urllib.parse import urlsplit
import webbrowser
from ddgs import DDGS
from .tool_models import ToolResult
from .page_reader import extract_relevant_text, extract_section, fetch_page
from .search_queries import MAX_QUESTION_CHARS, compact_question, search_queries, relevance

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 5
MAX_SEARCH_RESULT_CHARS = 5500
SEARCH_TIMEOUT_SECONDS = 8
SEARCH_BACKENDS = ("auto", "duckduckgo", "yahoo")
SEARCH_BUDGET_SECONDS = 18.0
WEB_TOOL_TIMEOUT_SECONDS = 30.0


class BrowserTools:
    """Browser interactions and bounded keyless web search."""

    def __init__(self, query_client=None):
        self.query_client = query_client

    async def _collect_records(self, question):
        """Use the configured model to propose a concise retrieval probe only.

        The planner sees the user's public search question, never saved memory,
        page instructions or credentials. It cannot execute tools or answer.
        """
        queries = [question]
        if self.query_client is not None:
            prompt = (
                "Create ONE concise web search query, not an answer. Return only JSON: {\"query\": \"...\"}. "
                "Use 6-14 keywords. Example: 'Please compare electric bikes under 900 euros in France and cite sources' "
                "becomes {\"query\": \"electric bikes under 900 EUR France comparison\"}. "
                "Keep the exact product variant, budget, country and requested date. Remove conversational instructions. "
                "For official-source requests use a site: operator for the relevant official organization. "
                "Use English search keywords for multilingual comparisons, but preserve names and amounts. "
                "Do not invent facts, products or URLs. Maximum 180 characters.\nQuestion: " + question
            )
            try:
                raw, metrics = await asyncio.wait_for(self.query_client.generate(prompt, max_tokens=150), 6)
                if metrics.success:
                    start, end = raw.find("{"), raw.rfind("}")
                    planned = json.loads(raw[start:end + 1]).get("query")
                    if isinstance(planned, str) and 3 <= len(planned) <= 180 and not re.search(r"site:\S+/", planned):
                        queries = [planned, question]
                        logger.info("web_query_planned", extra={"query": planned})
            except Exception:
                logger.warning("web_query_plan_unavailable")
        # Explicit source/domain constraints are extracted from the request.
        # No retailer, organization, product, or country is special-cased.
        explicit_domains = re.findall(
            r"(?<![\w.-])([\w-]+\.(?:org|com|gov|edu|net)(?:\.[a-z]{2})?)(?![\w.-])",
            question,
            re.I,
        )
        if explicit_domains:
            probe = search_queries(question)[0]
            queries = list(dict.fromkeys([f"site:{explicit_domains[0]} {probe}", *queries]))
        # Parallel probes share bounded per-probe budgets. The original query
        # remains available if the model's retrieval rewrite is unhelpful.
        batches = await asyncio.gather(*(self._search_records(q, budget=12 if len(queries) > 1 else SEARCH_BUDGET_SECONDS) for q in queries))
        records = {}
        for batch in batches:
            if isinstance(batch, list):
                for record in batch:
                    records.setdefault(str(record.get("href") or record.get("title")), record)
        if not records:
            return batches[-1]
        # Respect explicit official-domain probes and prefer them, without any
        # per-site adapter or hardcoded product catalogue.
        explicit = re.findall(r"\b(?:use|from|site:)\s*([\w-]+\.(?:org|com|gov|edu|net)(?:\.[a-z]{2})?)", question, re.I)
        preferred = explicit or re.findall(r"site:([\w.-]+)", queries[0])
        named_sources = re.findall(r"\b([A-Z][A-Za-z0-9]+) sources\b", question)
        for record in records.values():
            host = urlsplit(str(record.get("href", ""))).hostname or ""
            if any(name.lower() in host.split(".") for name in named_sources):
                preferred.append(host.removeprefix("www."))
        def preferred_host(record):
            host = urlsplit(str(record.get("href", ""))).hostname or ""
            return any(host == d or host.endswith("." + d) for d in preferred)
        def score(record):
            return relevance(record, search_queries(queries[0])[0]) + (1 if preferred_host(record) else 0)
        ordered = sorted(records.values(), key=score, reverse=True)
        if preferred and (explicit or explicit_domains or named_sources or re.search(r"\bofficial\b", question, re.I)):
            preferred_records = [r for r in ordered if preferred_host(r)]
            if preferred_records:
                ordered = preferred_records
        return ordered[:MAX_SEARCH_RESULTS] if ordered else ToolResult(False,
            "I could not verify this from the requested official source. I will not substitute an unofficial claim.", "no_official_results")

    async def open_url(self, url: str) -> ToolResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
        except Exception:
            return ToolResult(False, "", "invalid_url")

        tld = host.rsplit(".", 1)[-1] if "." in host else ""
        if "." not in host or not (tld.isalpha() and len(tld) >= 2):
            return ToolResult(False, "", "invalid_url")

        try:
            # webbrowser.open is blocking in some OS, but usually fine. 
            # We use to_thread to be safe.
            success = await asyncio.to_thread(webbrowser.open, url)
            if success:
                return ToolResult(True, f"Successfully requested browser to open: {url}")
            else:
                return ToolResult(False, "", "Browser failed to launch or open URL")
        except Exception as e:
            return ToolResult(False, "", f"Browser error: {str(e)}")

    async def search_web(self, query: str, max_sources: int | None = None) -> ToolResult:
        """Return up to five short text results without opening a browser."""
        normalized_query = compact_question(query)
        if not normalized_query:
            logger.error("web_search_empty_query")
            return ToolResult(False, "Please give me a search question.", "empty_query")
        if len(normalized_query) > MAX_QUESTION_CHARS:
            return ToolResult(False, "That question is too long to research reliably. Please split it into smaller questions; I have not discarded your constraints.", "query_too_long")

        results = await self._collect_records(normalized_query)
        if isinstance(results, ToolResult):
            return results

        return self._format_results(results)

    async def _search_records(self, normalized_query: str, *, budget=None) -> list[dict[str, object]] | ToolResult:
        results: list[dict[str, object]] = []
        backend_errors: list[str] = []
        last_exception: BaseException | None = None
        deadline = asyncio.get_running_loop().time() + (SEARCH_BUDGET_SECONDS if budget is None else budget)
        queries = search_queries(normalized_query)
        attempts = [(queries[0], backend) for backend in SEARCH_BACKENDS] if queries else []
        if len(queries) > 1:
            attempts += [(queries[1], backend) for backend in SEARCH_BACKENDS]
        successful_queries = set()
        for query, backend in attempts:
            if query in successful_queries:
                continue
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                candidate_results = await asyncio.wait_for(
                    asyncio.to_thread(
                        lambda selected_backend=backend, selected_query=query: DDGS(timeout=SEARCH_TIMEOUT_SECONDS).text(
                            selected_query,
                            max_results=MAX_SEARCH_RESULTS,
                            backend=selected_backend,
                        )
                    ),
                    timeout=min(remaining, SEARCH_TIMEOUT_SECONDS + 0.2),
                )
            except Exception as exc:
                if "no results found" not in str(exc).lower():
                    last_exception = exc
                backend_errors.append(f"{backend}: {exc}")
                logger.warning(
                    "web_search_backend_failed",
                    extra={"backend": backend, "query_length": len(query)},
                )
                continue

            if candidate_results:
                results.extend(candidate_results)
                successful_queries.add(query)
                logger.info(
                    "web_search_backend_succeeded",
                    extra={"backend": backend, "query_length": len(query)},
                )
                if max(relevance(record, query) for record in candidate_results) >= 0.2:
                    break
                # Try the shorter keyword probe when the first results are
                # unrelated. Do not treat a nonempty backend as task success.
                if len(queries) < 2 or query != queries[0]:
                    break
            backend_errors.append(f"{backend}: no_results")

        if not results:
            log_name = "web_search_failed" if last_exception is not None else "web_search_empty_results"
            logger.error(
                log_name,
                extra={
                    "query_length": len(normalized_query),
                    "backends": ",".join(SEARCH_BACKENDS),
                    "errors": " | ".join(backend_errors),
                },
                exc_info=(
                    type(last_exception),
                    last_exception,
                    last_exception.__traceback__,
                )
                if last_exception is not None
                else None,
            )
            if last_exception is None:
                return ToolResult(False, "I found no matching results after trying alternative searches. That does not prove the subject does not exist.", "no_results")
            return ToolResult(False, "I couldn't reach the web right now.", "search_unavailable")

        unique = {}
        for record in results:
            key = str(record.get("href") or record.get("title"))
            unique.setdefault(key, record)
        return sorted(unique.values(), key=lambda item: relevance(item, queries[0]), reverse=True)[:MAX_SEARCH_RESULTS]

    def _format_results(self, results: list[dict[str, object]]) -> ToolResult:
        entries: list[str] = []
        used_chars = 0

        for result in results[:MAX_SEARCH_RESULTS]:
            title = html.escape(" ".join(str(result.get("title", "")).split()), quote=False)
            href = str(result.get("href", "")).strip()
            if not href.startswith(("http://", "https://")):
                href = ""
            snippet = html.escape(" ".join(str(result.get("body", "")).split())[:800], quote=False)
            if not title and not snippet and not href:
                continue
            source = f"\nSource: {html.escape(href, quote=False)}" if href else ""
            entry = f"{len(entries) + 1}. {title}{source}\nEvidence kind: search snippet (page not verified)\nEvidence: {snippet}".strip()
            remaining = MAX_SEARCH_RESULT_CHARS - used_chars
            if remaining <= 0:
                break
            if entries:
                remaining -= 1
            if len(entry) > remaining:
                break  # Never emit a cut-off URL or source block.
            if not entry:
                break
            entries.append(entry)
            used_chars += len(entry) + (1 if len(entries) > 1 else 0)

        if not entries:
            logger.error("web_search_empty_results")
            return ToolResult(False, "The search returned no readable evidence.", "no_results")

        return ToolResult(True, "\n".join(entries)[:MAX_SEARCH_RESULT_CHARS])

    async def research_web(self, query: str, max_sources: int = 3) -> ToolResult:
        """Search, fetch, and extract bounded evidence from multiple sources."""
        normalized_query = compact_question(str(query))
        if not normalized_query:
            return ToolResult(False, "I need a research question first.", "empty_query")
        if len(normalized_query) > MAX_QUESTION_CHARS:
            return ToolResult(False, "That question is too long to research reliably. Please split it into smaller questions; I have not discarded your constraints.", "query_too_long")
        records = await self._collect_records(normalized_query)
        if isinstance(records, ToolResult):
            return records

        try:
            source_limit = max(1, min(int(max_sources), 3))
        except (TypeError, ValueError):
            source_limit = 3
        async def read_source(index, record):
            url = str(record.get("href", "")).strip()
            if not url.startswith(("http://", "https://")):
                return ""
            title = " ".join(str(record.get("title", "")).split())
            html_text = await fetch_page(url)
            excerpt = extract_relevant_text(html_text, search_queries(normalized_query)[0], max_chars=1200) if html_text else ""
            kind = "fetched page" if excerpt else "search snippet (page not verified)"
            snippet = " ".join(str(record.get("body", "")).split())[:500]
            if not excerpt:
                excerpt = snippet
            if not excerpt:
                return ""
            return f"{index}. {title}\nSource: {url}\nEvidence kind: {kind}\nEvidence: {excerpt}" + (f"\nSearch snippet: {snippet}" if html_text and snippet else "")

        evidence = [entry for entry in await asyncio.gather(*(
            read_source(index, record) for index, record in enumerate(records[:source_limit], 1)
        )) if entry]

        if not evidence:
            return ToolResult(False, "I found search results but could not read usable source evidence.", "no_fetchable_sources")
        return ToolResult(True, "\n\n".join(evidence))

    async def open_section(self, url: str, section: str) -> ToolResult:
        """Resolve a static HTML heading, open its anchor, and return evidence."""
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return ToolResult(False, "I need a valid http(s) URL.", "invalid_url")
        if not isinstance(section, str) or not section.strip():
            return ToolResult(False, "I need the section name.", "missing_section")

        html_text = await fetch_page(url)
        if not html_text:
            return ToolResult(False, "I could not fetch that page to find the section.", "page_unavailable")
        excerpt, anchor = extract_section(html_text, section, max_chars=1800)
        if not excerpt:
            return ToolResult(False, f"Section not found: {section}", "section_not_found")

        resolved_url = url.split("#", 1)[0] + (f"#{anchor}" if anchor else "")
        opened = await self.open_url(resolved_url)
        status = "browser_open_requested" if opened.success else "browser_open_failed"
        return ToolResult(
            opened.success,
            f"Section found: {section}\nResolved URL: {resolved_url}\nStatus: {status}\nEvidence: {excerpt}",
            None if opened.success else opened.error,
        )
