"""Public API for read-only Quran morphology research."""

__version__ = "1.1.0"

from quran_analysis.research import AggregateQuery, CooccurrenceQuery, ResearchEngine, ResearchQuery, SetQuery, load_query

__all__ = ["__version__", "AggregateQuery", "CooccurrenceQuery", "ResearchEngine", "ResearchQuery", "SetQuery", "load_query"]
