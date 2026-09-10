"""Practice configuration loader supporting dynamic YAML overrides."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from src.app.core.config import settings
from src.app.core.logging import logger

_cached_practice_config: Optional[Dict[str, Any]] = None


def load_practice_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Loads practice configuration from YAML file, with fallback to example file and defaults.
    """
    global _cached_practice_config
    if _cached_practice_config is not None and config_path is None:
        return _cached_practice_config

    candidates = [
        Path(config_path) if config_path else Path("config/practice.yaml"),
        Path("config/practice.example.yaml"),
    ]

    for p in candidates:
        if p.exists():
            try:
                content = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                cfg = content.get("practice", {})
                if cfg:
                    if config_path is None:
                        _cached_practice_config = cfg
                    return cfg
            except Exception as exc:
                logger.warning("Error reading practice config from %s: %s", p, exc)

    # Hardcoded safety fallback
    fallback = {
        "current_academic_year": settings.CURRENT_ACADEMIC_YEAR,
        "keywords": [
            "practica", "practică", "conventie", "convenție",
            "caiet", "adeverinta", "adeverință", "ore", "tutore",
            "colocviu", "erasmus", "staj"
        ],
        "categories": [
            "conventie", "adeverinta", "caiet_practica", "colocviu",
            "companie", "ore_practica", "erasmus", "situatie_speciala"
        ],
        "auto_classification_rules": [
            {"tag": "erasmus", "match_terms": ["erasmus", "mobilitate", "bursa strainatate"]},
            {"tag": "conventie", "match_terms": ["conventie de practica", "semnatura firma", "anexa 1"]},
            {"tag": "caiet", "match_terms": ["caiet de practica", "raport saptamanal", "activitate zilnica"]},
        ]
    }
    if config_path is None:
        _cached_practice_config = fallback
    return fallback


def get_practice_keywords() -> List[str]:
    cfg = load_practice_config()
    return cfg.get("keywords", ["practica", "conventie", "caiet", "erasmus", "colocviu"])


def get_practice_categories() -> List[str]:
    cfg = load_practice_config()
    return cfg.get("categories", ["conventie", "adeverinta", "caiet_practica", "colocviu"])
