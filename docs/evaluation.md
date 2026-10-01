# Evaluation protocol

ComplaintOps keeps three different measurements separate. None should be presented as a
consumer-outcome or legal-accuracy score.

1. **Observed operations metrics** come from completed analyses and human review actions in the
   database. They include latency, estimated model cost, and whether both evidence collections
   were cited. Citation presence does not establish evidence relevance.
2. **Mock routing baseline** uses eight hand-labeled synthetic narratives. It checks only the
   deterministic route and priority rules; it does not exercise the live AI agent.
3. **Labeled retrieval and live-agent checks** use the reproducible benchmark below. Thirty
   retrieved CFPB candidates across six anchors were manually judged for relevance. The same six
   anchors have an expected policy section, and the eight synthetic intake examples have expected
   team and priority labels for optional live-agent testing.

Run the free, read-only retrieval check from `backend`:

```powershell
.venv\Scripts\python -m app.services.benchmark
```

Run the zero-cost authenticated workflow smoke test:

```powershell
.venv\Scripts\python -m app.services.smoke
```

This verifies case creation, sensitive-value redaction, two-collection mock analysis, human
approval, and persistence, then removes its temporary case. It is an integration check rather
than a model-quality score.

On the local 10,183-complaint snapshot, the 30 judged results produced complaint
**precision@5 of 26/30 (86.7%)** with **100% judgment coverage**. The expected policy section
appeared in the three passages supplied to the agent for **6/6 anchors (100% hit@3)**, with
**83.3% MRR@3**. These are intentionally reported as small-sample diagnostic results, not broad
quality claims. The older single-known-pair hit@10 remains **1/6 (16.7%)** as a regression signal,
but it is not a precision score: other retrieved complaints can be relevant even when that one
preselected comparison complaint does not appear. The test reuses each anchor's stored embedding
and makes no API call. The complete reproducible output is in
[`retrieval-benchmark.json`](retrieval-benchmark.json).

Reproduce the paid live-agent check by explicitly opting in and choosing a small run:

```powershell
.venv\Scripts\python -m app.services.benchmark --live --max-cases 2 --max-cost-usd 0.05
```

This calls the live model and embedding API on synthetic cases without creating operational cases.
The `$0.05` parameter is a **soft accounting stop**, not a hard provider-enforced budget: one
in-flight run can exceed the reserved `$0.02` estimate. Review the OpenAI account's own spending
limit before running it. The report scores team, priority, and two-collection citations; it does
not score whether the written advice resolves the complaint.

The completed two-case live run produced **100% normalized team accuracy**, **100% priority
accuracy**, and **100% dual-collection citation coverage**, at an estimated total API cost of
**$0.00214**. A trailing display-only word such as `team` is ignored when comparing routing labels.
The sample is deliberately tiny and is a smoke benchmark, not a broad model-accuracy claim. The
complete output is in [`live-agent-benchmark.json`](live-agent-benchmark.json).

Next evaluation improvement: expand the judged set across a larger, stratified selection of
products and issues, add graded relevance or nDCG, and keep the evaluation set separate from any
tuning set. Recommendation quality still requires human labels beyond retrieval relevance.
