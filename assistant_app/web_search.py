from __future__ import annotations

import os
from typing import Any

from ddgs import DDGS

import sys
import time
import threading

class SpinnerTimer:
    def __init__(self, message="Processing"):
        self.message = message
        self.is_running = False
        self._thread = None
        self.start_time = 0

    def _spin(self) -> None:
        while self.is_running:
            elapsed = time.time() - self.start_time

            sys.stdout.write(f"\r[⏳] {self.message}... ({elapsed:.1f}s)")
            sys.stdout.flush()
            time.sleep(0.1) 

    def start(self) -> None:
        self.is_running = True
        self.start_time = time.time()
        self._thread = threading.Thread(target=self._spin)
        self._thread.start()

    def stop(self) -> float:
        self.is_running = False
        if self._thread:
            self._thread.join()

        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
        return time.time() - self.start_time


class WebSearchError(RuntimeError):
    pass


try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


class WebSearchService:
    def __init__(
        self,
        tavily_api_key: str | None = None,
        enable_tavily: bool = True,
        enable_ddg: bool = True,
    ):
        self.enable_tavily = enable_tavily
        self.enable_ddg = enable_ddg

        self.tavily_api_key = tavily_api_key or os.getenv("TAVILY_API_KEY")
        self.tavily_client = None

        if self.enable_tavily and self.tavily_api_key and TavilyClient:
            self.tavily_client = TavilyClient(api_key=self.tavily_api_key)

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        query = query.strip()
        if not query:
            raise WebSearchError("Query must not be empty.")

        print(f"\n[🌐] Orbit is searching the web for: '{query}'...")

        timer = SpinnerTimer(message="Waiting for Search API")
        timer.start()

        if self.tavily_client:
            try:
                results = self._search_tavily(query, max_results)
                
                elapsed = timer.stop()
                print(f"[🌐] Web Search: Successfully found {len(results)} results via Tavily! ({elapsed:.1f}s)")
                return results
            except Exception as e:
                timer.stop()
                print(f"[⚠️] Tavily search failed: {e}. Falling back to DuckDuckGo...")
                timer = SpinnerTimer(message="Waiting for DuckDuckGo")
                timer.start()

        if self.enable_ddg:
            try:
                results = self._search_ddg(query, max_results)
                elapsed = timer.stop()
                print(f"[🌐] Web Search: Successfully found {len(results)} results via DDG! ({elapsed:.1f}s)")
                return results
            except Exception as e:
                timer.stop()
                print(f"[⚠️] DuckDuckGo search failed: {e}")

        if timer.is_running:
            timer.stop()
        raise WebSearchError("Search failed on all enabled providers.")

    def _search_tavily(self, query: str, max_results: int) -> list[dict[str, str]]:
        tavily_response = self.tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
            include_raw_content=False,
        )

        results: list[dict[str, str]] = []
        for result in tavily_response.get("results", []):
            results.append({
                "title": result.get("title", "No title"),
                "link": result.get("url", ""),
                "body": result.get("content", "No content"),
                "source": "tavily",
            })

        return results

    def _search_ddg(self, query: str, max_results: int) -> list[dict[str, str]]:
        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, max_results=max_results))

        results: list[dict[str, str]] = []
        for item in raw_results:
            results.append({
                "title": item.get("title", "No title"),
                "link": item.get("href", ""),
                "body": item.get("body", "No content"),
                "source": "ddg",
            })

        return results