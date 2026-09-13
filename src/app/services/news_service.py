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
from sqlalchemy import select, text

from src.app.core.config import settings
from src.app.core.exceptions import PersistenceException
from src.app.core.logging import logger
from src.app.core.retry import retry_async
from src.app.core.user_scope import require_user_id
from src.app.database.models.models import NewsArticle
from src.app.database.session import AsyncSessionLocal, engine
from src.app.schemas.news import NewsArticleSchema


RawArticleFetcher = Callable[[Dict[str, Any]], Awaitable[List[Dict[str, Any]]]]
_memory_news_articles: Dict[str, Dict[str, NewsArticleSchema]] = {}


class NewsService:
    """Fetch configured RSS sources; fixtures are injected by tests, never used in runtime."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        llm_provider=None,
        raw_article_fetcher: Optional[RawArticleFetcher] = None,
        session_factory=AsyncSessionLocal,
        database_engine=engine,
    ):
        self.config_path = config_path or settings.NEWS_CONFIG_FILE
        self.llm = llm_provider
        self.raw_article_fetcher = raw_article_fetcher or self._fetch_rss_source
        self.config = self._load_config()
        self.session_factory = session_factory
        self.database_engine = database_engine
        self._schema_ready = False
        self._db_available = True

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
        user_id: Optional[str] = None,
    ) -> List[NewsArticleSchema]:
        owner_id = require_user_id(user_id)
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
        selected_articles = results[:limit]
        for article in selected_articles:
            article.summary = self._extractive_summary(article.content or "", article.topic)
        await self.persist_articles(selected_articles, user_id=owner_id)
        return selected_articles

    async def persist_articles(
        self,
        articles: List[NewsArticleSchema],
        user_id: Optional[str] = None,
    ) -> List[NewsArticleSchema]:
        """Upsert RSS results for one Telegram user without sharing feed history."""

        owner_id = require_user_id(user_id)
        if not await self._can_use_database():
            store = _memory_news_articles.setdefault(owner_id, {})
            for article in articles:
                store[article.url] = article.model_copy(deep=True)
            return articles

        try:
            async with self.session_factory() as session:
                for article in articles:
                    existing = await session.scalar(
                        select(NewsArticle).where(
                            NewsArticle.user_id == owner_id,
                            NewsArticle.url == article.url,
                        )
                    )
                    values = {
                        "title": article.title,
                        "source_name": article.source_name,
                        "fingerprint": article.fingerprint,
                        "topic": article.topic,
                        "relevance_score": article.relevance_score,
                        "content": article.content,
                        "summary": article.summary,
                        "published_at": self._naive_datetime(article.published_at),
                    }
                    if existing:
                        for field_name, value in values.items():
                            setattr(existing, field_name, value)
                    else:
                        session.add(NewsArticle(user_id=owner_id, url=article.url, **values))
                await session.commit()
            return articles
        except Exception as exc:
            self._disable_database(exc)
            store = _memory_news_articles.setdefault(owner_id, {})
            for article in articles:
                store[article.url] = article.model_copy(deep=True)
            return articles

    async def list_persisted_articles(
        self,
        user_id: Optional[str] = None,
        topic_filter: Optional[str] = None,
        limit: int = 10,
    ) -> List[NewsArticleSchema]:
        """Read previously persisted news for the current Telegram user only."""

        owner_id = require_user_id(user_id)
        if await self._can_use_database():
            try:
                async with self.session_factory() as session:
                    stmt = select(NewsArticle).where(NewsArticle.user_id == owner_id)
                    if topic_filter:
                        stmt = stmt.where(NewsArticle.topic == topic_filter)
                    stmt = stmt.order_by(NewsArticle.published_at.desc()).limit(limit)
                    result = await session.execute(stmt)
                    return [self._to_schema(row) for row in result.scalars().all()]
            except Exception as exc:
                self._disable_database(exc)

        stored = list(_memory_news_articles.get(owner_id, {}).values())
        if topic_filter:
            stored = [article for article in stored if article.topic == topic_filter]
        return stored[:limit]

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
            if isinstance(response, BaseException):
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

    @staticmethod
    def _naive_datetime(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @staticmethod
    def _to_schema(article: NewsArticle) -> NewsArticleSchema:
        return NewsArticleSchema(
            id=article.id,
            title=article.title,
            url=article.url,
            source_name=article.source_name,
            topic=article.topic,
            published_at=article.published_at,
            content=article.content,
            summary=article.summary,
            relevance_score=article.relevance_score or 0.0,
            fingerprint=article.fingerprint,
        )

    async def _can_use_database(self) -> bool:
        if not self._db_available:
            if not settings.persistence_fallback_allowed:
                raise PersistenceException("News database is unavailable")
            return False
        if self._schema_ready:
            return True
        try:
            async with self.database_engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            self._schema_ready = True
            return True
        except Exception as exc:
            self._disable_database(exc)
            return False

    def _disable_database(self, exc: Exception) -> None:
        if self._db_available:
            logger.warning("News database unavailable; using memory fallback (%s).", type(exc).__name__)
        self._db_available = False
        if not settings.persistence_fallback_allowed:
            raise PersistenceException(f"News database is unavailable: {exc}") from exc
