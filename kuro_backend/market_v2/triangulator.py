"""Triangulation engine for Market Sentinel V2."""
from __future__ import annotations

from typing import Dict, Iterable, List

from kuro_backend.market_v2 import analyzer
from kuro_backend.market_v2.freshness import downgrade_confidence, is_stale, utc_now_iso
from kuro_backend.market_v2.schemas import (
    MarketObservation,
    MarketSentinelReport,
    MarketSignal,
    SourceReliabilityScore,
)


NOT_FINANCIAL_ADVICE = "Not financial advice. This is a watchlist signal with uncertainty."


class MarketTriangulator:
    def __init__(self, *, stale_threshold_seconds: float = 3600.0) -> None:
        self.stale_threshold_seconds = stale_threshold_seconds

    def build_report(
        self,
        *,
        symbol: str,
        username: str,
        workspace_id: str,
        observations: List[MarketObservation],
    ) -> MarketSentinelReport:
        reliability = self.score_reliability(observations)
        signal = self.triangulate_signal(symbol=symbol, observations=observations)
        evidence_table = self.build_evidence_table(observations)
        source_list = self.build_source_list(observations, reliability)
        freshness_warnings = self.freshness_warnings(observations)
        summary = self.summarize(symbol=symbol, signal=signal, observations=observations)
        report = MarketSentinelReport(
            username=username,
            workspace_id=workspace_id,
            symbol=symbol,
            generated_at=utc_now_iso(),
            summary=summary,
            evidence_table=evidence_table,
            source_list=source_list,
            freshness_warnings=freshness_warnings,
            confidence=signal.confidence_score,
            signal=signal,
            observations=observations,
            reliability_scores=reliability,
            insufficient_evidence=signal.insufficient_evidence,
            disclaimer=NOT_FINANCIAL_ADVICE,
        )
        return report.model_copy(update={"report_markdown": self.render_markdown(report)})

    def triangulate_signal(self, *, symbol: str, observations: Iterable[MarketObservation]) -> MarketSignal:
        rows = list(observations)
        source_ids = {row.source_id for row in rows if row.confidence_score >= 0.25}
        price_move = analyzer.latest_price_movement(rows)
        news_score = analyzer.average_news_sentiment(rows)
        stale = any(is_stale(row.freshness_seconds, threshold_seconds=self.stale_threshold_seconds) for row in rows)

        price_dir = 1 if price_move > 1.0 else (-1 if price_move < -1.0 else 0)
        news_dir = 1 if news_score > 0.2 else (-1 if news_score < -0.2 else 0)
        contradiction = bool(price_dir and news_dir and price_dir != news_dir)
        insufficient = len(source_ids) < 2 or not rows

        if insufficient:
            direction = "insufficient_evidence"
        elif contradiction:
            direction = "watchlist_signal_neutral"
        elif price_dir > 0 or news_dir > 0:
            direction = "watchlist_signal_up"
        elif price_dir < 0 or news_dir < 0:
            direction = "watchlist_signal_down"
        else:
            direction = "watchlist_signal_neutral"

        avg_conf = sum(row.confidence_score for row in rows) / max(1, len(rows))
        agreement = 0.35 if contradiction else (0.55 if insufficient else 0.82)
        if abs(price_move) > 3.0 and (news_dir == price_dir or news_dir == 0):
            agreement = min(1.0, agreement + 0.08)
        confidence = avg_conf * agreement
        if stale:
            confidence = downgrade_confidence(confidence, stale=True)
        if insufficient:
            confidence = min(confidence, 0.35)
        if contradiction:
            confidence = min(confidence, 0.45)

        reasons: List[str] = []
        if price_move:
            reasons.append(f"price movement {price_move:.2f}%")
        if news_score:
            reasons.append(f"news sentiment {news_score:.2f}")
        if contradiction:
            reasons.append("contradictory price/news signals")
        if stale:
            reasons.append("stale source data detected")
        if insufficient:
            reasons.append("insufficient independent evidence")

        return MarketSignal(
            symbol=symbol,
            direction=direction,
            confidence_score=round(max(0.0, min(1.0, confidence)), 3),
            source_agreement_score=round(agreement, 3),
            contradiction_detected=contradiction,
            stale_data_detected=stale,
            insufficient_evidence=insufficient,
            reasons=reasons,
            catalyst_keywords=analyzer.collect_catalysts(rows),
        )

    def score_reliability(self, observations: Iterable[MarketObservation]) -> List[SourceReliabilityScore]:
        buckets: Dict[str, List[MarketObservation]] = {}
        for row in observations:
            buckets.setdefault(row.source_id, []).append(row)
        scores: List[SourceReliabilityScore] = []
        for source_id, rows in sorted(buckets.items()):
            stale_rows = [
                row
                for row in rows
                if is_stale(row.freshness_seconds, threshold_seconds=self.stale_threshold_seconds)
            ]
            avg = sum(row.confidence_score for row in rows) / max(1, len(rows))
            stale = bool(stale_rows)
            score = downgrade_confidence(avg, stale=stale)
            scores.append(
                SourceReliabilityScore(
                    source_id=source_id,
                    score=round(score, 3),
                    stale=stale,
                    reason="stale source data" if stale else "source returned usable evidence",
                )
            )
        return scores

    def build_evidence_table(self, observations: Iterable[MarketObservation]) -> List[Dict]:
        evidence: List[Dict] = []
        for row in observations:
            evidence.append(
                {
                    "source_id": row.source_id,
                    "type": row.observation_type,
                    "symbol": row.symbol,
                    "observed_at": row.observed_at,
                    "confidence": row.confidence_score,
                    "freshness_seconds": row.freshness_seconds,
                    "source_url": row.source_url,
                    "value": row.value_json,
                }
            )
        return evidence

    def build_source_list(
        self,
        observations: Iterable[MarketObservation],
        reliability: List[SourceReliabilityScore],
    ) -> List[Dict]:
        by_score = {score.source_id: score for score in reliability}
        seen: set[str] = set()
        sources: List[Dict] = []
        for row in observations:
            if row.source_id in seen:
                continue
            seen.add(row.source_id)
            score = by_score.get(row.source_id)
            sources.append(
                {
                    "source_id": row.source_id,
                    "source_url": row.source_url,
                    "reliability": score.score if score else row.confidence_score,
                    "stale": score.stale if score else False,
                }
            )
        return sources

    def freshness_warnings(self, observations: Iterable[MarketObservation]) -> List[str]:
        warnings: List[str] = []
        for row in observations:
            if is_stale(row.freshness_seconds, threshold_seconds=self.stale_threshold_seconds):
                warnings.append(f"{row.source_id} data for {row.symbol} may be stale.")
        return warnings

    def summarize(self, *, symbol: str, signal: MarketSignal, observations: List[MarketObservation]) -> str:
        if signal.insufficient_evidence:
            return f"{symbol}: insufficient evidence for a grounded market signal."
        base = f"{symbol}: {signal.direction.replace('_', ' ')} with confidence {signal.confidence_score:.2f}."
        if signal.contradiction_detected:
            base += " Price and qualitative signals conflict, so confidence is reduced."
        return base

    def render_markdown(self, report: MarketSentinelReport) -> str:
        lines = [
            f"# Market Sentinel V2 Report: {report.symbol}",
            "",
            report.summary,
            "",
            f"Confidence: {report.confidence:.2f}",
            "",
            "## Evidence",
        ]
        for row in report.evidence_table:
            lines.append(
                f"- {row['source_id']} ({row['type']}): confidence {row['confidence']}, observed {row['observed_at']}"
            )
        if report.freshness_warnings:
            lines.extend(["", "## Freshness Warnings"])
            lines.extend(f"- {warning}" for warning in report.freshness_warnings)
        lines.extend(["", report.disclaimer])
        return "\n".join(lines)
