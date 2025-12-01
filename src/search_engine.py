import os
import time
import logging
import hashlib
import pickle
import re
import tempfile
from typing import List, Dict, Optional
from datetime import datetime
from urllib.parse import quote_plus

try:
    import src.logger as logger_module
except Exception:
    logger_module = None

try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None

import trafilatura
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

def _get_root_logger():
    if logger_module:
        try:
            return logging.getLogger("EnhancedSearchEngine")
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger("EnhancedSearchEngine")


class EnhancedSearchEngine:
    def __init__(self, cache_dir: str = ".search_cache", cache_ttl: int = 3600):
        self.ddgs = DDGS() if DDGS else None
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.logger = _get_root_logger()
        self.ensure_cache_dir()

    def ensure_cache_dir(self):
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception as e:
            self.logger.warning("Could not create cache dir %s: %s", self.cache_dir, e)

    def get_timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_cache_key(self, query: str, search_type: str = "text") -> str:
        """
        Deterministic cache key generator using MD5 (safe for filenames).
        """
        key_string = f"{query}_{search_type}".encode("utf-8")
        return hashlib.md5(key_string).hexdigest()

    def _atomic_pickle_write(self, path: str, obj: Dict) -> None:
        """
        Write `obj` to `path` atomically using a temp file + os.replace.
        """
        dirpath = os.path.dirname(path) or "."
        try:
            os.makedirs(dirpath, exist_ok=True)
        except Exception:
            pass

        fd, tmp_path = tempfile.mkstemp(dir=dirpath, prefix=".tmp_cache_", suffix=".pkl")
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, path)
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            self.logger.warning("Failed to write cache file %s: %s", path, e)

    def _load_pickle_safe(self, path: str) -> Optional[Dict]:
        """
        Load pickled object from path. If missing or corrupted, return None.
        On corruption attempt to delete file so future runs can recreate.
        """
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except (pickle.UnpicklingError, EOFError, OSError) as e:
            self.logger.warning("Cache file corrupt/unreadable (%s): %s. Removing.", path, e)
            try:
                os.remove(path)
            except Exception:
                self.logger.debug("Could not remove corrupt cache file: %s", path, exc_info=True)
            return None
        except Exception as e:
            self.logger.warning("Unexpected error loading cache %s: %s", path, e)
            return None

    def get_cached_result(self, cache_key: str) -> Optional[Dict]:
        """
        Return cached object if TTL not expired and file valid, otherwise None.
        """
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.pkl")
        if os.path.exists(cache_file):
            try:
                age = time.time() - os.path.getmtime(cache_file)
            except Exception:
                age = self.cache_ttl + 1
            if age < self.cache_ttl:
                loaded = self._load_pickle_safe(cache_file)
                if isinstance(loaded, dict):
                    return loaded
        return None

    def cache_result(self, cache_key: str, data: Dict):
        """
        Safely write cache (non-blocking callers will still wait for write).
        """
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.pkl")
        try:
            self._atomic_pickle_write(cache_file, data)
        except Exception:
            pass

    def search_text(self, query: str, max_results: int = 5) -> List[Dict]:
        """Basic text search using ddgs / duckduckgo_search."""
        self.logger.info("🔎 Text Search: '%s'", query)
        if not self.ddgs:
            self.logger.error("DDGS not available (install 'ddgs' or 'duckduckgo_search').")
            return []

        try:
            results = list(self.ddgs.text(
                query,
                max_results=max_results,
                region="wt-wt",
                safesearch="moderate"
            ))
            self.logger.debug("RAW_SEARCH_RESULTS: %s", results)
            return results
        except Exception as e:
            self.logger.error("Text search error: %s", e)
            return []

    def fetch_intelligent_content(self, url: str, max_length: int = 3000) -> str:
        """
        Try Trafilatura first. If it fails, fallback to requests + BeautifulSoup.
        Results are cached using the url as part of the cache key.
        """
        cache_key = self.get_cache_key(f"content_{url}", "content")
        cached = self.get_cached_result(cache_key)
        if cached:
            return cached.get("content", "")

        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False
                )
                if text:
                    final_text = text[:max_length]
                    if len(text) > max_length:
                        final_text += "..."
                    self.cache_result(cache_key, {"content": final_text, "url": url})
                    return final_text
        except Exception as e:
            self.logger.debug("Trafilatura attempt failed for %s: %s", url, e)

        try:
            resp = requests.get(url, headers=self.headers, timeout=8)
            status = getattr(resp, "status_code", "N/A")
            content_type = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and "text/html" in content_type:
                soup = BeautifulSoup(resp.text, "html.parser")
                article = soup.find("article")
                if article:
                    text = article.get_text(separator="\n").strip()
                else:
                    paragraphs = soup.find_all("p")
                    if paragraphs:
                        para_texts = [p.get_text().strip() for p in paragraphs if p.get_text().strip()]
                        text = "\n\n".join(para_texts[:20])
                    else:
                        text = ""
                if text:
                    final_text = text[:max_length]
                    if len(text) > max_length:
                        final_text += "..."
                    self.cache_result(cache_key, {"content": final_text, "url": url})
                    return final_text
            else:
                msg = f"Failed to download page (status {status})."
                self.logger.debug("Fetch fallback for %s: %s", url, msg)
                return msg
        except Exception as e:
            self.logger.warning("Requests/BS4 fallback failed for %s: %s", url, e)

        return "No readable text found."

    @staticmethod
    def _extract_url_from_result(r: Dict) -> Optional[str]:
        """
        Extract a plausible URL from a ddgs result dict.
        """
        if not isinstance(r, dict):
            return None
        for key in ("href", "url", "link", "href_link", "link_url"):
            if r.get(key):
                candidate = r.get(key)
                if isinstance(candidate, (list, tuple)):
                    candidate = candidate[0]
                if isinstance(candidate, str) and candidate.startswith("http"):
                    return candidate

        body = (r.get("body") or r.get("snippet") or "")
        m = re.search(r"https?://[^\s)\"'>]+", body)
        if m:
            return m.group(0)
        return None

    def search_and_fetch_parallel(self, query: str, num_pages: int = 2) -> List[Dict]:
        """
        Search (text) and then fetch page content in parallel.
        - num_pages controls search max results and maximum parallel fetches.
        - Uses bounded ThreadPoolExecutor to avoid runaway threads.
        """
        results = self.search_text(query, max_results=num_pages)
        if not results:
            return []

        urls = []
        for r in results:
            url = self._extract_url_from_result(r)
            if url:
                urls.append(url)

        if not urls:
            self.logger.warning("No URLs found in search results; constructing fallback search URL")
            urls = [f"https://www.bing.com/search?q={quote_plus(query)}"]

        max_workers = max(1, min(len(urls), num_pages, 4))
        url_content_map: Dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(self.fetch_intelligent_content, url): url for url in urls}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    url_content_map[url] = future.result()
                except Exception as e:
                    url_content_map[url] = f"Error fetching content: {e}"
                    self.logger.debug("Error fetching %s: %s", url, e)

        enhanced_results = []
        for r in results:
            url = self._extract_url_from_result(r) or ""
            enhanced_results.append({
                "title": r.get("title") or r.get("text") or "No Title",
                "url": url,
                "snippet": r.get("body") or r.get("snippet") or "",
                "full_content": url_content_map.get(url, "")
            })

        return enhanced_results

    def _simple_extractive_summary(self, text: str, max_sentences: int = 4) -> str:
        if not text:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        summary = " ".join(sentences[:max_sentences])
        return summary.strip()

    def summarize_text(self, text: str,
                       provider: str = "auto",
                       model: Optional[str] = None,
                       max_tokens: int = 256) -> str:
        """
        Summarize text using Google GenAI or OpenAI when available. Falls back to
        a simple extractive summary when model calls fail or no API key is present.
        """
        if not text:
            return ""

        google_key = os.getenv("GOOGLE_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")
        chosen = provider.lower()

        if chosen == "auto":
            if google_key:
                chosen = "google"
            elif openai_key:
                chosen = "openai"
            else:
                chosen = "none"

        if chosen == "google":
            try:
                try:
                    from google.generativeai import client as genai_client
                    genai_client.configure(api_key=google_key)
                    prompt = (
                        "Summarize the following content in 3–4 concise sentences, "
                        "listing main facts. Keep it factual and short:\n\n" + text
                    )
                    resp = genai_client.generate_text(
                        model=model or "gemini-1.5",
                        input=prompt,
                        max_output_tokens=max_tokens
                    )
                    if hasattr(resp, "text"):
                        return resp.text.strip()
                    if isinstance(resp, dict):
                        return resp.get("candidates", [{}])[0].get("content", "").strip() or \
                               self._simple_extractive_summary(text)
                    return self._simple_extractive_summary(text)
                except Exception:
                    from google.genai import client as genai_client2
                    genai_client2.configure(api_key=google_key)
                    prompt = (
                        "Summarize the following content in 3–4 concise sentences, "
                        "listing main facts. Keep it factual and short:\n\n" + text
                    )
                    resp = genai_client2.generate_text(
                        model=model or "gemini-1.5",
                        input=prompt,
                        max_output_tokens=max_tokens
                    )
                    return getattr(resp, "text", str(resp)).strip() or \
                           self._simple_extractive_summary(text)
            except Exception as e:
                self.logger.warning("Google GenAI summarization failed: %s", e)
                return self._simple_extractive_summary(text)

        if chosen == "openai":
            try:
                import openai
                openai.api_key = openai_key
                prompt = (
                    "Summarize the following content in 3–4 concise sentences, "
                    "listing main facts. Keep it factual and short:\n\n" + text
                )
                resp = openai.ChatCompletion.create(
                    model=model or "gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.2
                )
                summary = resp["choices"][0]["message"]["content"].strip()
                return summary
            except Exception as e:
                self.logger.warning("OpenAI summarization failed: %s", e)
                return self._simple_extractive_summary(text)

        return self._simple_extractive_summary(text)

    def quick_answer(self, query: str) -> str:
        """
        Return a short, direct answer for simple factual queries using search_text().
        Uses a small cache and avoids LLM calls for speed.
        """
        query = (query or "").strip()
        if not query:
            return ""

        cache_key = self.get_cache_key(query, "quick")
        cached = self.get_cached_result(cache_key)
        if cached and isinstance(cached, dict):
            ans = cached.get("answer", "")
            if ans:
                return ans

        results = self.search_text(query, max_results=3)
        if not results:
            return "No quick answer available."

        top = results[0] or {}
        snippet = (top.get("body") or top.get("snippet") or "").strip()
        title = (top.get("title") or top.get("text") or "").strip()

        if snippet:
            answer = self._simple_extractive_summary(snippet, max_sentences=2)
        elif title:
            answer = title
        else:
            answer = self._simple_extractive_summary(str(top), max_sentences=2)

        url = self._extract_url_from_result(top)
        self.cache_result(cache_key, {"answer": answer, "url": url})
        return answer
