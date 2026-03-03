"""
Search Adapters - External Search Provider Integration

This module contains adapters for external search providers like Tavily, SerpAPI, etc.
Each adapter provides a consistent interface for search operations while handling
provider-specific authentication and response formatting.
"""

# Import adapters for easy access
from .tavily_adapter import TavilyAdapter

__all__ = ["TavilyAdapter"]
