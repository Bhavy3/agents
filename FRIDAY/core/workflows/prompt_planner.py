import json
import os
import re
import time
from typing import Any, Optional

import httpx
from ..llm.ollama_client import OllamaClient
from ..logging.logger import get_logger
from ..tools.tool_registry import ToolRegistry
from .planner import BoundedPlanner
from core.skills.loader import SkillLoader

# A goal that names another platform is not a request to scaffold a static site,
# even when the word "website" appears in it ("checks a website every hour").
# Without this guard the deterministic fallback hijacks such goals and reports
# success for work the user never asked for.
_FOREIGN_PLATFORM = re.compile(
    r"\b(?:n8n|zapier|airflow|make\.com|docker|docker-compose|kubernetes|k8s|"
    r"wordpress|shopify|jenkins|terraform|ansible|github\s+actions?|"
    r"aws|azure|gcp|salesforce|supabase|firebase)\b"
)


class PromptPlanner:
    """High-level interface for creating plans from user intent."""

    def __init__(
        self,
        ollama_client: OllamaClient,
        tool_registry: Optional[ToolRegistry] = None,
        skill_loader: SkillLoader | None = None,
        strong_ollama_client: OllamaClient | None = None,
    ):
        self.planner = BoundedPlanner(ollama_client, tool_registry=tool_registry)
        # Planning is one slow call; execution is many fast ones. A larger
        # model may author the plan while the small model still runs the turn.
        self.strong_planner = (
            BoundedPlanner(strong_ollama_client, tool_registry=tool_registry)
            if strong_ollama_client is not None
            else None
        )
        self.last_planner_backend: Optional[str] = None
        self._strong_health_checked_at = 0.0
        self._strong_healthy = False
        self.skill_loader = skill_loader or SkillLoader()
        self.last_rejection_reason: Optional[str] = None
        # The validator's own words, so a refusal can say why instead of
        # collapsing every failure into one vague sentence.
        self.last_rejection_detail: Optional[str] = None
        self.logger = get_logger("workflows.prompt_planner")

    async def create_plan_for_goal(self, goal: str) -> list[dict[str, Any]]:
        """Decomposes a user goal into a list of executable tool steps."""
        self.last_rejection_reason = None
        self.last_rejection_detail = None
        skill_name = self._skill_for_goal(goal)
        skill = self.skill_loader.load(skill_name) if skill_name else None
        skill_context = skill.instructions if skill else ""
        fallback = self._deterministic_fallback(goal)
        if fallback and any(
            step.get("intent") == "browser_open"
            and str(step.get("parameters", {}).get("url", "")).startswith("workspace://")
            for step in fallback
        ):
            self.last_planner_backend = "deterministic_website_build"
            self.logger.info("website_build_plan_selected", extra={"backend": self.last_planner_backend})
            return fallback
        planner = self._planner_for_planning()
        prompt = planner._build_prompt(goal, skill_context=skill_context)
        try:
            response, metrics = await planner.ollama.generate(prompt, max_tokens=700)
            if not metrics.success or not response:
                self.last_rejection_reason = "llm_error"
                self.logger.error(
                    "workflow_planning_generation_failed",
                    extra={"error": metrics.error or "empty_response"},
                )
                return []
            clean_json = response.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0]
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0]
            clean_json = clean_json.strip()
            try:
                parsed = json.loads(clean_json)
            except Exception:
                # Truncated/off-task JSON: fall back to the deterministic plan
                # for low-ambiguity goals instead of failing the turn.
                fallback = self._deterministic_fallback(goal)
                if fallback is not None:
                    self.last_rejection_reason = None
                    self.logger.info("workflow_plan_deterministic_fallback", extra={"trigger": "invalid_json"})
                    return fallback
                self.last_rejection_reason = "invalid_json"
                self.logger.warning(
                    "workflow_plan_rejected",
                    extra={"reason": "invalid_json", "response_excerpt": clean_json[:200]},
                )
                return []
            try:
                return planner.validate_plan(parsed, original_goal=goal)
            except ValueError as first_error:
                if "impossible:" in str(first_error):
                    self.last_rejection_reason = "impossible"
                    self.last_rejection_detail = str(first_error).split("impossible:", 1)[1].strip()
                    self.logger.info("workflow_plan_refused_impossible", extra={"reason": self.last_rejection_detail})
                    return []
                # Small local models often produce a plausible first draft
                # with too many steps or one wrong tool argument. Give the
                # same model one bounded correction pass; never execute the
                # unvalidated draft.
                repair_prompt = (
                    f"{prompt}\n\nThe previous draft was rejected with this validation error:\n"
                    f"{first_error}\n"
                    "Return a corrected JSON list only. Keep at most 5 steps. "
                    "Use exact tool names and exact required parameters. Remove any step "
                    "that is not necessary for the user's goal."
                )
                repaired, repair_metrics = await planner.ollama.generate(
                    repair_prompt,
                    max_tokens=700,
                )
                if not repair_metrics.success or not repaired:
                    raise first_error
                repaired_json = repaired.strip()
                if "```json" in repaired_json:
                    repaired_json = repaired_json.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in repaired_json:
                    repaired_json = repaired_json.split("```", 1)[1].split("```", 1)[0].strip()
                repaired_plan = json.loads(repaired_json)
                return planner.validate_plan(repaired_plan, original_goal=goal)
        except ValueError as ve:
            self.logger.warning(
                "workflow_plan_rejected",
                extra={"reason": str(ve)[:200]},
            )
            fallback = self._deterministic_fallback(goal)
            if fallback is not None:
                self.last_rejection_reason = None
                self.last_rejection_detail = None
                return fallback
            self.last_rejection_detail = str(ve)[:300]
            if "impossible:" in str(ve):
                self.last_rejection_reason = "impossible"
                self.last_rejection_detail = str(ve).split("impossible:", 1)[1].strip()
            elif "cannot be empty" in str(ve) or parsed == []:
                self.last_rejection_reason = "invalid_plan"
            elif "remember_not_authorized" in str(ve):
                self.last_rejection_reason = "remember_not_authorized"
            elif "unsafe_parameter_substitution" in str(ve):
                self.last_rejection_reason = "unsafe_parameter_substitution"
            else:
                self.last_rejection_reason = "invalid_plan"
            return []
        except Exception:
            self.logger.exception("workflow_planning_generation_failed")
            fallback = self._deterministic_fallback(goal)
            if fallback is not None:
                self.last_rejection_reason = None
                return fallback
            self.last_rejection_reason = "llm_error"
            return []

    def _strong_planner_enabled(self) -> bool:
        configured = (os.getenv("FRIDAY_PLANNER_MODEL") or "").strip().lower()
        return configured in ("7b", "strong", "large")

    def _endpoint_healthy(self) -> bool:
        """True when the strong planner's server answers; cached briefly."""
        now = time.monotonic()
        if now - self._strong_health_checked_at < 15.0:
            return self._strong_healthy
        self._strong_health_checked_at = now
        base_url = getattr(getattr(self.strong_planner, "ollama", None), "base_url", "") or ""
        try:
            with httpx.Client(timeout=1.5) as client:
                self._strong_healthy = client.get(f"{base_url.rstrip('/')}/v1/models").status_code == 200
        except Exception as exc:
            # Not an error: the strong model is optional. Never let a missing
            # sidecar break planning, and say why in the log.
            self._strong_healthy = False
            self.logger.info(
                "planner_strong_unavailable",
                extra={"base_url": base_url, "error": f"{type(exc).__name__}: {exc}"},
            )
        return self._strong_healthy

    def _planner_for_planning(self) -> BoundedPlanner:
        """Pick who authors the plan. Execution is unaffected by this choice."""
        if self.strong_planner is None or not self._strong_planner_enabled():
            self.last_planner_backend = "primary"
            return self.planner
        if not self._endpoint_healthy():
            self.last_planner_backend = "primary_strong_unavailable"
            return self.planner
        self.last_planner_backend = "strong"
        self.logger.info("planner_backend_selected", extra={"backend": "strong"})
        return self.strong_planner

    @staticmethod
    def _deterministic_fallback(goal: str) -> list[dict[str, Any]] | None:
        """Return small, verifiable plans for common low-ambiguity requests."""
        normalized = " ".join(goal.casefold().split())
        # n8n is a foreign platform for the website scaffold, but it is a real
        # capability: build the automation directly instead of refusing.
        n8n_plan = PromptPlanner._n8n_plan(normalized)
        if n8n_plan is not None:
            return n8n_plan
        if _FOREIGN_PLATFORM.search(normalized):
            return None
        if re.search(r"\b(?:build|create|make|scaffold)\b", normalized) and re.search(
            r"\b(?:website|web site|static site)\b", normalized
        ):
            match = re.search(r"\b(?:called|named)\s+([a-z0-9_-]+)", normalized)
            if match:
                requested_name = match.group(1)
                project = f"{requested_name}-{time.time_ns()}"
                headline = requested_name.replace("-", " ").replace("_", " ").title()
            else:
                # "build me a simple food website" is about food, not about a
                # thing called "website". Use the subject for the page and the
                # folder so the scaffold is not a placeholder.
                subject = PromptPlanner._website_subject(normalized)
                slug = re.sub(r"[^a-z0-9]+", "-", subject).strip("-") or "website"
                project = f"{slug}-{time.time_ns()}"
                headline = subject.title() if subject else "Website"
            return [
                {
                    "intent": "write_text_file",
                    "parameters": {
                        "file_path": f"{project}/index.html",
                        "content": PromptPlanner._website_page(headline, project),
                    },
                },
                {
                    "intent": "write_text_file",
                    "parameters": {
                        "file_path": f"{project}/style.css",
                        "content": PromptPlanner._website_styles(),
                    },
                },
                {
                    "intent": "write_text_file",
                    "parameters": {
                        "file_path": f"{project}/app.js",
                        "content": PromptPlanner._website_script(headline),
                    },
                },
                {"intent": "browser_open", "parameters": {"url": f"workspace://{project}/index.html"}},
                {"intent": "browser_snapshot", "parameters": {}},
            ]
        if re.search(r"\b(?:build|create|make|scaffold)\b", normalized) and re.search(
            r"\b(?:folder|directory|project)\b", normalized
        ):
            # "create a project folder called X containing main.py, README.md ..."
            match = re.search(r"\b(?:called|named)\s+([a-z0-9_-]+)", normalized)
            project = match.group(1) if match else "project"
            file_names = re.findall(
                r"\b[a-z0-9_-]{1,40}\.(?:py|md|txt|html|json|js|css)\b", normalized
            )[:5]
            if file_names:
                steps: list[dict[str, Any]] = []
                for file_name in file_names:
                    steps.append({
                        "intent": "write_text_file",
                        "parameters": {
                            "file_path": f"{project}/{file_name}",
                            "content": PromptPlanner._scaffold_content(file_name, project),
                        },
                    })
                return steps
        if re.search(r"\b(?:navigate|open)\b", normalized) and re.search(
            r"\b(?:title|page\s+name)\b", normalized
        ):
            url_match = re.search(r"\b(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?", goal, re.I)
            if url_match:
                url = url_match.group(0)
                if not url.startswith(("http://", "https://")):
                    url = f"https://{url}"
                return [
                    {"intent": "browser_open", "parameters": {"url": url}},
                    {"intent": "browser_snapshot", "parameters": {}},
                ]
        return None

    # Words that describe the request rather than the subject of the site.
    _WEBSITE_FILLER = frozenset(
        {
            "a", "an", "the", "me", "my", "our", "please", "simple", "basic",
            "small", "little", "static", "new", "full", "own", "single", "quick",
            "modern", "personal", "clean", "nice", "good", "landing", "plan",
            "and", "then", "start", "coding", "for", "to", "of", "with", "about",
            "build", "create", "make", "scaffold", "called", "named",
        }
    )

    @staticmethod
    def _website_subject(normalized: str) -> str:
        """Return what the site is about, e.g. 'food' from 'a food website'."""
        match = re.search(r"\b([a-z0-9]+)\s+(?:website|web\s*site|static\s+site|site)\b", normalized)
        if match and match.group(1) not in PromptPlanner._WEBSITE_FILLER:
            return match.group(1)
        about = re.search(r"\babout\s+([a-z0-9][a-z0-9 -]{0,30})", normalized)
        if about:
            words = [w for w in about.group(1).split() if w not in PromptPlanner._WEBSITE_FILLER]
            if words:
                return " ".join(words[:2])
        return ""

    @staticmethod
    def _website_page(headline: str, slug: str) -> str:
        """Build a complete static page that can be opened from the workspace."""
        return (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{headline}</title>\n"
            f"<link rel=\"stylesheet\" href=\"style.css\">\n</head>\n<body>\n"
            f"<header>\n<h1>{headline}</h1>\n"
            f"<p class=\"tagline\">Seasonal plates, thoughtful ingredients, and a warm welcome.</p>\n"
            "</header>\n<main>\n"
            f"<h2>Our kitchen</h2>\n<p>{headline} brings familiar favorites together "
            "with fresh ingredients and a little creativity. Explore today's featured dishes below.</p>\n"
            "<h2>Featured dishes</h2>\n<ul id=\"menu\" aria-live=\"polite\"></ul>\n"
            "</main>\n"
            f"<footer>\n<p>{headline} &mdash; scaffolded by FRIDAY.</p>\n</footer>\n"
            "<script src=\"app.js\" defer></script>\n"
            "</body>\n</html>\n"
        )

    @staticmethod
    def _website_styles() -> str:
        return (
            ":root{font-family:system-ui,sans-serif;color:#1d1f24;background:#fbfaf7}"
            "body{margin:0;font-size:16px;line-height:1.6}"
            "header,main,footer{max-width:46rem;margin:0 auto;padding:1.5rem}"
            "header{padding-top:3.5rem}h1{font-size:clamp(2rem,5vw,3rem);margin:0}"
            ".tagline{color:#5c616b}h2{margin-top:2rem}"
            "#menu{display:grid;gap:.75rem;padding:0;list-style:none}"
            "#menu li{padding:1rem;background:white;border:1px solid #e2ded6;border-radius:.75rem}"
            "footer{margin-top:3rem;border-top:1px solid #e2ded6;color:#5c616b}\n"
        )

    @staticmethod
    def _website_script(headline: str) -> str:
        dishes = (
            ("Roasted tomato soup", "$9"),
            ("Herb garden pasta", "$16"),
            ("Warm apple tart", "$8"),
        )
        rows = ",\n".join(
            f"  {{ name: {json.dumps(name)}, price: {json.dumps(price)} }}"
            for name, price in dishes
        )
        return (
            f"// Featured menu for {headline}.\n"
            f"const dishes = [\n{rows}\n];\n"
            "const menu = document.querySelector('#menu');\n"
            "for (const dish of dishes) {\n"
            "  const item = document.createElement('li');\n"
            "  item.textContent = `${dish.name} - ${dish.price}`;\n"
            "  menu.append(item);\n"
            "}\n"
        )

    @staticmethod
    def _n8n_plan(normalized: str) -> list[dict[str, Any]] | None:
        """Build a real n8n workflow from a plain schedule request.

        The small model only ever sent a name, which produced an empty
        workflow. A schedule request always needs at least a trigger node.
        """
        if not re.search(r"\bn8n\b", normalized) or not re.search(r"\bworkflow\b", normalized):
            return None
        if not re.search(r"\b(?:create|build|make|add|set\s+up|schedule)\b", normalized):
            return None

        name_match = re.search(r"\bcalled\s+([a-z0-9 _-]{2,40}?)(?:\s+that|\s+which|$)", normalized)
        name = name_match.group(1).strip().title() if name_match else "FRIDAY workflow"

        hour = 9
        at = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", normalized)
        if at:
            candidate = int(at.group(1))
            if "pm" in normalized and candidate < 12:
                candidate += 12
            if 0 <= candidate <= 23:
                hour = candidate
        minute = int(at.group(2)) if at and at.group(2) else 0
        cron = f"{minute} {hour} * * *"

        workflow = {
            "name": name,
            "nodes": [
                {
                    "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": cron}]}},
                    "name": "Schedule trigger",
                    "type": "n8n-nodes-base.scheduleTrigger",
                    "typeVersion": 1.2,
                    "position": [0, 0],
                }
            ],
            "connections": {},
        }
        return [
            {
                "intent": "n8n_create_workflow",
                "parameters": {"name": name, "workflow_json": json.dumps(workflow)},
            }
        ]

    @staticmethod
    def _scaffold_content(file_name: str, project: str) -> str:
        if file_name.endswith(".py"):
            return (
                f'"""{project} entry point."""\n\n\ndef main() -> None:\n'
                '    print("hello")\n\n\n'
                'if __name__ == "__main__":\n    main()\n'
            )
        if file_name.endswith(".md"):
            return f"# {project}\n\nScaffold created by FRIDAY.\n"
        if file_name.endswith(".html"):
            return (
                "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
                f"<title>{project}</title>\n</head>\n<body>\n<h1>{project}</h1>\n</body>\n</html>\n"
            )
        if file_name.endswith(".json"):
            return "{}\n"
        return "\n"

    @staticmethod
    def _skill_for_goal(goal: str) -> str | None:
        normalized = goal.casefold()
        if any(word in normalized for word in ("desktop", "app", "window", "click", "type")):
            return "desktop"
        if any(word in normalized for word in ("website", "web site", "browser", "chrome", "url")):
            return "browser"
        if any(word in normalized for word in ("code", "coding", "project", "build", "implement", "file")):
            return "coding"
        return "project_building"
