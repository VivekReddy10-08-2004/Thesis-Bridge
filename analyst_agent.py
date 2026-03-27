"""LLM-backed analysis agent for converting research inputs into structured reports.

This module defines strict Pydantic schemas for both public-markets and
private-equity modes, then uses those schemas to validate model responses.
"""

from dotenv import load_dotenv
import os
from groq import Groq
import json
from typing import List, Literal
from pydantic import BaseModel, Field, ValidationError, ConfigDict

# Load environment variables from the .env file
load_dotenv()


class ScenarioCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projected_impact_usd: int = Field(default=0)
    assumption: str = Field(default="")


class ScenarioProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    downside: ScenarioCase = Field(default_factory=ScenarioCase)
    base: ScenarioCase = Field(default_factory=ScenarioCase)
    upside: ScenarioCase = Field(default_factory=ScenarioCase)


class PublicMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(default="")
    metric: str
    previous_period: str = Field(default="")
    current_period: str = Field(default="")
    delta: str = Field(default="")
    unit: str = Field(default="")
    timeframe: str = Field(default="")
    impact_direction: Literal["positive", "negative", "mixed"] = "mixed"
    metric_source_url: str = Field(default="")
    citation_locator: str = Field(default="")
    source_excerpt: str = Field(default="")
    confidence: int = Field(default=0, ge=0, le=10)
    caveat: str = Field(default="")


class PublicEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    source: str
    score: int = Field(ge=0, le=10)
    evidence_strength: Literal["strong", "medium", "weak"] = "medium"
    weakness_note: str = Field(default="")
    why_it_matters: str
    extracted_metrics: List[PublicMetric] = Field(default_factory=list)


class PublicReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["public_markets"]
    thesis: str
    executive_summary: str
    ranked_evidence: List[PublicEvidence] = Field(default_factory=list)
    scenario_projection: ScenarioProjection = Field(default_factory=ScenarioProjection)
    confidence_score: int = Field(ge=0, le=10)
    risks_and_caveats: List[str] = Field(default_factory=list)
    next_diligence_steps: List[str] = Field(default_factory=list)


class PrivateMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    before_value: str = Field(default="")
    after_value: str = Field(default="")
    impact: str = Field(default="")
    unit: str = Field(default="")
    timeframe: str = Field(default="")
    impact_direction: Literal["positive", "negative", "mixed"] = "mixed"
    metric_source_url: str = Field(default="")
    citation_locator: str = Field(default="")
    source_excerpt: str = Field(default="")
    confidence: int = Field(default=0, ge=0, le=10)
    caveat: str = Field(default="")


class PrivateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    source: str
    score: int = Field(ge=0, le=10)
    evidence_strength: Literal["strong", "medium", "weak"] = "medium"
    weakness_note: str = Field(default="")
    why_it_matters: str
    extracted_metrics: List[PrivateMetric] = Field(default_factory=list)


class PrivateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["private_equity"]
    thesis: str
    executive_summary: str
    ranked_evidence: List[PrivateEvidence] = Field(default_factory=list)
    scenario_projection: ScenarioProjection = Field(default_factory=ScenarioProjection)
    confidence_score: int = Field(ge=0, le=10)
    risks_and_caveats: List[str] = Field(default_factory=list)
    next_diligence_steps: List[str] = Field(default_factory=list)

class AnalystAgent:
    """Wrapper around Groq chat completions with schema-validated output."""

    def __init__(self):
        """Initialize Groq client from environment configuration."""
        api_key = os.getenv('Groq_API_key')
        if not api_key:
            raise ValueError("Groq_API_key not found in .env file")
        self.client = Groq(api_key=api_key)

    def _build_context(self, search_results):
        """Flatten search results into a readable context block for prompting."""
        context_blocks = []
        for i, res in enumerate(search_results, 1):
            title = res.get('title', 'Unknown title')
            url = res.get('url', 'Unknown source')
            content = res.get('content', '')
            context_blocks.append(
                f"Case Study {i}:\nTitle: {title}\nSource: {url}\nContent: {content}\n"
            )
        return "\n".join(context_blocks)

    def _call_json(self, prompt):
        """Call the LLM and force a JSON object response."""
        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)

    def _validate_with_retry(self, prompt, schema_model):
        """Validate model output against schema and retry once on validation failure."""
        try:
            parsed = self._call_json(prompt)
            validated = schema_model.model_validate(parsed)
            return validated.model_dump()
        except ValidationError as first_error:
            retry_prompt = (
                prompt
                + "\n\nIMPORTANT: Your prior response failed schema validation. "
                + "Return ONLY valid JSON exactly matching the requested keys, types, and allowed enum values. "
                + f"Previous validation error: {first_error}"
            )
            try:
                parsed_retry = self._call_json(retry_prompt)
                validated_retry = schema_model.model_validate(parsed_retry)
                return validated_retry.model_dump()
            except Exception as retry_error:
                return {"error": f"Schema validation failed after retry: {retry_error}"}
        except Exception as e:
            return {"error": f"Analysis failed: {e}"}

    def analyze_public_markets(self, search_results, thesis, baseline_revenue=1000000):
        """Run public-markets analysis flow and return validated JSON output."""
        context = self._build_context(search_results)

        prompt = f"""
You are an investment research support analyst for a boutique wealth/asset management firm.
Mode: public_markets

Thesis:
{thesis}

Baseline annual revenue for scenario modeling:
{baseline_revenue}

Case studies:
{context}

Instructions:
1) Score each case study for relevance and numeric richness from 1 to 10.
2) Keep only studies with score >= 7 in ranked_evidence.
3) Focus on listed-company evidence: ticker symbols, prior vs current period values, and deltas.
4) Build downside, base, and upside annual impact projections.
5) Be conservative when data is uncertain, and include caveats.
6) For each metric, include metric_source_url and citation_locator for click-to-verify.

Respond ONLY with valid JSON and EXACT top-level keys:
{{
    "mode": "public_markets",
    "thesis": "string",
    "executive_summary": "string",
    "ranked_evidence": [
        {{
            "title": "string",
            "source": "string",
            "score": 0,
            "evidence_strength": "strong|medium|weak",
            "weakness_note": "string",
            "why_it_matters": "string",
            "extracted_metrics": [
                {{
                    "ticker": "string",
                    "metric": "string",
                    "previous_period": "string",
                    "current_period": "string",
                    "delta": "string",
                    "unit": "string",
                    "timeframe": "string",
                    "impact_direction": "positive|negative|mixed",
                    "metric_source_url": "string",
                    "citation_locator": "string",
                    "source_excerpt": "string",
                    "confidence": 0,
                    "caveat": "string"
                }}
            ]
        }}
    ],
    "scenario_projection": {{
        "downside": {{"projected_impact_usd": 0, "assumption": "string"}},
        "base": {{"projected_impact_usd": 0, "assumption": "string"}},
        "upside": {{"projected_impact_usd": 0, "assumption": "string"}}
    }},
    "risks_and_caveats": ["string"],
    "confidence_score": 0,
    "next_diligence_steps": ["string"]
}}
"""
        return self._validate_with_retry(prompt, PublicReport)

    def analyze_private_equity(self, search_results, thesis, baseline_revenue=1000000):
        """Run private-equity analysis flow and return validated JSON output."""
        context = self._build_context(search_results)

        prompt = f"""
You are an investment research support analyst for private equity value creation workstreams.
Mode: private_equity

Thesis:
{thesis}

Baseline annual revenue for scenario modeling:
{baseline_revenue}

Case studies:
{context}

Instructions:
1) Score each case study for relevance and numeric richness from 1 to 10.
2) Keep only studies with score >= 7 in ranked_evidence.
3) Focus on operating value creation: before/after and measurable impact.
4) Build downside, base, and upside annual impact projections.
5) Be conservative when data is uncertain, and include caveats.
6) For each metric, include metric_source_url and citation_locator for click-to-verify.

Respond ONLY with valid JSON and EXACT top-level keys:
{{
    "mode": "private_equity",
    "thesis": "string",
    "executive_summary": "string",
    "ranked_evidence": [
        {{
            "title": "string",
            "source": "string",
            "score": 0,
            "evidence_strength": "strong|medium|weak",
            "weakness_note": "string",
            "why_it_matters": "string",
            "extracted_metrics": [
                {{
                    "metric": "string",
                    "before_value": "string",
                    "after_value": "string",
                    "impact": "string",
                    "unit": "string",
                    "timeframe": "string",
                    "impact_direction": "positive|negative|mixed",
                    "metric_source_url": "string",
                    "citation_locator": "string",
                    "source_excerpt": "string",
                    "confidence": 0,
                    "caveat": "string"
                }}
            ]
        }}
    ],
    "scenario_projection": {{
        "downside": {{"projected_impact_usd": 0, "assumption": "string"}},
        "base": {{"projected_impact_usd": 0, "assumption": "string"}},
        "upside": {{"projected_impact_usd": 0, "assumption": "string"}}
    }},
    "risks_and_caveats": ["string"],
    "confidence_score": 0,
    "next_diligence_steps": ["string"]
}}
"""
        return self._validate_with_retry(prompt, PrivateReport)

    def analyze_and_model(self, search_results, thesis, baseline_revenue=1000000):
        """Backward-compatible default analysis path."""
        return self.analyze_private_equity(search_results, thesis, baseline_revenue)

# Simple test block (only runs if you execute this file directly)
if __name__ == "__main__":
    agent = AnalystAgent()
    # Mock data to test the logic without calling Tavily
    mock_data = [{
        "title": "Mock transformation study",
        "url": "https://example.com/test",
        "content": "Our new AI pipeline reduced server costs by 20% within the first year."
    }]
    result = agent.analyze_and_model(mock_data, thesis="AI operations efficiency for boutique investment firms")
    print(json.dumps(result, indent=4))