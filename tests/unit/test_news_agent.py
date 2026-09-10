import pytest
from src.app.services.news_service import NewsService
from src.app.agents.news_agent import NewsAgent
from src.app.schemas.news import NewsArticleSchema


async def fake_rss_fetcher(source):
    return [
        {
            "source": source.get("name", "Test RSS"),
            "title": "OpenAI LLM Agents improve RAG workflows",
            "url": "https://example.test/openai-rag",
            "content": "OpenAI announced an LLM Agent update for production RAG systems.",
        }
    ]


@pytest.mark.asyncio
async def test_news_service_deduplication():
    service = NewsService()
    
    art1 = NewsArticleSchema(
        title="OpenAI Releases New Model",
        url="https://example.com/art1",
        source_name="Source 1",
        topic="AI",
        content="Same content body text"
    )
    art2 = NewsArticleSchema(
        title="OpenAI Releases New Model (Syndicated)",
        url="https://example.com/art2",
        source_name="Source 2",
        topic="AI",
        content="Same content body text"
    )

    deduped = service.deduplicate_articles([art1, art2])
    assert len(deduped) == 1


@pytest.mark.asyncio
async def test_news_service_relevance_scoring():
    service = NewsService()
    score_high = service.calculate_relevance_score(
        article_title="OpenAI LLM Agents in RAG",
        article_content="Details about OpenAI LLM agents",
        keywords=["OpenAI", "LLM", "RAG"]
    )
    assert score_high >= 70.0

    score_low = service.calculate_relevance_score(
        article_title="Vremea la munte",
        article_content="Soare la Brașov",
        keywords=["OpenAI", "LLM", "RAG"]
    )
    assert score_low < 70.0

    score_title_match = service.calculate_relevance_score(
        article_title="UNITBV publică un anunț important",
        article_content="Actualizare pentru comunitatea academică.",
        keywords=["UNITBV"],
    )
    assert score_title_match >= 70.0


@pytest.mark.asyncio
async def test_news_agent_handle_query():
    agent = NewsAgent(news_service=NewsService(raw_article_fetcher=fake_rss_fetcher))
    res = await agent.handle_news_query("Ce știri importante sunt despre AI?", topic="AI")
    assert "text" in res
    assert res["count"] > 0
    assert "AI" in res["text"] or "Știri" in res["text"]
