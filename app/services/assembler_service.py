"""Converts structured newsletter JSON into Markdown or HTML for distribution."""
import os
from typing import Dict, Any
from jinja2 import Environment, FileSystemLoader
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("assembler_service")

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=True,
)


class NewsletterAssembler:

    def to_markdown(self, newsletter: Dict[str, Any]) -> str:
        try:
            md = []

            md.append(f"# {newsletter.get('issue_title', settings.NEWSLETTER_TITLE)}")

            issue_num = newsletter.get('issue_number')
            date_str = newsletter.get('date_iso', '')[:10] if newsletter.get('date_iso') else ''
            md.append(f"**Issue #{issue_num if issue_num else 'N'}** | {date_str}")
            md.append("")

            subheadline = newsletter.get('subheadline', '')
            if subheadline:
                md.append(f"_{subheadline}_")
                md.append("")

            intro = newsletter.get('intro', '')
            if intro:
                md.append(intro)
                md.append("")

            md.append("---")
            md.append("")

            headline = newsletter.get('headline')
            if headline:
                emoji = headline.get('emoji', '🏆')
                md.append(f"## {emoji} HEADLINE")
                md.append("")
                md.append(f"**{headline.get('title', 'Untitled')}**")
                md.append("")
                md.append(headline.get('summary', ''))
                md.append("")
                source_label = headline.get('source_label', 'Source')
                source_url = headline.get('source_url', '')
                if source_url:
                    md.append(f"👉 [{source_label}]({source_url})")
                md.append("")
                md.append("---")
                md.append("")

            for section_key, section_title, section_emoji in [
                ('latest_news', 'LATEST NEWS', '📰'),
                ('company_updates', 'COMPANY UPDATES', '🏢'),
                ('tools_and_products', 'TOOLS & RELEASES', '⚙️'),
                ('open_source_spotlight', 'OPEN SOURCE SPOTLIGHT', '🐙'),
            ]:
                items = newsletter.get(section_key, [])
                if items:
                    md.append(f"## {section_emoji} {section_title}")
                    md.append("")
                    for item in items:
                        title = item.get('title', 'Untitled')
                        summary = item.get('summary', '')
                        source_label = item.get('source_label', 'Source')
                        source_url = item.get('source_url', '')
                        md.append(f"• **{title}** — {summary}")
                        if source_url:
                            md.append(f"  [{source_label}]({source_url})")
                        md.append("")
                    md.append("---")
                    md.append("")

            research = newsletter.get('research_spotlight')
            if research:
                emoji = research.get('emoji', '🔬')
                md.append(f"## {emoji} RESEARCH SPOTLIGHT")
                md.append("")
                md.append(f"**{research.get('title', 'Untitled')}**")
                md.append("")
                md.append(research.get('summary', ''))
                md.append("")
                source_url = research.get('source_url', '')
                if source_url:
                    md.append(f"👉 [{research.get('source_label', 'Source')}]({source_url})")
                md.append("")
                md.append("---")
                md.append("")

            quick_bytes = newsletter.get('quick_bytes', [])
            if quick_bytes:
                md.append("## ⚡ QUICK BYTES")
                md.append("")
                for byte_item in quick_bytes:
                    display = byte_item.get('summary', '') or byte_item.get('title', '')
                    md.append(f"• {display}")
                    source_url = byte_item.get('source_url', '')
                    if source_url:
                        md.append(f"  [{byte_item.get('source_label', 'Source')}]({source_url})")
                    md.append("")
                md.append("---")
                md.append("")

            wrap = newsletter.get('wrap', '')
            if wrap:
                md.append(wrap)
                md.append("")

            md.append("---")
            md.append("")

            footer = newsletter.get('footer', f'© {settings.NEWSLETTER_COPYRIGHT} | Curated with intelligence, crafted with care')
            md.append(footer)
            md.append("")

            read_time = newsletter.get('estimated_read_time', '4-6 minutes')
            md.append(f"_{read_time} read_")

            result = "\n".join(md)
            logger.info(f"Generated Markdown newsletter ({len(result)} chars)")
            return result

        except Exception as e:
            logger.error(f"Markdown generation failed: {e}")
            return self._fallback_markdown(newsletter)

    def to_html(self, newsletter: Dict[str, Any]) -> str:
        try:
            template = _jinja_env.get_template("newsletter_email.html")

            ctx = {
                "issue_title": newsletter.get("issue_title", settings.NEWSLETTER_TITLE),
                "issue_number": newsletter.get("issue_number"),
                "date_iso": newsletter.get("date_iso", ""),
                "subheadline": newsletter.get("subheadline", ""),
                "intro": newsletter.get("intro", ""),
                "headline": newsletter.get("headline"),
                "latest_news": newsletter.get("latest_news", []),
                "company_updates": newsletter.get("company_updates", []),
                "research_spotlight": newsletter.get("research_spotlight"),
                "tools_and_products": newsletter.get("tools_and_products", []),
                "open_source_spotlight": newsletter.get("open_source_spotlight", []),
                "quick_bytes": newsletter.get("quick_bytes", []),
                "wrap": newsletter.get("wrap", ""),
                "footer": newsletter.get(
                    "footer",
                    f"© {settings.NEWSLETTER_COPYRIGHT} | Curated with intelligence, crafted with care",
                ),
                "estimated_read_time": newsletter.get("estimated_read_time", "4-6 minutes"),
            }

            result = template.render(**ctx)
            logger.info(f"Generated HTML newsletter ({len(result)} chars)")
            return result

        except Exception as e:
            logger.error(f"HTML generation failed: {e}")
            return self._fallback_html(newsletter)

    def _fallback_markdown(self, newsletter: Dict[str, Any]) -> str:
        return f"""# {newsletter.get('issue_title', settings.NEWSLETTER_TITLE)}

{newsletter.get('intro', 'Newsletter content unavailable.')}

---

{newsletter.get('footer', f'© {settings.NEWSLETTER_COPYRIGHT}')}
"""

    def _fallback_html(self, newsletter: Dict[str, Any]) -> str:
        title = newsletter.get("issue_title", settings.NEWSLETTER_TITLE)
        intro = newsletter.get("intro", "Newsletter content unavailable.")
        footer = newsletter.get("footer", f"© {settings.NEWSLETTER_COPYRIGHT}")
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body style="margin:0; padding:0; background-color:#f4f4f7; font-family:Arial, sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f4f7;">
<tr><td align="center" style="padding:24px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0">
<tr><td bgcolor="#1a1a2e" style="padding:24px 32px; text-align:center;">
<span style="font-size:24px; font-weight:700; color:#ffffff;">{title}</span>
</td></tr>
<tr><td bgcolor="#ffffff" style="padding:32px;">
<p style="font-size:15px; line-height:1.6; color:#374151;">{intro}</p>
</td></tr>
<tr><td bgcolor="#1a1a2e" style="padding:16px 32px; text-align:center;">
<span style="font-size:12px; color:#a0aec0;">{footer}</span>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
