"""
magnetar.aggregator
-------------------
Turns a flat list of Hit records into summary statistics:
  - Top visitors (by IP) with hit count and bot/human classification
  - Country breakdown (requires GeoIP2 mmdb)
  - Aggregated and disaggregated referrers (Domain vs Full URLs)
  - Extracted search engine keywords and campaign terms
  - Top article pages read
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import parse_qs, unquote_plus, urlparse

import geoip2.database
import geoip2.errors

from magnetar.log_parser import Hit


@dataclass
class VisitorRow:
    ip: str
    hits: int
    is_bot: bool
    country: str
    country_code: str
    city: str
    org: str
    top_ua: str
    top_path: str


@dataclass
class CountryRow:
    country: str
    country_code: str
    unique_ips: int
    hits: int


@dataclass
class RefererRow:
    referer: str
    hits: int


@dataclass
class ArticleRow:
    path: str
    hits: int


@dataclass
class KeywordRow:
    keyword: str
    source: str
    hits: int


@dataclass
class Summary:
    total_hits: int
    unique_ips: int
    human_hits: int
    bot_hits: int
    top_visitors: list[VisitorRow]
    countries: list[CountryRow]
    referrers: list[RefererRow]
    top_articles: list[ArticleRow]
    domain_referrers: list[RefererRow] = field(default_factory=list)
    full_referrers: list[RefererRow] = field(default_factory=list)
    search_keywords: list[KeywordRow] = field(default_factory=list)


def extract_search_keyword(referer_url: str) -> tuple[Optional[str], Optional[str]]:
    """Extract search query or topic keyword from referer URL if present."""
    if not referer_url or referer_url == "-":
        return None, None
    try:
        parsed = urlparse(referer_url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        query_dict = parse_qs(parsed.query)
        # Search query params
        for param in ["q", "query", "p", "k", "search", "search_query"]:
            if param in query_dict and query_dict[param]:
                kw = unquote_plus(query_dict[param][0]).strip()
                if kw:
                    return kw, domain

        # Campaign parameter
        if "utm_campaign" in query_dict and query_dict["utm_campaign"]:
            camp = unquote_plus(query_dict["utm_campaign"][0]).strip()
            if camp:
                return f"Campaign: {camp}", domain

        # Reddit / Subreddit path
        if "reddit.com/r/" in referer_url:
            sub = referer_url.split("reddit.com/r/")[1].split("/")[0]
            return f"r/{sub}", "reddit.com"

    except Exception:
        pass
    return None, None


def build_summary(
    hits: list[Hit],
    geoip_db_path: Optional[str] = None,
    top_n: int = 25,
) -> Summary:
    # --- GeoIP reader (optional) ---
    reader = None
    if geoip_db_path:
        try:
            reader = geoip2.database.Reader(geoip_db_path)
        except Exception:
            pass

    def geoip(ip: str) -> tuple[str, str, str]:
        """Returns (country, country_code, city)."""
        if reader is None:
            return "Unknown", "??", ""
        try:
            r = reader.country(ip)
            return (
                r.country.name or "Unknown",
                r.country.iso_code or "??",
                "",
            )
        except geoip2.errors.AddressNotFoundError:
            return "Unknown", "??", ""

    # --- Per-IP aggregation ---
    ip_hits: dict[str, list[Hit]] = defaultdict(list)
    for h in hits:
        ip_hits[h.ip].append(h)

    visitor_rows: list[VisitorRow] = []
    country_ips: dict[str, set[str]] = defaultdict(set)
    country_hits: dict[str, int] = Counter()

    for ip, ip_hit_list in ip_hits.items():
        country, cc, city = geoip(ip)
        is_bot = any(h.is_bot for h in ip_hit_list)
        ua_counter = Counter(h.user_agent for h in ip_hit_list if h.user_agent)
        path_counter = Counter(h.path for h in ip_hit_list if h.path)

        visitor_rows.append(VisitorRow(
            ip=ip,
            hits=len(ip_hit_list),
            is_bot=is_bot,
            country=country,
            country_code=cc,
            city=city,
            org="",
            top_ua=ua_counter.most_common(1)[0][0] if ua_counter else "",
            top_path=path_counter.most_common(1)[0][0] if path_counter else "",
        ))

        country_ips[country].add(ip)
        country_hits[country] += len(ip_hit_list)

    visitor_rows.sort(key=lambda r: r.hits, reverse=True)

    # --- Countries ---
    country_rows: list[CountryRow] = []
    for country, ips in country_ips.items():
        cc = next((r.country_code for r in visitor_rows if r.country == country), "??")
        country_rows.append(CountryRow(
            country=country,
            country_code=cc,
            unique_ips=len(ips),
            hits=country_hits[country],
        ))
    country_rows.sort(key=lambda r: r.hits, reverse=True)

    # --- Referrers: Both Domain-Aggregated and Disaggregated Full URLs ---
    full_ref_counter: Counter = Counter()
    domain_ref_counter: Counter = Counter()
    keyword_counter: dict[tuple[str, str], int] = Counter()

    for h in hits:
        ref = (h.referer or "").strip()
        h_domain = getattr(h, "domain", "")
        if ref and ref != "-" and (not h_domain or h_domain not in ref):
            full_ref_counter[ref] += 1
            # Extract domain
            try:
                d = urlparse(ref).netloc.lower()
                if d.startswith("www."):
                    d = d[4:]
                if d:
                    domain_ref_counter[d] += 1
            except Exception:
                domain_ref_counter[ref] += 1

            # Extract search terms / keywords
            kw, source = extract_search_keyword(ref)
            if kw and source:
                keyword_counter[(kw, source)] += 1

    full_referrer_rows = [RefererRow(ref, cnt) for ref, cnt in full_ref_counter.most_common(top_n)]
    domain_referrer_rows = [RefererRow(dom, cnt) for dom, cnt in domain_ref_counter.most_common(top_n)]
    keyword_rows = [
        KeywordRow(keyword=kw_src[0], source=kw_src[1], hits=cnt)
        for kw_src, cnt in Counter(keyword_counter).most_common(top_n)
    ]

    # --- Top articles (page paths only, humans only) ---
    _SKIP_PATHS = {"/", "/index.html", "/favicon.ico", "/robots.txt", "/ads.txt"}
    _SKIP_PREFIXES = (
        "/api", "/static", "/.well-known", "/wp-", "/pagina/",
        "/uploads/", "/styles-", "/main-", "/chunk-", "/polyfills-",
    )
    article_counter: Counter = Counter()
    for h in hits:
        p = h.path.split("?")[0]
        if (
            not h.is_bot
            and h.status == 200
            and p not in _SKIP_PATHS
            and not any(p.startswith(pfx) for pfx in _SKIP_PREFIXES)
        ):
            article_counter[p] += 1
    article_rows = [ArticleRow(path, cnt) for path, cnt in article_counter.most_common(top_n)]

    if reader:
        reader.close()

    human_hits = sum(1 for h in hits if not h.is_bot)
    bot_hits = sum(1 for h in hits if h.is_bot)

    return Summary(
        total_hits=len(hits),
        unique_ips=len(ip_hits),
        human_hits=human_hits,
        bot_hits=bot_hits,
        top_visitors=visitor_rows[:top_n],
        countries=country_rows,
        referrers=full_referrer_rows,
        top_articles=article_rows,
        domain_referrers=domain_referrer_rows,
        full_referrers=full_referrer_rows,
        search_keywords=keyword_rows,
    )
