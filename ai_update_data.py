import json
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from google import genai
from google.genai import types

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# RSS Feed Endpoints
RSS_FEEDS = {
    "Radiology Business": "https://radiologybusiness.com/rss.xml",
    "AuntMinnie": "https://www.auntminnie.com/rss/rss.aspx",
    "FDA News": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
}


def fetch_rss_headlines():
    items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HealthcareDashboard/1.0"
    }

    for source_name, url in RSS_FEEDS.items():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                xml_data = response.read().decode("utf-8", errors="ignore")

            raw_items = re.findall(r"<item>(.*?)</item>", xml_data, re.DOTALL)

            for raw_item in raw_items[:3]:
                title_match = re.search(
                    r"<title>(.*?)</title>", raw_item, re.DOTALL
                )
                link_match = re.search(
                    r"<link>(.*?)</link>", raw_item, re.DOTALL
                )
                date_match = re.search(
                    r"<pubDate>(.*?)</pubDate>", raw_item, re.DOTALL
                )

                if title_match and link_match:
                    title = (
                        title_match.group(1)
                        .replace("<![CDATA[", "")
                        .replace("]]>", "")
                        .strip()
                    )
                    link = (
                        link_match.group(1)
                        .replace("<![CDATA[", "")
                        .replace("]]>", "")
                        .strip()
                    )
                    pub_date = (
                        date_match.group(1).strip() if date_match else "Recent"
                    )

                    tag = "Industry"
                    title_lower = title.lower()
                    if "fda" in title_lower or "clearance" in title_lower:
                        tag = "Regulatory"
                    elif "ai" in title_lower or "algorithm" in title_lower:
                        tag = "AI Innovation"
                    elif (
                        "reimbursement" in title_lower
                        or "cpt" in title_lower
                        or "market" in title_lower
                    ):
                        tag = "Macro / Market"

                    items.append
