import feedparser
import asyncio
import time
import re
from datetime import datetime
from utils_logger import log_message

# RSS feeds (free, no key required)
FEEDS = {
    'CryptoNews': 'https://cryptoslate.com/feed/',
    'Cointelegraph': 'https://cointelegraph.com/rss',
    'BitcoinMagazine': 'https://bitcoinmagazine.com/feed',
}

KEYWORDS = ['trump', 'crypto', 'bitcoin', 'ethereum', 'regulation', 'sec', 'fed', 'interest rate',
            'tariff', 'sanctions', 'ban', 'crash', 'hack', 'exploit']


def _sanitize_markdown(text: str) -> str:
    """Escape Telegram MarkdownV1 special characters in dynamic text."""
    # Telegram Markdown special chars: _ * [ ] ( ) ~ ` > # + - = | { } . !
    # We only escape the ones that cause parse failures in MarkdownV1: _ * ` [
    for ch in ('_', '*', '`', '[', ']'):
        text = text.replace(ch, f'\\{ch}')
    return text


class NewsMonitor:
    def __init__(self, send_message_fn=None):
        self.send_message_fn = send_message_fn
        self.seen_links = set()
        self.running = False
        self._first_run = True  # Suppress all items on first poll

    def contains_keywords(self, entry):
        text = (entry.get('title', '') + entry.get('summary', '')).lower()
        return any(k in text for k in KEYWORDS)

    async def poll_feeds(self):
        new_entries = []
        for source, url in FEEDS.items():
            try:
                feed = await asyncio.to_thread(feedparser.parse, url)
                for entry in feed.entries[:10]:
                    link = entry.get('link')
                    if link and link not in self.seen_links:
                        self.seen_links.add(link)
                        # On first run, only populate seen_links — don't alert
                        if not self._first_run and self.contains_keywords(entry):
                            new_entries.append({
                                'source': source,
                                'title': entry.get('title', 'No Title'),
                                'link': link,
                                'published': entry.get('published', ''),
                            })
            except Exception as e:
                log_message(f"Error fetching news from {source}: {e}")
        
        if self._first_run:
            log_message(f"News Monitor: seeded {len(self.seen_links)} seen links on first poll")
            self._first_run = False
        
        return new_entries

    async def run(self):
        log_message("=== News Monitor Started (Async) ===")
        self.running = True
        while self.running:
            try:
                new_items = await self.poll_feeds()
                for item in new_items:
                    safe_title = _sanitize_markdown(item['title'])
                    safe_source = _sanitize_markdown(item['source'])
                    msg = (f"🚨 *NEWS ALERT: {safe_source}*\n\n"
                           f"📰 {safe_title}\n"
                           f"🕒 {item['published']}\n"
                           f"🔗 {item['link']}")
                    
                    log_message(f"🚨 NEW: {item['source']} — {item['title']}")
                    
                    if self.send_message_fn:
                        try:
                            await self.send_message_fn(msg)
                        except Exception as e:
                            log_message(f"News alert send failed: {e}")
                    
                    # Rate-limit: 1 message per 3 seconds to avoid flood control
                    await asyncio.sleep(3)
                
            except Exception as e:
                log_message(f"News monitor loop error: {e}")
            
            await asyncio.sleep(300)  # Check every 5 minutes

if __name__ == '__main__':
    async def test():
        monitor = NewsMonitor(print)
        await monitor.run()
    asyncio.run(test())
