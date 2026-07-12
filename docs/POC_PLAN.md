# Part 3: Path to Proof of Concept, Blockers, Estimates, and Release Plan

Companion to [DESIGN.md](DESIGN.md). This document turns the design into an
engineering sequence: what to build, in what order, what can block it, how to
evaluate the PoC, and how to release without surprises.

Estimating convention: ranges are given as *optimistic → expected → padded*,
assuming **2 engineers**; single-point estimates on novel work are fiction, so
confidence is stated per item. Calendar time ≠ effort time where external
parties are involved.

---

## 1. PoC definition — prove the risky parts, defer the rest

**Goal**: crawl **10 million URLs across ~20 domains in ≤ 7 days** on the
production architecture skeleton, and produce the measurements that
de-risk the billion-scale decision.

**In scope** (each maps to a specific §-risk in DESIGN.md):
- File → S3 ingestion with canonicalization + dedup (loader correctness)
- Kafka frontier + per-domain politeness controller (the §1 constraint, in code)
- Async fetch workers from the existing `fetcher.py` (does the refactor hold
  1,000+ concurrent connections per task?)
- Fetch/parse split with raw HTML in S3 + one full **reprocessing run**
  (prove the "reparse without refetch" cost claim)
- Unified schema v1.0 end to end: Kafka → Parquet/Iceberg → Athena
- Dashboards 1–3 and the paging alerts from DESIGN.md §5
- Measured per-domain success/block rates → data for the §7 tier decisions

**Explicitly out of scope**: MySQL CDC ingestion (monthly export suffices),
DynamoDB hot index, headless-browser tier, multi-region, recrawl/change
detection, the named mega-retailers (PoC uses medium-sized domains where
Tier-1 fetching is viable — the retailers are a *procurement* track, not a
PoC track; see blockers B1/B2).

**Why 10M**: large enough to surface politeness math, spot interruptions,
queue behavior, and cost-per-1K with real error bars; small enough to re-run
the whole PoC in a day after a fix.

---

## 2. Implementation schedule

Six weeks to an evaluated PoC; two engineers (A: pipeline/infra, B: data/observability).

| Phase | Weeks | Deliverables | Exit gate |
|---|---|---|---|
| **P0 — Foundations** | 1–2 | Terraform for VPC/MSK/Redis/S3/ECS skeleton; async refactor of `fetcher.py` (aiohttp) keeping SSRF guard/size-cap tests green; loader with canonicalization + dedup; schema v1.0 frozen + JSON Schema CI check | 100K-URL smoke run end-to-end on one worker |
| **P1 — Scale the skeleton** | 3–4 | Politeness controller (token buckets + robots.txt cache); Fargate Spot autoscaling on consumer lag; DLQ + redrive; parse workers → Iceberg; Athena queryable | 1M URLs, ≥3 domains, zero manual intervention |
| **P2 — Observe & harden** | 4–5 (overlaps) | Dashboards 1–3, paging alerts, runbooks for each; canary URL set; chaos drill (kill 30% of workers mid-run; zero a domain rate live) | on-call engineer can answer "is the batch on track?" from dashboards alone |
| **P3 — PoC run & evaluation** | 6 | 10M-URL run; reprocessing run over stored HTML; evaluation report vs. §3 criteria; go/no-go review | report delivered; decision made |

Estimate confidence: P0 **high** (refactor of tested code, standard infra),
P1 **medium** (politeness controller is the novel component — padded),
P2 **high**, P3 **medium** (first contact with reality; one re-run budgeted).
Padded calendar total: **6–8 weeks**.

---

## 3. PoC evaluation — how we know it worked

Measured against explicit targets; every number lands in the evaluation report.

**System performance**
| Metric | Target | Why this number |
|---|---|---|
| Sustained throughput | ≥ 50 URLs/sec fleet-wide for 24h+ | 10M/wk needs ~17/sec; 3× headroom proves autoscaling, not luck |
| Per-domain rate compliance | 0 violations of configured ceilings | politeness is a correctness property, not best-effort |
| Worker efficiency | ≥ 500 concurrent fetches per 2-vCPU task | validates the async refactor and the §6 fleet-size math |
| Spot interruption recovery | 0 lost URLs across ≥5 interruptions | proves idempotency design under real churn |

**Data quality** (sampled: 1,000 records/domain, plus manual audit of 500)
| Metric | Target |
|---|---|
| Fetch success (attemptable) | ≥ 85% per domain |
| Metadata completeness (title present on `ok`) | ≥ 95% |
| Classification precision on audit sample | ≥ 80%, with per-type confusion table |
| Schema violations | 0 |
| Reprocessing run | 100% of stored HTML reparsed, zero fetches, cost recorded |

**Economics**
| Metric | Target |
|---|---|
| Cost per 1K URLs (all-in, from Cost Explorer tags) | ≤ $7.50 (1.5× the §6 model; PoC scale lacks amortization) |
| Extrapolated 1B/mo cost | within 2× of the $5K model, with the delta explained |

**Operations**: every paging alert fired at least once (chaos drill or
naturally) and each was actionable via its runbook; batch-completion
projection on dashboard 1 within 10% of actual.

**Go/no-go**: go = all system + data targets hit and economics within bounds.
Conditional go = misses explained by known, costed fixes. No-go = politeness
math or block rates invalidate the timeline promise → escalate to the Tier-0
procurement path (DESIGN.md §7) before any further engineering spend.

---

## 4. Blockers and risks

Classified by knowability and severity; each with owner-type and lead time.

### Known, trivial (days; engineering-internal)
| # | Blocker | Resolution | Lead time |
|---|---|---|---|
| T1 | AWS service quotas (Fargate concurrent tasks, MSK brokers, S3 PUT rate is per-prefix) | quota increase requests; prefix-sharded S3 keys (already in the §2 layout) | 1–3 days, submit in P0 week 1 |
| T2 | `requests` → `aiohttp` behavioral drift (redirect semantics, timeout model) | the 29 existing tests + guarded-redirect tests run against both during refactor | in-plan (P0) |
| T3 | MySQL export access & format for the URL source | one meeting + a sample dump; loader handles text either way | 1 week, calendar not effort |
| T4 | Schema sign-off with downstream consumers | circulate §3 schema week 1; additive-only evolution afterwards | 1 week |

### Known, hard (weeks; cross-functional)
| # | Blocker | Impact | Mitigation | Lead time |
|---|---|---|---|---|
| B1 | **Bot walls on the named retail domains** — measured, not speculative (DESIGN.md §7) | Tier-1 success on amazon/walmart/bestbuy may be <20%, invalidating naive completion promises | PoC runs on viable domains; parallel procurement track for APIs/licensed data/unblocking vendors starts week 1, *not* after the PoC | **4–8 weeks, on the critical path for the retail use case** |
| B2 | Legal/ToS review of crawling policy per target + proxy vendor terms | blocks Tier-2/3 usage; can block the whole retail track | engage counsel week 1 with the §7 tier table; robots.txt-honoring Tier 1 proceeds meanwhile | 2–6 weeks, calendar |
| B3 | Politeness vs. deadline arithmetic requires a *stakeholder decision* (crawl slower vs. spend on Tier 2/3 vs. license data) | undefined "done" for the monthly batch | present the §1 math with per-domain options and costs at the P1 review; decision is an input to the SLA, not an engineering guess | decision meeting, week 4 |
| B4 | Spot capacity crunches (us-east-1 events) | throughput dips | capacity-optimized allocation, 3 instance families, 20% on-demand floor | in-plan |

### Unknown-unknowns (budgeted, not enumerated)
20% schedule pad (already in the ranges), one full PoC re-run budgeted, and a
standing rule: any surprise that costs >2 engineer-days gets a written
mini-postmortem so the next estimate improves. Operating history already
funded this budget honestly: local Docker/AF_UNIX kernel bug, AWS Free-plan
service lockout, and PowerShell pipe encoding each cost real hours and none
were foreseeable from documentation.

---

## 5. Release plan — PoC → GA

Principle: **scale is earned in ~10× increments**, each gated on the same
evaluation harness as §3, so "it worked at N" is always evidence, never hope.

| Stage | Scale | Duration | Gate to advance |
|---|---|---|---|
| PoC | 10M / 20 domains | wk 6 | §3 go |
| Beta | 100M / 200 domains, first real monthly batch, MySQL ingestion added | wks 7–10 | SLOs held for a full batch; cost within 1.5× model; zero data-loss incidents |
| GA v1 | 1B+/mo, SLA signed, on-call rotation live | wks 11–16 | two consecutive compliant batches |

**Release quality mechanics** (each release, including PoC):
- Versioned everything: image tags = git SHA; `schema_version` and
  `classifier_version` in every record (already in schema).
- **Canary deploys**: new worker version takes 5% of one domain's partition
  for 24h; dashboards diff old-vs-new error and quality rates before fleet
  rollout; instant rollback = repoint image tag (stateless workers).
- Data changes get the same rigor as code: a classifier change ships behind
  a reprocessing plan and a before/after confusion table on the audit set.
- Runbook + on-call readiness review before beta; error-budget policy
  (DESIGN.md §4) active from beta onward.
- Documentation as release artifact: architecture docs (these), per-alert
  runbooks, schema registry, and the PoC evaluation report all live in-repo
  and are updated in the same PR as the change they describe.

**Post-GA roadmap candidates** (explicitly deferred): recrawl scheduling from
per-domain change-rate models; headless-browser tier if B1 procurement
chooses it; DynamoDB hot index when a low-latency consumer materializes;
multilingual topic extraction; near-duplicate content detection (simhash)
across domains.
