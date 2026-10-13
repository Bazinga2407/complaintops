# Complaint Handling Policy

Version: 0.2.0
Status: Demonstration policy—not legal guidance
Owner: Complaint Operations
Review cycle: Quarterly for the demonstration

This fictional operating policy exists to evaluate routing, escalation, evidence gathering, and
human review in ComplaintOps. It is not a substitute for an institution's approved procedures,
regulatory interpretation, or legal advice.

## Purpose and scope

- Apply this policy to consumer complaints entered into the ComplaintOps demonstration queue.
- Use the system to support triage and investigation planning, not to decide legal liability.
- Keep historical CFPB complaints as analogous evidence only; they do not establish an outcome.
- A trained employee remains accountable for every final operational decision.

## Minimum intake information

- Record the product, consumer narrative, intake channel, and received date when available.
- Record the company, state, issue, and sub-issue when the supplied information supports them.
- Do not invent missing facts. Mark uncertain fields for clarification during review.
- Keep the original meaning when correcting spelling or formatting.

## Privacy and redaction

- Remove Social Security numbers, account numbers, telephone numbers, and email addresses from
  narratives before storage or model processing.
- Do not ask an employee to place unredacted authentication information in review notes.
- Treat a high redaction count as a data-quality signal requiring a quick manual check.
- Do not expose one consumer's identifying information in another case.

## Triage

- Route credit reporting complaints to the Credit Reporting team.
- Route debt collection complaints to the Collections Resolution team.
- Route money transfer, virtual currency, and payment complaints to the Payments team.
- Route mortgages, vehicle loans, student loans, deposits, credit cards, and unmatched products to
  General Resolution unless another approved routing rule applies.

## Issue classification

- Select the issue that best describes the consumer's primary requested investigation.
- Preserve a supplied issue when it is consistent with the narrative.
- When several issues appear, identify one primary issue and list the others in the rationale.
- Do not convert an allegation into a confirmed fact.

## Duplicate and related cases

- Check for an existing case involving the same consumer-reported event before creating parallel
  work.
- Link related cases when they share an account event but require separate decisions.
- Do not merge cases merely because they involve the same company or product.
- Escalate uncertain duplicates for human review instead of closing them automatically.

## Standard review

- Use standard review when the narrative describes a routine service, billing, reporting, or
  collection dispute without a time-sensitive harm signal.
- Standard review still requires cited evidence and human approval.
- A prior similar complaint does not by itself justify changing a case to priority review.

## Escalation

- Flag a complaint for priority review when the narrative describes imminent foreclosure, active
  identity theft, inability to access essential funds, or threats of legal action.
- Also prioritize an explicit risk of immediate eviction, utility interruption, or loss of access
  to wages or benefit payments.
- Explain the exact escalation signal in the rationale.
- Do not infer an emergency solely from emotional language.

## Identity theft and account takeover

- Prioritize active identity theft, newly opened fraudulent accounts, or continuing unauthorized
  access.
- Route credit-file identity theft to Credit Reporting and payment-account takeover to Payments
  when the product supports that route.
- Recommend verification of the consumer's submitted identity-theft documentation through secure
  procedures.
- Never instruct the employee to request sensitive documents through an unsecured channel.

## Foreclosure and housing risk

- Prioritize a complaint that reports an imminent foreclosure sale, eviction, or a time-sensitive
  loss-mitigation deadline.
- Recommend verification of the stated date and the status of any active dispute or application.
- Route the case to General Resolution unless the institution maintains a dedicated mortgage team.
- Do not promise that collection or foreclosure activity will stop.

## Access to essential funds

- Prioritize a case when frozen or missing funds are described as necessary for rent, food,
  medicine, utilities, wages, or benefit payments.
- Route money-transfer and payment-access cases to Payments.
- Recommend checking transaction status, restrictions, holds, and prior notices.
- A routine transfer delay that has already resolved remains standard unless another risk exists.

## Collection and legal-action threats

- Route debt collection complaints to Collections Resolution.
- Prioritize a reported threat of near-term litigation, garnishment, repossession, or other legal
  action.
- Recommend validating account ownership, balance, collector authority, and communication history.
- Do not determine whether a debt is legally enforceable.

## Credit reporting disputes

- Route disputes about inaccurate accounts, inquiries, identity theft, or investigation results to
  Credit Reporting.
- Recommend checking the disputed tradeline or inquiry, prior disputes, and supplied evidence.
- Prioritize active identity theft or a documented time-sensitive housing or employment impact.
- Do not state that information must be deleted without an approved investigation.

## Payment and transfer disputes

- Route unauthorized transfers, frozen wallets, missing transfers, and payment-service access
  complaints to Payments.
- Distinguish unauthorized activity from merchant disputes and ordinary processing delays.
- Recommend checking authorization evidence, transaction status, notices, and dispute history.
- Prioritize active account takeover or loss of access to essential funds.

## Evidence checklist

- Review the narrative, product, issue, company, dates, and previous internal contacts.
- Use retrieved CFPB complaints only to identify analogous fact patterns and investigation ideas.
- Use the current active policy version to support routing and escalation.
- Document contradictions, missing evidence, and assumptions for the human reviewer.

## Similar-complaint evidence

- Prefer historical complaints with the same product and a closely matching fact pattern.
- Cite the complaint identifier and a short relevant excerpt.
- Do not imply that the cited complaint was proven, adjudicated, or resolved in the same way.
- Exclude the incoming case itself when it originated from the historical corpus.

## Low confidence and conflicting evidence

- A low-confidence classification must be reviewed before assignment.
- When complaint evidence and policy retrieval point to different routes, present the conflict
  rather than hiding it.
- Recommend clarification when missing facts could change priority or ownership.
- Do not use confidence as a probability that the consumer is truthful.

## Recommended actions

- Recommend a small, ordered checklist that an employee can verify.
- Tie each action to the incoming facts or a retrieved policy requirement.
- Separate immediate risk controls from the normal investigation.
- Do not instruct the system to contact a consumer, change an account, or issue compensation.

## Consumer communication

- Use neutral language that acknowledges the complaint without admitting or denying liability.
- State what will be reviewed and identify any information still required through approved channels.
- Do not expose internal confidence scores, model reasoning, or another consumer's complaint.
- A human employee must approve any response derived from the recommendation.

## Human approval

The system may recommend a route, priority, and response checklist. A human operator must approve or edit the recommendation. The demonstration must not characterize its output as legal advice.

## Editing and rejection

- Edit a recommendation when the evidence supports useful portions but routing, priority, or an
  action needs correction.
- Reject it when it is materially unsupported, unsafe, or based on the wrong case facts.
- Record a concise reason so future quality reviews can distinguish retrieval and generation errors.
- Preserve the original analysis alongside the latest human decision.

## Quality assurance and audit

- Retain the model, token usage, estimated cost, tool trace, citations, and review action.
- Monitor dual-collection citation coverage, latency, review outcomes, and recurring edit reasons.
- Sample approved recommendations for relevance and policy compliance.
- Treat citation presence as a coverage signal, not proof that the citation was relevant.

## Prohibited outputs

- Do not give legal advice, make a legal conclusion, or guarantee a consumer outcome.
- Do not claim that a historical complaint proves the incoming allegation.
- Do not fabricate an account action, investigation result, policy requirement, or citation.
- Do not take an external action without an authorized human workflow.

## Policy governance

- Store every policy revision as a versioned document and keep only the approved revision active.
- Re-embed changed sections before using a new version for live analysis.
- Evaluate retrieval after material wording or chunking changes.
- Record the owner, status, and review date for any policy used beyond this demonstration.
