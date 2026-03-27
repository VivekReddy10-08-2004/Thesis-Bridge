"""Search agent for collecting deduplicated web evidence via Tavily.

The agent supports two query profiles:
- public_markets: filings, earnings, and macro context
- private_equity: value-creation and before/after outcomes
"""

from dotenv import load_dotenv
import os
from tavily import TavilyClient

# Load environment variables from the .env file
load_dotenv()

class SearchAgent:
    """Encapsulates Tavily search logic and mode-specific query strategies."""

    def __init__(self):
        """Initialize Tavily client from environment configuration."""
        api_key = os.getenv('Tavily_API_key')
        if not api_key:
            raise ValueError("Tavily_API_key not found in .env file")
        self.client = TavilyClient(api_key=api_key)
    
    def get_user_prompt(self):
        """Collect terminal input and return a validated prompt."""
        prompt = input(f"What would you like to search for?").strip()
    # Validate directly here to save space
        if not prompt:
            raise ValueError("Prompt cannot be empty. Please enter a valid search query.")
        return prompt


    def _run_queries(self, topic, queries):
        """Run a batch of Tavily queries and dedupe by URL."""
        print(f"--- Researching: {topic} ---")
        collected = []
        seen_urls = set()

        try:
            for query in queries:
                response = self.client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=5,
                    include_raw_content=False,
                )
                for item in response.get('results', []):
                    url = item.get('url')
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    collected.append(item)

            return collected[:8]
        except Exception as e:
            return f"Search failed: {e}"

    def process_search_public(self, topic):
        """Public markets search profile (filings, earnings, and macro signals)."""
        queries = [
            f"{topic} earnings transcript 10-Q 10-K guidance margin growth analysis",
            f"{topic} SEC filing investor presentation KPI quarter over quarter change",
            f"{topic} macro exposure rates inflation demand sensitivity public company",
        ]
        return self._run_queries(topic, queries)

    def process_search_private(self, topic):
        """Private equity search profile (before/after value creation outcomes)."""
        queries = [
            f"ROI case studies on {topic} with measurable before after outcomes",
            f"{topic} implementation results including operating cost timeline EBITDA impact",
            f"{topic} B2B operational improvement case study productivity efficiency",
        ]
        return self._run_queries(topic, queries)

    def process_search(self, topic):
        """Backward-compatible default search path."""
        return self.process_search_private(topic)


if __name__ == "__main__":
    agent = SearchAgent()
    try:
        user_prompt = agent.get_user_prompt()
        results = agent.process_search(user_prompt)
        # Print a quick preview of collected sources for manual verification.
        for i, res in enumerate(results, 1):
            print(f"\n Result {i} Title: {res['title']}")
            print(f"Source: {res['url']}")
            # Snippet of the content we'll send to Groq later
            print(f"Content Preview: {res['content'][:200]}...")             
    except ValueError as e:
        print(f"Error: {e}")