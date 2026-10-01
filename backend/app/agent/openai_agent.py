import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Case
from app.schemas.case import AgentRecommendation, Citation, Classification
from app.services.embeddings import OpenAIEmbedder
from app.services.retrieval import search_operating_policies, search_similar_complaints

MODEL_PRICING_PER_MILLION = {
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5-mini": (0.25, 2.00),
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_similar_complaints",
        "description": (
            "Search the local pgvector collection of public CFPB complaint narratives. "
            "Use it to find comparable historical evidence; it does not provide legal outcomes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A concise semantic search query based on the case facts.",
                },
                "product": {
                    "type": "string",
                    "description": "The product label from the incoming case.",
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["query", "product", "top_k"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_operating_policies",
        "description": (
            "Search the separate local pgvector collection of versioned operating-policy "
            "passages. Use it to ground routing, escalation, and human-review steps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A concise query for relevant internal policy requirements.",
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 6},
            },
            "required": ["query", "top_k"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

TOOL_INSTRUCTIONS = """You are the ComplaintOps evidence-gathering agent for a fictional
financial institution. Before making a recommendation, call both available search tools. Search
historical complaints for analogous facts and operating policies for routing, escalation, and
human-review requirements. Do not provide legal advice or claim that a historical complaint proves
an outcome. The application, not you, controls all database access."""

FINAL_INSTRUCTIONS = """Create a concise operations recommendation using only the incoming case
and retrieved tool evidence. Classify the product and issue, choose an assigned team, set standard
or priority review, and provide actionable next steps. Confidence is confidence in the operational
classification, not in the truth of the complaint. Never claim a legal conclusion. A human employee
must make the final decision."""


class AgentDraft(BaseModel):
    summary: str = Field(max_length=800)
    classification: Classification
    recommended_actions: list[str] = Field(min_length=1, max_length=8)
    rationale: list[str] = Field(min_length=1, max_length=8)


@dataclass(frozen=True)
class OpenAIAgentResult:
    recommendation: AgentRecommendation
    tool_trace: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    model: str


def _usage(response: Any) -> tuple[int, int]:
    if response.usage is None:
        return 0, 0
    return response.usage.input_tokens, response.usage.output_tokens


def _model_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = MODEL_PRICING_PER_MILLION.get(model, (0.0, 0.0))
    return input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price


def _deduplicate_citations(citations: list[Citation]) -> list[Citation]:
    unique: dict[tuple[str, str], Citation] = {}
    for citation in citations:
        unique[(citation.collection, citation.source_id)] = citation
    complaints = [item for item in unique.values() if item.collection == "historical_complaints"][
        :5
    ]
    policies = [item for item in unique.values() if item.collection == "operating_policies"][:3]
    return [*policies, *complaints]


def analyze_with_openai(
    db: Session,
    case: Case,
    *,
    api_key: str,
    model: str,
    embedding_model: str,
    embedding_dimensions: int = 1536,
    max_agent_turns: int = 3,
    max_output_tokens: int = 1200,
) -> OpenAIAgentResult:
    client = OpenAI(api_key=api_key)
    embedder = OpenAIEmbedder(
        api_key=api_key,
        model=embedding_model,
        dimensions=embedding_dimensions,
    )
    case_payload = {
        "case_id": str(case.id),
        "product": case.product,
        "existing_issue": case.issue,
        "company": case.company,
        "state": case.state,
        "narrative": case.narrative,
    }
    input_items: list[Any] = [
        {
            "role": "user",
            "content": "Analyze this incoming complaint case:\n" + json.dumps(case_payload),
        }
    ]
    tool_trace: list[dict[str, Any]] = []
    citations: list[Citation] = []
    total_input_tokens = 0
    total_output_tokens = 0
    retrieval_cost = 0.0
    called_collections: set[str] = set()

    for _ in range(max_agent_turns):
        response = client.responses.create(
            model=model,
            instructions=TOOL_INSTRUCTIONS,
            input=input_items,
            tools=TOOLS,
            tool_choice="required",
            parallel_tool_calls=True,
            reasoning={"effort": "none"},
            max_output_tokens=max_output_tokens,
            store=False,
        )
        used_input, used_output = _usage(response)
        total_input_tokens += used_input
        total_output_tokens += used_output
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            break
        input_items.extend(item.model_dump(exclude_none=True) for item in response.output)
        for call in calls:
            arguments = json.loads(call.arguments)
            if call.name == "search_similar_complaints":
                result = search_similar_complaints(
                    db,
                    embedder,
                    query=arguments["query"],
                    product=case.product,
                    top_k=arguments["top_k"],
                    exclude_complaint_id=case.source_complaint_id,
                )
                collection = "historical_complaints"
            elif call.name == "search_operating_policies":
                result = search_operating_policies(
                    db,
                    embedder,
                    query=arguments["query"],
                    top_k=arguments["top_k"],
                )
                collection = "operating_policies"
            else:
                raise RuntimeError(f"Unsupported agent tool: {call.name}")
            citations.extend(result.citations)
            retrieval_cost += result.estimated_cost_usd
            called_collections.add(collection)
            tool_trace.append(
                {
                    "tool": call.name,
                    "status": "completed",
                    "result_count": len(result.citations),
                }
            )
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps([citation.model_dump() for citation in result.citations]),
                }
            )
        if called_collections == {"historical_complaints", "operating_policies"}:
            break

    if "historical_complaints" not in called_collections:
        result = search_similar_complaints(
            db,
            embedder,
            query=case.narrative,
            product=case.product,
            top_k=5,
            exclude_complaint_id=case.source_complaint_id,
        )
        citations.extend(result.citations)
        retrieval_cost += result.estimated_cost_usd
        tool_trace.append(
            {
                "tool": "search_similar_complaints",
                "status": "guardrail_fallback",
                "result_count": len(result.citations),
            }
        )
    if "operating_policies" not in called_collections:
        result = search_operating_policies(
            db,
            embedder,
            query=case.narrative,
            top_k=3,
        )
        citations.extend(result.citations)
        retrieval_cost += result.estimated_cost_usd
        tool_trace.append(
            {
                "tool": "search_operating_policies",
                "status": "guardrail_fallback",
                "result_count": len(result.citations),
            }
        )

    grounded_citations = _deduplicate_citations(citations)
    collections = {citation.collection for citation in grounded_citations}
    if collections != {"historical_complaints", "operating_policies"}:
        raise RuntimeError("Both RAG collections must contain embeddings before live analysis")
    input_items.append(
        {
            "role": "user",
            "content": (
                "Produce the final structured recommendation. The backend will attach these "
                "verified citations: "
                + json.dumps([citation.model_dump() for citation in grounded_citations])
            ),
        }
    )
    final_response = client.responses.parse(
        model=model,
        instructions=FINAL_INSTRUCTIONS,
        input=input_items,
        tools=TOOLS,
        tool_choice="none",
        reasoning={"effort": "none"},
        max_output_tokens=max_output_tokens,
        text_format=AgentDraft,
        store=False,
    )
    used_input, used_output = _usage(final_response)
    total_input_tokens += used_input
    total_output_tokens += used_output
    draft = final_response.output_parsed
    if draft is None:
        raise RuntimeError("OpenAI returned no structured recommendation")
    classification = draft.classification.model_copy(update={"product": case.product})
    recommendation = AgentRecommendation(
        summary=draft.summary,
        classification=classification,
        recommended_actions=draft.recommended_actions,
        rationale=draft.rationale,
        citations=grounded_citations,
        provider="openai",
        requires_human_review=True,
    )
    return OpenAIAgentResult(
        recommendation=recommendation,
        tool_trace=tool_trace,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        estimated_cost_usd=(
            _model_cost(model, total_input_tokens, total_output_tokens) + retrieval_cost
        ),
        model=model,
    )
