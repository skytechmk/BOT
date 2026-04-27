import sys
import re

with open("/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py", "r") as f:
    content = f.read()

# 1) Add the new endpoint /signals/{pair} right before `robots_txt`
signals_code = """
@app.get("/signals/{pair}", response_class=HTMLResponse)
async def seo_pair_page(pair: str):
    \"\"\"Programmatic SEO page for each crypto pair.\"\"\"
    pair = pair.upper()
    if not pair.endswith("USDT"):
        pair += "USDT"
    
    html_path = Path(__file__).parent / "signal_seo.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Pair page not found</h1>", status_code=404)
        
    template = html_path.read_text()
    html = template.replace("{pair}", pair)
    return HTMLResponse(content=html, status_code=200)

"""

# 2) Replace the sitemap_xml function
sitemap_code = """@app.get("/sitemap.xml")
async def sitemap_xml():
    \"\"\"Dynamic sitemap including programmatic SEO pair pages.\"\"\"
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    
    # Core static pages
    base_url = "https://anunnakiworld.com"
    static_routes = ["/", "/whitepaper", "/whitepaper/mk", "/app", "/landing"]
    
    for route in static_routes:
        xml.append('  <url>')
        xml.append(f'    <loc>{base_url}{route}</loc>')
        xml.append('    <changefreq>daily</changefreq>')
        xml.append('  </url>')
        
    # Programmatic Pair Pages (pull from DB)
    try:
        if _SIGNAL_DB_PATH.exists():
            import sqlite3
            conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT pair FROM signals")
            pairs = [row[0] for row in cur.fetchall()]
            conn.close()
            
            for pair in pairs:
                xml.append('  <url>')
                xml.append(f'    <loc>{base_url}/signals/{pair}</loc>')
                xml.append('    <changefreq>weekly</changefreq>')
                xml.append('  </url>')
    except Exception as e:
        print(f"Error building pair sitemap: {e}")
        
    xml.append('</urlset>')
    return Response(content='\\n'.join(xml), media_type="application/xml")
"""

# Replace the existing sitemap function
content = re.sub(
    r'@app\.get\("/sitemap\.xml"\).*?return Response\(content=xml, media_type="application/xml"\)',
    sitemap_code,
    content,
    flags=re.DOTALL | re.MULTILINE
)

# Insert the pair route before /robots.txt
content = content.replace('@app.get("/robots.txt", response_class=PlainTextResponse)', signals_code + '@app.get("/robots.txt", response_class=PlainTextResponse)')

with open("/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py", "w") as f:
    f.write(content)

print("Patched app.py")
