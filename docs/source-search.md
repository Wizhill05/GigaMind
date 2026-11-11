# Legacy source search

Text searches scan the complete filtered legacy memory and profile corpus for case-folded terms, including short and Unicode terms. Results identify their retrieval method; scores are raw and uncalibrated. A missing or unavailable embedding provider leaves lexical retrieval available, but cannot supply semantic matches. No lexical match is an empty result when vector retrieval is unavailable. Image searches require a valid PNG or JPEG and an available embedding provider.

File retrieval remains separate: its fallback considers at most 40 file records and PostgreSQL vector candidates are capped at 30 documents and 60 chunks. It does not provide full-corpus file or chunk lexical retrieval. Semantic retrieval depends on indexed vectors and the configured provider; lexical matching is not semantic understanding.
