"""External enrichment services for threat intelligence.

Provides passive DNS, ASN/RDAP, and takedown-verification enrichment
via external APIs.  Each module degrades gracefully when API keys are
absent.
"""
