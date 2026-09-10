from typing import Dict, Any, Optional
from src.app.services.news_service import NewsService
from src.app.core.logging import logger


class NewsAgent:
    """
    Specialized News Agent. Handles fetching, deduplicating, scoring, and formatting news for Telegram.
    """

    def __init__(self, news_service: Optional[NewsService] = None):
        self.news_service = news_service or NewsService()

    async def handle_news_query(
        self,
        user_prompt: str,
        topic: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Processes natural language news queries (e.g., 'Ce știri importante sunt despre AI?').
        """
        prompt_lower = user_prompt.lower()
        target_topic = topic

        if not target_topic:
            if "ai" in prompt_lower or "inteligență" in prompt_lower:
                target_topic = "AI"
            elif "embedded" in prompt_lower or "nxp" in prompt_lower:
                target_topic = "Embedded"
            elif "unitbv" in prompt_lower or "universitate" in prompt_lower:
                target_topic = "University"
            elif "python" in prompt_lower or "programare" in prompt_lower:
                target_topic = "Programming"

        logger.info(f"NewsAgent processing news query for topic '{target_topic or 'All Topics'}'...")

        articles = await self.news_service.fetch_and_process_news(topic_filter=target_topic)

        if not articles:
            topic_str = f" despre **{target_topic}**" if target_topic else ""
            return {
                "text": f"📰 **Nu au fost găsite știri noi cu un scor de relevanță peste prag{topic_str}.**",
                "count": 0
            }

        header_topic = f" ({target_topic})" if target_topic else ""
        lines = [f"📰 **Știri relevante de interes{header_topic}**:\n"]

        for idx, art in enumerate(articles, 1):
            score_int = int(art.relevance_score)
            lines.append(f"{idx}. **[{score_int}/100] {art.title}**")
            lines.append(f"   **Sursă**: `{art.source_name}`")
            lines.append(f"   **Rezumat**: {art.summary}")
            lines.append(f"   🔗 [Citește articolul]({art.url})")
            lines.append("")

        return {
            "text": "\n".join(lines),
            "count": len(articles),
            "articles": [a.model_dump() for a in articles]
        }
