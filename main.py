"""CLI pipeline entrypoint for research search, analysis, and memo export."""

# Bring in search and analysis building blocks.
from search_agent import SearchAgent
from analyst_agent import AnalystAgent
import json
import os
from datetime import datetime


def build_markdown_report(topic, report):
    """Render a structured markdown memo from the validated report payload."""
    evidence_rows = []
    for item in report.get("ranked_evidence", []):
        evidence_rows.append(
            f"| {item.get('score', 0)} | {item.get('title', 'N/A')} | {item.get('source', 'N/A')} | {item.get('why_it_matters', 'N/A')} |"
        )

    if not evidence_rows:
        evidence_rows.append("| - | No high-quality evidence retained | - | - |")

    scenario = report.get("scenario_projection", {})
    downside = scenario.get("downside", {})
    base = scenario.get("base", {})
    upside = scenario.get("upside", {})

    risks = report.get("risks_and_caveats", [])
    steps = report.get("next_diligence_steps", [])

    risk_lines = "\n".join([f"- {r}" for r in risks]) if risks else "- No explicit caveats returned."
    step_lines = "\n".join([f"- {s}" for s in steps]) if steps else "- No follow-up steps returned."

    return f"""# Pre-Investment Research Memo

## Thesis
{topic}

## Executive Summary
{report.get('executive_summary', 'No summary generated.')}

## Ranked Evidence
| Score | Title | Source | Why It Matters |
|---|---|---|---|
{chr(10).join(evidence_rows)}

## Scenario Projection (Annual Impact)
- Downside: ${downside.get('projected_impact_usd', 0)}
  - Assumption: {downside.get('assumption', 'Not provided')}
- Base: ${base.get('projected_impact_usd', 0)}
  - Assumption: {base.get('assumption', 'Not provided')}
- Upside: ${upside.get('projected_impact_usd', 0)}
  - Assumption: {upside.get('assumption', 'Not provided')}

## Risks and Caveats
{risk_lines}

## Confidence
{report.get('confidence_score', 0)} / 10

## Next Diligence Steps
{step_lines}
"""


def save_markdown_report(topic, report):
    """Persist the generated memo to the reports folder and return its path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("reports", exist_ok=True)
    output_path = os.path.join("reports", f"memo_{timestamp}.md")
    memo = build_markdown_report(topic, report)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(memo)
    return output_path

def run_pipeline():
    """Execute end-to-end research pipeline in terminal mode."""
    print("=== Starting Strategic Intelligence Pipeline ===")
    
    # Initialize the API-backed agents.
    try:
        searcher = SearchAgent()
        analyst = AnalystAgent()
    except ValueError as e:
        print(f"Setup Error: {e}")
        return

    # Step 1: Collect user thesis.
    try:
        topic = searcher.get_user_prompt()
    except ValueError as e:
        print(e)
        return

    # Step 2: Pull candidate evidence from web search.
    search_results = searcher.process_search(topic)
    
    if not search_results or isinstance(search_results, str):
        print("Search failed or returned no results.")
        return

    # Step 3: Convert raw evidence into structured scenario analysis.
    # Use $1,000,000 as baseline for scenario impact math.
    final_report = analyst.analyze_and_model(
        search_results,
        thesis=topic,
        baseline_revenue=1000000,
    )

    if "error" in final_report:
        print(f"Analysis Error: {final_report['error']}")
        return

    # Step 4: Print JSON and save markdown memo.
    print("\n=== FINAL STRATEGIC IMPACT REPORT ===")
    print(json.dumps(final_report, indent=4))

    report_path = save_markdown_report(topic, final_report)
    print(f"\nMarkdown memo saved to: {report_path}")

# CLI execution trigger.
if __name__ == "__main__":
    run_pipeline()