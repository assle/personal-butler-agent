---
name: general-research
version: 1.0.0
description: General internal and public-web research for factual questions, comparisons, and structured reports.
applies_to: [factual, comparison, report]
allowed_tools: [knowledge.search, web.search, web.fetch]
evidence_policy: claim-level
report_schema: structured-report-v1
reviewer_policy: strict-citation-v1
---

## Research Method

1. Search internal knowledge first, then public web.
2. Prefer authoritative sources (official docs, peer-reviewed).
3. Surface conflicting evidence explicitly — do not silently resolve.
4. Every factual claim must cite specific evidence.

## Source Hierarchy

- Primary: official documentation, peer-reviewed papers
- Secondary: reputable technical blogs, vendor docs
- Supplementary: community discussions (mark as lower confidence)

## Conflict Handling

When sources disagree, present both sides in the report with evidence citations for each position.

## Report Format

- Title summarizing the research question
- Executive summary with key findings
- Structured sections with evidence citations (e.g., [E:1], [E:2])
- Limitations section noting gaps and confidence levels
