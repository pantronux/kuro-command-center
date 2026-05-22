"""Market observation analysis helpers."""
from __future__ import annotations

from typing import Iterable, List

from kuro_backend.market_v2.schemas import MarketObservation, NewsObservation, PriceObservation


def price_observations(observations: Iterable[MarketObservation]) -> List[PriceObservation]:
    return [obs for obs in observations if isinstance(obs, PriceObservation)]


def news_observations(observations: Iterable[MarketObservation]) -> List[NewsObservation]:
    return [obs for obs in observations if isinstance(obs, NewsObservation)]


def average_news_sentiment(observations: Iterable[MarketObservation]) -> float:
    news = news_observations(observations)
    if not news:
        return 0.0
    return sum(item.sentiment_score for item in news) / len(news)


def latest_price_movement(observations: Iterable[MarketObservation]) -> float:
    prices = [item for item in price_observations(observations) if item.pct_change is not None]
    if not prices:
        return 0.0
    prices.sort(key=lambda item: item.freshness_seconds if item.freshness_seconds is not None else 999999)
    return float(prices[0].pct_change or 0.0)


def collect_catalysts(observations: Iterable[MarketObservation]) -> List[str]:
    values: set[str] = set()
    for item in news_observations(observations):
        values.update(item.catalyst_keywords)
    return sorted(values)
