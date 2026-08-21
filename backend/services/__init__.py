"""Application services: business logic that spans the repo and model layers.

Routers stay thin — they call into services rather than reaching for models or
repositories directly (enforced by the architecture test).
"""
