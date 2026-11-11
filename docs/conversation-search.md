# Conversation search

Legacy transcript search scans decoded titles, summaries and complete message text with SQL platform and source filters. Results identify lexical and optional vector signals separately; evidence excerpts retain message role, index and available source identifiers and timestamps. Existing transcript vectors may represent only a prefix, and vector scores are not calibrated relevance judgments. Search remains available without an embedding provider. Legacy sources remain admin-only and are not accepted knowledge.

Transcript segment vectors, scoped source storage and calibrated semantic relevance remain unfinished.

Queries are limited to 2048 characters. Direct lexical evidence ranks before vector-only candidates; scores combine ranking signals and are not confidence estimates. Evidence excerpts preserve original Unicode text. Legacy platform/source case matching uses the database lower-case comparison.
