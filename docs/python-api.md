# Python API

The public API provides the same query models and engine used by the CLI; CLI and API have query parity. It does not create sessions or write data for you.

```python
from quran_analysis import ResearchEngine, ResearchQuery
from quran_analysis.db.session import get_session_local

query = ResearchQuery.loads('{"where":{"dimension":"root","operator":"eq","value":"ktb"}}')
with get_session_local()() as session:
    result = ResearchEngine(session).execute(query)
print(result.to_dict()["summary"])
```

For file input, `from quran_analysis import load_query` accepts JSON or YAML paths. Use `AggregateQuery.from_dict`, `SetQuery.from_dict`, or `CooccurrenceQuery.from_dict` with `ResearchEngine.aggregate`, `.set`, or `.cooccurrence` respectively. All calls are read-only.
