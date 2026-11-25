"""Evidence-based, conservative website/blog qualification; no page execution."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
import time
from urllib.parse import urljoin, urlsplit, unquote
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from backend.services.qualification_http import FetchError, PublicHTTP, USER_AGENT, normalize_url

BLOG_PATHS = ("/blog", "/noticias", "/artigos", "/conteudo", "/news")
BLOG_WORD = re.compile(r"(?:blog|not[ií]cias|artigos|conte[uú]do|news|insights)", re.I)


def robots_allows(lines, url):
    """RFC wildcard/end-anchor restrictions in addition to RobotFileParser.

    Python 3.12's parser treats '*' literally. Resolve user-agent groups and
    longest matching rule here so wildcard restrictions cannot be bypassed.
    """
    groups, agents, rules = [], [], []
    for raw in [*lines, "User-agent: __end__"]:
        line = raw.split("#", 1)[0].strip()
        if ":" not in line: continue
        key, value = [part.strip() for part in line.split(":", 1)]
        if key.lower() == "user-agent":
            if rules:
                groups.append((agents, rules)); agents, rules = [], []
            agents.append(value.lower())
        elif key.lower() in {"allow", "disallow"} and agents and value:
            rules.append((key.lower() == "allow", value))
    relevant = []
    for agents, rules in groups:
        scores = [0 if agent == "*" else len(agent) for agent in agents if agent == "*" or agent in USER_AGENT.lower()]
        if scores: relevant.append((max(scores), rules))
    if not relevant: return True
    best = max(score for score, _ in relevant)
    path = unquote(urlsplit(url).path + ("?" + urlsplit(url).query if urlsplit(url).query else ""))
    matches = []
    for score, rules in relevant:
        if score != best: continue
        for allow, pattern in rules:
            end = pattern.endswith("$")
            pattern = unquote(pattern[:-1] if end else pattern)
            regex = "^" + re.escape(pattern).replace(r"\*", ".*") + ("$" if end else "")
            if re.search(regex, path): matches.append((len(pattern.replace("*", "")), allow))
    return max(matches, default=(0, True))[1]


def same_site(left, right):
    return (urlsplit(left).hostname or "").removeprefix("www.") == (urlsplit(right).hostname or "").removeprefix("www.")


def clean(value, limit=500):
    return re.sub(r"[\x00-\x1f\x7f]", " ", BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True))[:limit] or None


def publication_date(value, now):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        date = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            date = parsedate_to_datetime(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    date = date.astimezone(timezone.utc)
    return date if datetime(1990, 1, 1, tzinfo=timezone.utc) <= date <= now else None


def priority_for(*, available, wordpress, blog, days, total):
    if available != "accessible":
        return "INCONCLUSIVE"
    # Verified recency always wins, including on non-WordPress sites.
    if days is not None:
        return "LOW" if days <= 30 else "MEDIUM" if days <= 90 else "HIGH" if wordpress == "confirmed" else "MEDIUM"
    if blog == "missing_verified" or total == 0:
        return "HIGH" if wordpress == "confirmed" else "MEDIUM"
    return "INCONCLUSIVE"


class Crawler:
    def __init__(self, http):
        self.http = http
        self.robots = {}
        self.errors = []
        self.root = None
        self.halted = False

    def policy(self, url):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            def robots_redirect(destination):
                if urlsplit(destination).path != "/robots.txt":
                    raise FetchError("robots_redirect_rejected")
            page = self.http.get(origin + "/robots.txt", before_request=robots_redirect)
            robot = RobotFileParser()
            lines = []
            if page.status in {404, 410}:
                robot.parse([])
            elif page.status == 200 and not page.text.lstrip().startswith("<"):
                lines = page.text.splitlines()
                robot.parse(lines)
            else:
                raise FetchError("robots_unavailable")
            robot.qualification_lines = lines
            self.robots[origin] = robot
        robot = self.robots[origin]
        if not robot.can_fetch(USER_AGENT, url) or not robots_allows(robot.qualification_lines, url):
            raise FetchError("robots_disallowed")
        rate = robot.request_rate(USER_AGENT)
        delay = max(0.5, robot.crawl_delay(USER_AGENT) or 0, rate.seconds / rate.requests if rate and rate.requests else 0)
        # Transport enforces pacing INSIDE its shared host lock, including retries.
        host = parts.hostname.removeprefix("www.")
        if time.monotonic() + delay >= self.http.deadline:
            raise FetchError("crawl_delay_exceeds_budget")
        self.http.host_delays[host] = delay

    def get(self, url, *, initial=False):
        if self.halted:
            raise FetchError("site_blocked_stop")
        url = normalize_url(url)
        def guard(destination):
            if not initial and self.root and not same_site(self.root, destination):
                raise FetchError("off_site_redirect")
            self.policy(destination)
        page = self.http.get(url, before_request=guard)
        if page.status in {401, 403, 429}: self.halted = True
        return page


def _xml(body):
    # No DTD/entity expansion, external entities, gzip or unconstrained XML trees.
    if re.search(br"<!\s*(DOCTYPE|ENTITY)", body, re.I):
        raise ValueError("xml_entities_rejected")
    return ET.fromstring(body)


def _tag(element):
    return element.tag.rsplit("}", 1)[-1].lower()


def analyze_website(website, *, http=None, now=None):
    now = now or datetime.now(timezone.utc)
    result = dict(normalized_website=None, site_availability="unavailable", cms="unknown", cms_name=None,
                  wordpress_status="inconclusive", blog_status="inconclusive", blog_url=None,
                  total_posts=None, last_published_at=None, last_post_title=None, last_post_url=None,
                  days_since_publication=None, priority="INCONCLUSIVE", validation_status="inconclusive",
                  checked_at=now, evidence=[], errors=[])
    crawler = Crawler(http or PublicHTTP())
    evidence, errors, articles = result["evidence"], result["errors"], []
    visited, page_links, feeds, sitemap_links, blog_links = set(), [], [], [], []
    complete_sitemap, sitemap_urls, api_valid = False, [], False

    def add_article(date, title, url, source):
        date = publication_date(date, now)
        try:
            url = normalize_url(urljoin(result["normalized_website"], str(url or "")))
        except FetchError:
            return
        if date and same_site(url, result["normalized_website"]):
            articles.append((date, clean(title), url, source))

    def html(page):
        soup = BeautifulSoup(page.text, "html.parser")
        lower = page.text.lower()
        indicators = [word for word in ("wp-content/", "wp-includes/", "wp-json") if word in lower]
        generator = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
        generator_value = str(generator.get("content", "")) if generator else ""
        if indicators or "wordpress" in generator_value.lower():
            result.update(cms="WordPress", cms_name="WordPress", wordpress_status="confirmed")
            evidence.append({"source": "html", "reason": "wordpress_markers", "indicators": indicators + (["generator"] if "wordpress" in generator_value.lower() else [])})
        elif result["cms"] != "WordPress":
            for platform in ("Drupal", "Joomla", "Wix", "Squarespace", "Ghost", "Shopify"):
                if platform.lower() in generator_value.lower() or (platform == "Shopify" and "cdn.shopify.com/" in lower):
                    result.update(cms="other", cms_name=platform)
                    evidence.append({"source": "html", "reason": "platform_generator", "platform": platform})
                    break
        for a in soup.find_all("a", href=True)[:500]:
            try:
                target = normalize_url(urljoin(page.url, a["href"]))
            except FetchError:
                continue
            if same_site(target, result["normalized_website"]):
                page_links.append(target)
                if BLOG_WORD.search(a.get_text(" ") + urlsplit(target).path):
                    blog_links.append(target)
            elif BLOG_WORD.search(a.get_text(" ") + urlsplit(target).path):
                # An externally hosted blog is evidence AGAINST absence, but is
                # outside this company's same-site crawling boundary.
                errors.append("external_blog_reference_not_crawled")
                evidence.append({"source": "html", "reason": "external_blog_reference_not_crawled"})
        for link in soup.find_all("link", href=True):
            if "alternate" in link.get("rel", []) and any(x in str(link.get("type", "")) for x in ("rss", "atom")):
                feeds.append(urljoin(page.url, link["href"]))
        title = soup.title.get_text(" ", strip=True) if soup.title else None
        # Published metadata only. Generic dates and dateModified/lastmod are ignored.
        published = soup.find("meta", attrs={"property": "article:published_time"})
        if published:
            add_article(published.get("content"), title, page.url, "article:published_time")
        for script in soup.find_all("script", type="application/ld+json")[:20]:
            try:
                data = json.loads(script.string or script.get_text())
                stack = list(data) if isinstance(data, list) else [data]
                for _ in range(150):
                    if not stack:
                        break
                    item = stack.pop()
                    if not isinstance(item, dict):
                        continue
                    types = item.get("@type", [])
                    types = [types] if isinstance(types, str) else types
                    if any(t in {"Article", "BlogPosting", "NewsArticle"} for t in types):
                        add_article(item.get("datePublished"), item.get("headline") or item.get("name"), item.get("url") or page.url, "json_ld_datePublished")
                    for value in item.values():
                        if isinstance(value, dict): stack.append(value)
                        elif isinstance(value, list): stack.extend(value)
            except (ValueError, TypeError):
                errors.append("malformed_json_ld")
        for tag in soup.find_all("time", datetime=True)[:30]:
            attrs = " ".join(tag.get("class", [])) + " " + str(tag.get("itemprop", ""))
            if ("datePublished" in attrs or (tag.find_parent("article") and re.search(r"published|entry-date", attrs))) and not re.search(r"updated|modified", attrs, re.I):
                article = tag.find_parent("article")
                anchor = article.find("a", href=True) if article else None
                add_article(tag["datetime"], title, urljoin(page.url, anchor["href"]) if anchor else page.url, "published_time_element")
        if soup.find("article") or published or articles:
            result["blog_status"] = "detected"
            result["blog_url"] = result["blog_url"] or page.url

    def fetch(url):
        try:
            if not same_site(result["normalized_website"], normalize_url(url)) or url in visited:
                return None
            visited.add(url)
            page = crawler.get(url)
            if page.status in {401, 403, 429}:
                errors.append(f"http_{page.status}")
            return page
        except FetchError as error:
            errors.append(str(error))
            return None

    try:
        normalized = normalize_url(website)
        result["normalized_website"] = normalized
        home = crawler.get(normalized, initial=True)
        if home.status != 200:
            result["site_availability"] = "blocked" if home.status in {401, 403, 429} else "unavailable"
            errors.append(f"http_{home.status}")
            return result
        result.update(normalized_website=home.url, site_availability="accessible")
        crawler.root = home.url
        visited.add(home.url)
        html(home)
        origin = f"{urlsplit(home.url).scheme}://{urlsplit(home.url).netloc}"
        api = fetch(origin + "/wp-json/")
        if api and api.status == 200:
            try:
                info = json.loads(api.body)
                if isinstance(info, dict) and ("wp/v2" in info.get("namespaces", []) or "/wp/v2/posts" in info.get("routes", {})):
                    result.update(cms="WordPress", cms_name="WordPress", wordpress_status="confirmed")
                    evidence.append({"source": "wp-json", "reason": "wordpress_api_namespace"})
            except (ValueError, TypeError):
                errors.append("malformed_api_json")
        if result["wordpress_status"] != "confirmed":
            login = fetch(origin + "/wp-login.php")
            if login and login.status == 200:
                form = BeautifulSoup(login.text, "html.parser").find("form")
                if form and (form.get("id") == "loginform" or form.find(attrs={"id": "wp-submit"}) or form.find(attrs={"name": "wp-submit"})):
                    result.update(cms="WordPress", cms_name="WordPress", wordpress_status="confirmed")
                    evidence.append({"source": "wp-login.php", "reason": "wordpress_login_form"})
        if result["wordpress_status"] == "confirmed":
            posts = fetch(origin + "/wp-json/wp/v2/posts?per_page=1&orderby=date&order=desc&_fields=date,link,title")
            if posts and posts.status == 200:
                try:
                    data = json.loads(posts.body)
                    if not isinstance(data, list) or len(data) > 1:
                        raise ValueError()
                    total_header = posts.headers.get("x-wp-total")
                    total = int(total_header) if total_header is not None else None
                    if total is not None and (total < len(data) or (not data and total != 0)):
                        raise ValueError()
                    api_valid = True
                    result.update(blog_status="detected", blog_url=next(iter(blog_links), origin + "/"), total_posts=total if data else 0)
                    evidence.append({"source": "wp_posts_api", "reason": "published_posts_exposed" if data else "no_posts_exposed", "total": result["total_posts"]})
                    if data:
                        post = data[0]
                        add_article(post.get("date"), post.get("title", {}).get("rendered"), post.get("link"), "wp_posts_api")
                except (ValueError, TypeError, AttributeError):
                    api_valid = False
                    errors.append("malformed_posts_api")
            else:
                errors.append("posts_api_inaccessible")
        # Accessible REST data is authoritative; otherwise inspect public alternatives.
        if not api_valid:
            if result["wordpress_status"] != "confirmed" and api and api.status in {404, 410}:
                result["wordpress_status"] = "not_detected"
            for robot in crawler.robots.values():
                sitemap_links.extend(robot.site_maps() or [])
            sitemap_links.append(origin + "/sitemap.xml")
            sitemap_queue = list(dict.fromkeys(sitemap_links))
            all_complete = True
            seen_maps = set()
            while sitemap_queue and len(seen_maps) < 4:
                url = sitemap_queue.pop(0)
                if url in seen_maps: continue
                seen_maps.add(url)
                page = fetch(url)
                if not page or page.status != 200:
                    all_complete = False
                    continue
                try:
                    tree = _xml(page.body)
                    locations = [e.text for e in tree.iter() if _tag(e) == "loc" and e.text]
                    if len(locations) > 250:
                        all_complete = False
                    if _tag(tree) == "sitemapindex":
                        sitemap_queue.extend(locations[:4])
                    elif _tag(tree) == "urlset":
                        sitemap_urls.extend(locations[:250])
                    else:
                        all_complete = False
                except (ValueError, ET.ParseError):
                    errors.append("malformed_sitemap")
                    all_complete = False
            complete_sitemap = bool(sitemap_urls) and all_complete and not sitemap_queue
            blog_links.extend(url for url in sitemap_urls if BLOG_WORD.search(urlsplit(url).path))
            targets = list(dict.fromkeys(blog_links + [origin + path for path in BLOG_PATHS]))
            missing_routes = 0
            for target in targets[:8]:
                page = fetch(target)
                if page and page.status == 200:
                    html(page)
                    if target in blog_links:
                        result.update(blog_status="detected", blog_url=result["blog_url"] or page.url)
                elif page and page.status in {404, 410} and urlsplit(target).path in BLOG_PATHS:
                    missing_routes += 1
            # Inspect a few linked articles, including same-site navigation discoveries.
            candidates = list(dict.fromkeys(page_links + sitemap_urls))
            for target in [u for u in candidates if BLOG_WORD.search(urlsplit(u).path) and u not in visited][:3]:
                page = fetch(target)
                if page and page.status == 200: html(page)
            # A sitemap without a /blog path does not establish absence: article
            # permalinks can have arbitrary names. Audit every listed/navigation
            # page of a small complete site before making a negative conclusion.
            exhausted = False
            if complete_sitemap and len(set(sitemap_urls + page_links)) <= 8:
                audited = set(visited)
                exhausted = True
                for _ in range(8):
                    remaining = [u for u in dict.fromkeys(sitemap_urls + page_links) if u not in audited]
                    if not remaining: break
                    if len(set(sitemap_urls + page_links)) > 8:
                        exhausted = False; break
                    target = remaining[0]; audited.add(target)
                    page = fetch(target)
                    if not page or page.status != 200:
                        exhausted = False; break
                    html(page)
                exhausted = exhausted and all(u in audited for u in sitemap_urls + page_links)
            for url in list(dict.fromkeys(feeds + [origin + "/feed/"]))[:3]:
                page = fetch(url)
                if not page or page.status != 200: continue
                try:
                    tree = _xml(page.body)
                    entries = [e for e in tree.iter() if _tag(e) in {"item", "entry"}]
                    if entries:
                        result.update(blog_status="detected", blog_url=result["blog_url"] or page.url)
                    for entry in entries[:100]:
                        fields = {_tag(e): e for e in entry}
                        date = fields.get("pubdate") if "pubdate" in fields else fields.get("published")
                        link = fields.get("link")
                        title = fields.get("title")
                        if date is not None and link is not None:
                            add_article(date.text, title.text if title is not None else None, link.get("href") or link.text, "feed_published")
                except (ValueError, ET.ParseError):
                    errors.append("malformed_feed")
            if result["blog_status"] != "detected" and complete_sitemap and exhausted and missing_routes == len(BLOG_PATHS) and not blog_links and not errors:
                result["blog_status"] = "missing_verified"
                evidence.append({"source": "bounded_discovery", "reason": "complete_small_sitemap_no_blog_and_all_routes_absent", "sitemap_urls": len(sitemap_urls)})
        if articles:
            latest = max(articles, key=lambda a: a[0])
            result.update(last_published_at=latest[0], last_post_title=latest[1], last_post_url=latest[2],
                          days_since_publication=(now.date() - latest[0].date()).days, blog_status="detected")
            evidence.append({"source": latest[3], "reason": "verified_publication_date", "date": latest[0].isoformat()})
        result["priority"] = priority_for(available=result["site_availability"], wordpress=result["wordpress_status"],
                                          blog=result["blog_status"], days=result["days_since_publication"], total=result["total_posts"])
        if "external_blog_reference_not_crawled" in errors and (result["days_since_publication"] is None or result["days_since_publication"] > 30):
            result["priority"] = "INCONCLUSIVE"
        result["validation_status"] = "validated" if result["priority"] != "INCONCLUSIVE" else "inconclusive"
        if not evidence:
            evidence.append({"source": "bounded_discovery", "reason": "insufficient_blog_evidence"})
    except FetchError as error:
        errors.append(str(error))
        if "robots" in str(error): result["site_availability"] = "blocked"
    except (ValueError, TypeError, RecursionError):
        errors.append("invalid_site_content")
    result["errors"] = list(dict.fromkeys(errors))[:30]
    result["evidence"] = evidence[:30]
    return result
