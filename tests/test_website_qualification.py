from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from backend.services import qualification_http as transport
from backend.services import website_qualification as analyzer

NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
ROOT = "https://company.example/"
POSTS = ROOT + "wp-json/wp/v2/posts?per_page=1&orderby=date&order=desc&_fields=date,link,title"


class FakeHTTP:
    def __init__(self, pages):
        self.pages, self.calls, self.deadline = pages, [], float("inf")
        self.host_delays = {}

    def get(self, url, *, before_request=None):
        if before_request: before_request(url)
        self.calls.append(url)
        value = self.pages.get(url, (404, ""))
        status, body, *headers = value
        if not isinstance(body, (str, bytes)): body = json.dumps(body)
        return transport.Page(url, status, headers[0] if headers else {}, body.encode() if isinstance(body, str) else body)


@pytest.fixture(autouse=True)
def no_real_pacing(monkeypatch):
    transport._last_request.clear()
    monkeypatch.setattr(analyzer.time, "sleep", lambda _: None)


def analyze(pages):
    pages = {ROOT: (200, "<html><title>Company</title></html>"), ROOT + "robots.txt": (404, ""), **pages}
    http = FakeHTTP(pages)
    return analyzer.analyze_website(ROOT, http=http, now=NOW), http


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.org", "gopher://example.org", "https://a:b@example.org", "http://127.0.0.1", "http://127.1", "http://[::1]", "http://169.254.169.254/latest/meta-data", "http://10.0.0.1", "http://192.168.1.1", "http://[::ffff:8.8.8.8]", "http://[64:ff9b::a00:1]", "http://[fe80::1%25en0]", "https://localhost", "http://metadata.google.internal", "https://x.local", "http://example.org:8080", "https://example.org/\nsecret", "https://example.org\\@127.0.0.1"])
def test_bad_urls_are_rejected_before_connect(url, monkeypatch):
    monkeypatch.setattr(transport, "resolve_public", lambda _: pytest.fail("must not resolve"))
    with pytest.raises(transport.FetchError):
        transport.PublicHTTP().get(url)


@pytest.mark.parametrize("ip", ["0.0.0.0", "100.64.0.1", "168.63.129.16", "198.18.0.1", "224.0.0.1", "240.0.0.1", "::", "fc00::1", "ff02::1", "2001:db8::1", "2002:0808:0808::1", "::ffff:127.0.0.1"])
def test_non_public_and_transition_addresses_rejected(ip):
    with pytest.raises(transport.FetchError): transport.public_ip(ip)


def test_all_dns_answers_validated_and_mixed_public_private_rejected(monkeypatch):
    class Resolver:
        def resolve(self, host, kind, **_):
            return [SimpleNamespace(address="8.8.8.8" if kind == "A" else "::1")]
    monkeypatch.setattr(transport.dns.resolver, "Resolver", Resolver)
    with pytest.raises(transport.FetchError, match="non_public_address"): transport.resolve_public("company.example")


def test_rebinding_cannot_change_connected_numeric_address_and_peer_checked(monkeypatch):
    connected = []
    class Sock:
        def settimeout(self, timeout): pass
        def connect(self, pair): connected.append(pair)
        def getpeername(self): return ("8.8.8.8", 80)
        def close(self): pass
    monkeypatch.setattr(transport.socket, "socket", lambda *_: Sock())
    monkeypatch.setattr(transport.socket, "getaddrinfo", lambda *_: pytest.fail("second DNS lookup"))
    client = transport.PinnedConnection("company.example", "8.8.8.8", "http", 1)
    client.connect()
    assert connected == [("8.8.8.8", 80)]
    Sock.getpeername = lambda _: ("127.0.0.1", 80)
    with pytest.raises(transport.FetchError): client.connect()


def test_tls_uses_original_hostname_and_validated_public_peer(monkeypatch):
    seen = []
    class Sock:
        def settimeout(self, *_): pass
        def connect(self, pair): seen.append(pair)
        def getpeername(self): return ("8.8.8.8", 443)
        def close(self): pass
    context = SimpleNamespace(set_alpn_protocols=lambda _: None, wrap_socket=lambda sock, server_hostname: seen.append(server_hostname) or sock)
    monkeypatch.setattr(transport.socket, "socket", lambda *_: Sock())
    monkeypatch.setattr(transport.ssl, "create_default_context", lambda: context)
    transport.PinnedConnection("company.example", "8.8.8.8", "https", 1).connect()
    assert seen == [("8.8.8.8", 443), "company.example"]


def test_redirect_to_metadata_is_never_connected_and_proxies_unused(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    monkeypatch.setattr(transport, "resolve_public", lambda _: ["8.8.8.8"])
    calls = []
    def request(self, url, address):
        calls.append((url, address))
        return transport.Page(url, 302, {"location":"http://169.254.169.254/"}, b"")
    monkeypatch.setattr(transport.PublicHTTP, "_request", request)
    with pytest.raises(transport.FetchError): transport.PublicHTTP().get(ROOT)
    assert calls == [(ROOT, "8.8.8.8")]


def test_redirect_limit_and_policy_applied_every_hop(monkeypatch):
    monkeypatch.setattr(transport, "resolve_public", lambda _: ["8.8.8.8"])
    monkeypatch.setattr(transport.PublicHTTP, "_request", lambda _, u, ip: transport.Page(u,302,{"location":u+"x"},b""))
    checked = []
    with pytest.raises(transport.FetchError, match="redirect_limit"):
        transport.PublicHTTP().get(ROOT, before_request=checked.append)
    assert len(checked) == 5


@pytest.mark.parametrize("marker", ["<img src='/wp-content/a.png'>", "<script src='/wp-includes/a.js'></script>", "<meta name='generator' content='WordPress 6'>", "<link href='/wp-json/'>"])
def test_wordpress_html_indicators_and_empty_api(marker):
    result, _ = analyze({ROOT:(200,marker), POSTS:(200,[],{})})
    assert result["wordpress_status"] == "confirmed"
    assert result["total_posts"] == 0 and result["priority"] == "HIGH"
    assert any(e["reason"] == "no_posts_exposed" for e in result["evidence"])


def test_login_requires_actual_form_and_200_alone_never_confirms():
    result, _ = analyze({ROOT+"wp-login.php":(200,"<h1>Generic login</h1>"), ROOT+"wp-json/":(200,{})})
    assert result["wordpress_status"] == "inconclusive" and result["priority"] == "INCONCLUSIVE"
    result, _ = analyze({ROOT+"wp-login.php":(200,"<form id='loginform'><input id='wp-submit'></form>"), POSTS:(200,[])})
    assert result["wordpress_status"] == "confirmed"


def test_rest_namespace_and_sorted_latest_post_count():
    date = (NOW-timedelta(days=20)).isoformat()
    result, http = analyze({ROOT+"wp-json/":(200,{"namespaces":["wp/v2"]}), POSTS:(200,[{"date":date,"link":ROOT+"article","title":{"rendered":"<b>News</b>"}}],{"x-wp-total":"51"})})
    assert result["total_posts"] == 51 and result["last_post_title"] == "News"
    assert result["days_since_publication"] == 20 and result["priority"] == "LOW"
    assert POSTS in http.calls


@pytest.mark.parametrize("status,body", [(403,{}),(429,{}),(500,{}),(200,"bad-json"),(200,{"error":"blocked"})])
def test_inaccessible_or_malformed_api_never_means_empty(status, body):
    result, _ = analyze({ROOT:(200,"wp-content/"), POSTS:(status,body)})
    assert result["total_posts"] is None and result["priority"] == "INCONCLUSIVE"


@pytest.mark.parametrize("days,expected", [(0,"LOW"),(30,"LOW"),(31,"MEDIUM"),(90,"MEDIUM"),(91,"HIGH")])
def test_wordpress_recency_boundaries(days, expected):
    result,_=analyze({ROOT:(200,"wp-content/"), POSTS:(200,[{"date":(NOW-timedelta(days=days)).isoformat(),"link":ROOT+"post","title":{"rendered":"Title"}}])})
    assert result["priority"] == expected


def test_other_cms_jsonld_datepublished_not_modified_and_navigation():
    page = '<meta name="generator" content="Ghost"><a href="/blog">Blog</a>'
    article = '<script type="application/ld+json">'+json.dumps({"@type":"BlogPosting","datePublished":(NOW-timedelta(days=100)).isoformat(),"dateModified":NOW.isoformat(),"headline":"Original","url":ROOT+"blog/post"})+'</script>'
    result, _ = analyze({ROOT:(200,page), ROOT+"blog":(200,'<a href="/blog/post">Article</a>'), ROOT+"blog/post":(200,article)})
    assert result["cms_name"] == "Ghost" and result["cms"] == "other"
    assert result["days_since_publication"] == 100 and result["priority"] == "MEDIUM"


def test_feed_publication_ignores_updated_and_uses_latest_across_blogs():
    home = '<link rel="alternate" type="application/atom+xml" href="/feed.atom">'
    feed = '<feed><entry><title>Newest</title><link href="/article"/><published>2026-11-20T12:00:00Z</published><updated>2026-11-25T12:00:00Z</updated></entry><entry><link href="/older"/><published>2026-01-01T00:00:00Z</published></entry></feed>'
    result,_=analyze({ROOT:(200,home),ROOT+"feed.atom":(200,feed)})
    assert result["days_since_publication"] == 5 and result["last_post_title"] == "Newest"


def test_sitemap_indexes_discover_blog_but_lastmod_never_publication():
    result,http=analyze({ROOT+"robots.txt":(200,"Sitemap: "+ROOT+"index.xml"),ROOT+"index.xml":(200,"<sitemapindex><sitemap><loc>"+ROOT+"posts.xml</loc></sitemap></sitemapindex>"),ROOT+"posts.xml":(200,"<urlset><url><loc>"+ROOT+"blog/post</loc><lastmod>2026-11-25</lastmod></url></urlset>"),ROOT+"blog/post":(200,"<article><time datetime='2026-11-25'>Modified</time>Post without publication date</article>")})
    assert ROOT+"blog/post" in http.calls
    assert result["last_published_at"] is None and result["priority"] == "INCONCLUSIVE"


def test_guessed_404s_do_not_prove_missing_blog():
    result,_=analyze({})
    assert result["blog_status"] == "inconclusive" and result["priority"] == "INCONCLUSIVE"


def test_verified_missing_requires_complete_sitemap_and_all_routes_absent():
    result,_=analyze({ROOT+"sitemap.xml":(200,"<urlset><url><loc>"+ROOT+"about</loc></url></urlset>"),ROOT+"about":(200,"About our company")})
    assert result["blog_status"] == "missing_verified" and result["priority"] == "MEDIUM"


def test_robots_blocks_home_and_wildcard_routes():
    result,http=analyze({ROOT+"robots.txt":(200,"User-agent: *\nDisallow: /")})
    assert result["site_availability"] == "blocked" and ROOT not in http.calls
    assert not analyzer.robots_allows(["User-agent: *","Disallow: /*?*"], ROOT+"?secret=1")
    assert analyzer.robots_allows(["User-agent: *","Disallow: /private*","Allow: /private/public$"],ROOT+"private/public")


def test_blocking_stops_subsequent_requests_and_never_executes_js():
    result,http=analyze({ROOT:(200,"wp-content/<script>fetch('http://127.0.0.1')</script>"),ROOT+"wp-json/":(429,"")})
    assert result["total_posts"] is None
    assert http.calls == [ROOT+"robots.txt",ROOT,ROOT+"wp-json/"]


def test_future_modified_ambiguous_and_entity_xml_remain_inconclusive():
    result,_=analyze({ROOT:(200,'<script type="application/ld+json">{"@type":"Article","dateModified":"2026-11-25"}</script><time datetime="2026-11-20">Updated</time>'),ROOT+"sitemap.xml":(200,'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><urlset/>')})
    assert result["last_published_at"] is None and result["priority"] == "INCONCLUSIVE"
    assert analyzer.publication_date("2027-01-01",NOW) is None
    assert analyzer.publication_date("bad",NOW) is None


def test_sitemap_with_custom_article_permalink_cannot_be_called_missing():
    article='<script type="application/ld+json">{"@type":"Article","datePublished":"2026-11-20","headline":"Custom article"}</script>'
    result,_=analyze({ROOT+"sitemap.xml":(200,"<urlset><url><loc>"+ROOT+"our-story</loc></url></urlset>"),ROOT+"our-story":(200,article)})
    assert result["blog_status"] == "detected" and result["priority"] == "LOW"


def test_external_blog_reference_blocks_false_absence_or_inactivity_claim():
    result,http=analyze({ROOT:(200,'wp-content/<a href="https://blog.other.example/">Our blog</a>'),POSTS:(200,[])})
    assert result["priority"] == "INCONCLUSIVE"
    assert not any("other.example" in url for url in http.calls)


def test_crawl_delay_and_request_rate_are_passed_to_transport():
    http=FakeHTTP({ROOT+"robots.txt":(200,"User-agent: *\nCrawl-delay: 2\nRequest-rate: 1/5")})
    crawler=analyzer.Crawler(http)
    crawler.policy(ROOT)
    assert http.host_delays["company.example"] == 5


def test_wire_http_client_limits_size_compression_and_retries(monkeypatch):
    """Real HTTP parser over isolated socketpairs, without any network address."""
    import socket
    import threading
    monkeypatch.setattr(transport,"resolve_public",lambda _: ["8.8.8.8"])
    payloads=[]
    def connect(connection):
        client,server=socket.socketpair()
        connection.sock=transport.DeadlineSocket(client,connection.deadline,connection.timeout)
        payload=payloads.pop(0)
        def respond():
            try:
                server.recv(8192)
                server.sendall(payload)
            except OSError: pass
            finally: server.close()
        threading.Thread(target=respond,daemon=True).start()
    monkeypatch.setattr(transport.PinnedConnection,"connect",connect)
    payloads[:]=[b"HTTP/1.1 200 OK\r\nContent-Length: 3000000\r\n\r\n"]
    with pytest.raises(transport.FetchError,match="response_too_large"): transport.PublicHTTP().get(ROOT)
    payloads[:]=[b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 0\r\n\r\n"]
    with pytest.raises(transport.FetchError,match="encoded_response_rejected"): transport.PublicHTTP().get(ROOT)
    payloads[:]=[b"HTTP/1.1 503 Unavailable\r\nContent-Length: 0\r\n\r\n",b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 2\r\n\r\nOK"]
    client=transport.PublicHTTP()
    assert client.get(ROOT).body == b"OK" and client.requests == 2
    payloads[:]=[b"HTTP/1.1 429 Blocked\r\nContent-Length: 0\r\n\r\n"]
    client=transport.PublicHTTP()
    assert client.get(ROOT).status == 429 and client.requests == 1


def test_body_without_content_length_is_bounded_and_total_budget_enforced(monkeypatch):
    class Response:
        status=200
        def close(self): pass
        def getheaders(self): return []
        def read(self,size): return b"x"*size
    class Connection:
        def __init__(self,*_): pass
        def request(self,*_,**__): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(transport,"PinnedConnection",Connection)
    with pytest.raises(transport.FetchError,match="response_too_large"):
        transport.PublicHTTP(max_bytes=100)._request(ROOT,"8.8.8.8")
    with pytest.raises(transport.FetchError,match="site_budget_exceeded"):
        transport.PublicHTTP(max_requests=0)._request(ROOT,"8.8.8.8")
    with pytest.raises(transport.FetchError,match="site_budget_exceeded"):
        transport.DeadlineReader(None,0,1).readinto(bytearray(1))


def test_per_host_connections_are_serial_even_across_lead_workers(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    # Use Event.wait because the analyzer fixture replaces sleep for determinism.
    active,maximum=0,0
    lock=threading.Lock()
    def perform(self,url,address):
        nonlocal active,maximum
        with lock: active+=1; maximum=max(maximum,active)
        threading.Event().wait(.015)
        with lock: active-=1
        return transport.Page(url,200,{},b"")
    monkeypatch.setattr(transport.PublicHTTP,"_perform_request",perform)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: transport.PublicHTTP()._request(ROOT,"8.8.8.8"),range(6)))
    assert maximum == 1


def test_retry_and_following_request_respect_actual_host_crawl_delay(monkeypatch):
    clock,starts=[100.0],[]
    monkeypatch.setattr(transport.time,"monotonic",lambda:clock[0])
    monkeypatch.setattr(transport.time,"sleep",lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    monkeypatch.setattr(transport,"resolve_public",lambda _: ["8.8.8.8"])
    statuses=[503,200,403]
    class Response:
        def __init__(self): self.status=statuses.pop(0)
        def getheaders(self): return [("content-length","0")]
        def read(self,_): return b""
        def close(self): pass
    class Connection:
        def __init__(self,*_): pass
        def request(self,*_,**__): starts.append(clock[0])
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(transport,"PinnedConnection",Connection)
    client=transport.PublicHTTP(); client.host_delays["company.example"]=5
    assert client.get(ROOT).status == 200
    assert client.get(ROOT).status == 403
    assert starts == [100,105,110] and client.requests == 3
