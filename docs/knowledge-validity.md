# Knowledge validity

Administrators can set `valid_from` and `valid_until` through `POST /api/v1/review/memories/{id}/validity`. Supply both fields (a timestamp with a timezone or null) and the current integer `expected_revision`. The server stores timestamps in UTC. The interval includes its start and excludes its end.

A record outside its window remains accepted in storage. It is excluded from retrieval and context, while administrators can inspect and correct it through review. Changing a window creates a revision and activity event. Restore uses the bounds in the selected revision. Existing records migrate with unbounded windows. Validity does not change approval, subject conflict, or supersession rules.

A context request evaluates search results and preferences at the same request-time instant. A restore applies bounds recorded in the selected snapshot, including explicit nulls. For a legacy snapshot that lacks a bound, restore preserves the current bound for that field.
