# Portal.line Vision Deck

A proposed presentation script for explaining Portal.line as a SQL-first, Iceberg-native catalog for analytics and geospatial metadata.

---

## 1. Opening: Why This, Why Now

- Geospatial infrastructure is still fragmented across many APIs and metadata standards.
- Analytics platforms have converged around open table standards and SQL.
- AI agents need one canonical, machine-readable interface, not five different catalog dialects.

**Core message:** Portal.line connects modern analytics architecture with the geospatial metadata world.

---

## 2. Vision in One Sentence

**Portal.line is a canonical metadata system where resources are defined once, enriched with semantics, and published to multiple standards.**

- One place to create and govern resources.
- One canonical metadata model.
- Many output formats for compatibility.

---

## 3. Design Principles

1. **SQL-first**
2. **Iceberg-native**
3. **CLI-first (agent-ready)**
4. **Canonical metadata, multi-standard outputs**
5. **AI-ready semantics (OSI aligned)**

---

## 4. The Core Paradigm: Define Once

Portal.line keeps a canonical definition of:

- Resource identity and lineage
- Spatial/temporal/quality metadata
- Access policy (public/private)
- Semantics for AI interpretation (OSI)

From this canonical layer, we derive outputs for legacy and modern ecosystems.

---

## 5. Architecture Overview

```text
External Systems (STAC, ArcGIS, Portals, Files, DBs)
                    |
                    v
         Portal.line Canonical Catalog
        (resources + metadata + semantics)
                    |
      +-------------+-------------+
      |             |             |
      v             v             v
  Iceberg/SQL      STAC      ISO/Other outputs
      |
      v
   Web/UI is just another view over the same canonical source
```

**Key idea:** The website is an output, not the source of truth.

---

## 6. Resource Modes: Reference vs Materialize

Portal.line supports both patterns:

- **Reference mode:** keep remote assets in place; register metadata and access paths.
- **Materialize mode:** import/cast/convert data into preferred cloud-native representations.

This covers:

- Datasets we do not want to copy
- Datasets we must normalize for performance/governance
- Mixed catalogs where both coexist

---

## 7. Public and Private Data by Design

Canonical metadata includes publication intent and access posture.

- Public datasets: discoverable and publishable through open outputs.
- Private datasets: controlled visibility with internal query/access paths.
- Same lifecycle model; different exposure policies.

---

## 8. Federation: Integrate Existing Infrastructure

Portal.line can federate and register existing resources from:

- STAC catalogs
- ArcGIS Servers / Portals
- Other existing enterprise catalogs

**Goal:** adopt incrementally, without forcing a big-bang migration.

---

## 9. Lifecycle: Git-Like Catalog Operations

Client-side workflow emphasizes controlled change management:

1. Clone / checkout catalog state
2. Add or update metadata/resources locally
3. Validate and preview outputs
4. Push/sync updates
5. Pull remote changes

This gives familiar operational discipline without needing full branch complexity.

---

## 10. Why Iceberg + SQL at the Center

- Aligns with where analytics platforms already are.
- Enables broad interoperability with engines and tools.
- Makes geospatial metadata queryable with normal SQL workflows.
- Creates a bridge between geospatial specialists and mainstream data teams.

---

## 11. Compatibility Strategy

Portal.line is not anti-standards; it is a standards bridge.

- Keep one canonical representation internally.
- Publish outward to multiple formats for ecosystem compatibility.
- Preserve value from prior standards while modernizing the core.

---

## 12. Current Scope vs Roadmap

### Current

- Read-oriented publishing catalog
- Strong federation and publication workflows
- Canonical metadata + output generation

### Next

- Writable Iceberg catalog operations
- Richer transactional behaviors
- Optional backend evolution (including Nessie-like under-the-hood models)

---

## 13. Positioning vs Emerging Open Catalog Projects

The market is moving toward open-source catalogs with overlapping features.

Portal.line differentiation:

- Geospatial-first metadata depth
- Canonical-to-multi-standard publishing model
- CLI-first operations for human + agent workflows
- Practical bridge from existing infra to modern analytics stacks

---

## 14. Suggested Demo Flow (If You Present Live)

1. Start from an empty local catalog.
2. Federate one existing source (for example STAC or ArcGIS).
3. Register one referenced remote asset (no copy).
4. Materialize one dataset that requires conversion.
5. Show SQL queryability through Iceberg metadata.
6. Generate web/STAC output from the same canonical source.

---

## 15. Closing Message

**Portal.line is a canonical metadata operating layer for geospatial + analytics convergence.**

- Define once
- Query with SQL
- Publish everywhere
- Prepare for AI agents
- Evolve from read-only publishing today to writable catalogs tomorrow

---

## Optional Appendix: One-Slide Summary

```text
Problem: Fragmented geospatial catalogs and APIs
Approach: Canonical metadata + SQL-first Iceberg core
Execution: CLI-first lifecycle + federation + multi-output publishing
Today: Read/publish workflow
Tomorrow: Writable catalogs and deeper transactional control
```
