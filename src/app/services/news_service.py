"""RSS-driven news collection, ranking, and deterministic summarisation."""

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
import yaml

from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.core.retry import retry_async
from src.app.schemas.news import NewsArticleSchema


RawArticleFetcher = Callable[[Dict[str, Any]], Awaitable[List[Dict[str, Any]]]]


class NewsService:
    """Fetch configured RSS sources; fixtures are injected by tests, never used in runtime."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        llm_provider=None,
        raw_article_fetcher: Optional[RawArticleFetcher] = None,
    ):
        self.config_path = config_path or settings.NEWS_CONFIG_FILE
        self.llm = llm_provider
        self.raw_article_fetcher = raw_article_fetcher or self._fetch_rss_source
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        path = Path(self.config_path)
        if not path.exists():
            example_path = Path("config/news.example.yaml")
            if example_path.exists():
                path = example_path
            else:
                logger.warning("News configuration file does not exist: %s", path)
                return {"enabled": False, "topics": [], "sources": []}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return data.get("news", {})
        except (OSError, yaml.YAMLError) as exc:
            logger.error("Could not read news configuration %s: %s", path, exc)
            return {"enabled": False, "topics": [], "sources": []}

    def compute_fingerprint(self, title: str, content: str) -> str:
        clean_content = re.sub(r"[^a-z0-9]", "", (content or title).lower())
        return hashlib.sha256(clean_content.encode("utf-8")).hexdigest()

    def calculate_relevance_score(self, article_title: str, article_content: str, keywords: List[str]) -> float:
        text = f"{article_title} {article_content}".lower()
        score = 0.0
        for keyword in keywords:
            if keyword.lower() in article_title.lower():
                score += 70.0
            elif keyword.lower() in text:
                score += 20.0
        return min(score, 100.0)

    def deduplicate_articles(self, articles: List[NewsArticleSchema]) -> List[NewsArticleSchema]:
        seen_urls: set[str] = set()
        seen_fingerprints: set[str] = set()
        unique_articles: List[NewsArticleSchema] = []
        for article in articles:
            url_key = article.url.strip().lower()
            fingerprint = article.fingerprint or self.compute_fingerprint(article.title, article.content or "")
            article.fingerprint = fingerprint
            if url_key in seen_urls or fingerprint in seen_fingerprints:
                logger.info("Deduplicated syndicated article: %s", article.title)
                continue
            seen_urls.add(url_key)
            seen_fingerprints.add(fingerprint)
            unique_articles.append(article)
        return unique_articles

    async def fetch_and_process_news(
        self,
        topic_filter: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> List[NewsArticleSchema]:
        if not self.config.get("enabled", True):
            return []

        configured_topics = self.config.get("topics", [])
        raw_items = await self._fetch_raw_articles()
        parsed_articles: List[NewsArticleSchema] = []
        threshold = float(self.config.get("relevance_threshold", 70))

        for item in raw_items:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            content = str(item.get("content") or "").strip()
            if not title or not url:
                continue

            best_topic, best_score = "General", 0.0
            for topic in configured_topics:
                topic_name = topic.get("name", "General")
                if topic_filter and topic_filter.lower() not in topic_name.lower():
                    continue
                score = self.calculate_relevance_score(title, content, topic.get("keywords", []))
                if score > best_score:
                    best_topic, best_score = topic_name, score

            if best_score >= threshold or (topic_filter and best_score > 0):
                parsed_articles.append(
                    NewsArticleSchema(
                        title=title,
                        url=url,
                        source_name=str(item.get("source") or "RSS"),
                        topic=best_topic,
                        published_at=item.get("published_at"),
                        content=content,
                        relevance_score=best_score,
                        fingerprint=self.compute_fingerprint(title, content),
                    )
                )

        results = self.deduplicate_articles(parsed_articles)
        results.sort(key=lambda article: article.relevance_score, reverse=True)
        limit = max_results or int(self.config.get("max_results", settings.NEWS_MAX_RESULTS))
        for article in results[:limit]:
            article.summary = self._extractive_summary(article.content, article.topic)
        return results[:limit]

    async def _fetch_raw_articles(self) -> List[Dict[str, Any]]:
        sources = [source for source in self.config.get("sources", []) if source.get("type", "rss").lower() == "rss"]
        if not sources:
            logger.warning("No RSS news sources are configured")
            return []

        responses = await asyncio.gather(
            *(self._fetch_one_source(source) for source in sources), return_exceptions=True
        )
        articles: List[Dict[str, Any]] = []
        for source, response in zip(sources, responses):
            if isinstance(response, Exception):
                logger.warning("RSS source '%s' failed: %s", source.get("name", source.get("url")), response)
                continue
            articles.extend(response)
        return articles

    async def _fetch_one_source(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await retry_async(
            lambda: self.raw_article_fetcher(source),
            operation_name=f"rss_fetch:{source.get('name', source.get('url', 'unknown'))}",
        )

    async def _fetch_rss_source(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = source.get("url")
        if not url:
            return []
        async with httpx.AsyncClient(
            timeout=settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "academic-ai-assistant/1.0 (+RSS reader)"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        try:
            import feedparser
        except ImportError as exc:
            raise RuntimeError("feedparser is required for RSS news ingestion") from exc

        feed = await asyncio.to_thread(feedparser.parse, response.content)
        if getattr(feed, "bozo", False) and not getattr(feed, "entries", []):
            raise RuntimeError(f"RSS parsing failed: {getattr(feed, 'bozo_exception', 'invalid feed')}")

        articles: List[Dict[str, Any]] = []
        for entry in feed.entries:
            content = self._entry_content(entry)
            articles.append(
                {
                    "source": source.get("name") or getattr(feed.feed, "title", "RSS"),
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "content": content,
                    "published_at": self._entry_published_at(entry),
                }
            )
        return articles

    @staticmethod
    def _entry_content(entry: Any) -> str:
        if entry.get("content"):
            return " ".join(part.get("value", "") for part in entry["content"])
        return entry.get("summary") or entry.get("description") or ""

    @staticmethod
    def _entry_published_at(entry: Any) -> datetime:
        raw_date = entry.get("published") or entry.get("updated")
        if raw_date:
            try:
                parsed = parsedate_to_datetime(raw_date)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _extractive_summary(content: str, topic: str) -> str:
        normalized = re.sub(r"\s+", " ", content).strip()
        if not normalized:
            return f"Articol relevant pentru categoria {topic}."
        return normalized[:360].rstrip() + ("..." if len(normalized) > 360 else "")
