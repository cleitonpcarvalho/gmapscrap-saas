import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import EmailTemplate


DEFAULT_LOGO_URL = "https://automasoluct.com.br/wp-content/uploads/2025/06/Automa_Soluct_Logo_Sem_Fundo.png"
CONTENT_BLOCK_PLACEHOLDER = "\n              {{content_card_block}}\n"
CTA_TABLE_MARKER = """              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:10px 0 32px 0;">"""
CTA_BLOCK = """
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 16px 0;">
                We specialize in automation and integrations for service businesses. If you ever need help connecting tools, automating follow-ups, or reducing manual work, just click below and send me a quick note.
              </p>
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:10px 0 32px 0;">
                    <a href="{{get_in_touch_link}}" style="background-color:{{primary_color}};color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:6px;font-size:15px;font-weight:600;display:inline-block;">Get in touch</a>
                  </td>
                </tr>
              </table>
"""
OLD_CONTENT_CTA_PATTERN = re.compile(
    r'\s*<table width="100%" cellpadding="0" cellspacing="0">\s*'
    r"<tr>\s*"
    r'<td align="center" style="padding:10px 0 32px 0;">\s*'
    r'<a href="\{\{content_link\}\}" style="background-color:\{\{primary_color\}\};color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:6px;font-size:15px;font-weight:600;display:inline-block;">Open the content</a>\s*'
    r"</td>\s*"
    r"</tr>\s*"
    r"</table>",
)


def _base_html(body: str, footer_note: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{{{content_title}}}}</title>
</head>
<body style="margin:0;padding:0;background-color:{{{{background_color}}}};font-family:Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:{{{{background_color}}}};padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <tr>
            <td style="background-color:{{{{primary_color}}}};padding:32px 40px;text-align:center;">
              <img src="{{{{logo_url}}}}" alt="Automa Soluct" height="64" style="display:block;margin:0 auto;" />
              <p style="color:#d7d7d7;font-size:13px;margin:12px 0 0 0;">Automation & Integrations</p>
            </td>
          </tr>
          <tr>
            <td style="padding:40px 40px 24px 40px;">
              {body}
              {{{{content_card_block}}}}
{CTA_BLOCK}
              <hr style="border:none;border-top:1px solid #eeeeee;margin:0 0 28px 0;" />
              <p style="font-size:13px;color:#888888;margin:0 0 12px 0;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Get in touch</p>
              <p style="font-size:15px;color:{{{{text_color}}}};line-height:1.7;margin:0;">
                Cleiton Carvalho<br />
                Automation Specialist · Automa Soluct<br />
                <a href="https://automasoluct.com.br" style="color:{{{{primary_color}}}};text-decoration:none;">automasoluct.com.br</a>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 40px 40px 40px;border-top:1px solid #eeeeee;">
              <p style="margin:0;font-size:12px;color:#999999;line-height:1.6;">{footer_note}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _html_with_content_cta(current_html: str) -> str:
    next_html = current_html.replace("{{content_video_block}}", "{{content_card_block}}")
    next_html = next_html.replace(">Watch the video<", ">Open the content<")

    next_html, replacements = OLD_CONTENT_CTA_PATTERN.subn(CTA_BLOCK, next_html, count=1)
    if "{{get_in_touch_link}}" in next_html:
        return next_html

    if "{{content_card_block}}" not in next_html and CTA_TABLE_MARKER in next_html:
        next_html = next_html.replace(CTA_TABLE_MARKER, f"{CONTENT_BLOCK_PLACEHOLDER}{CTA_TABLE_MARKER}", 1)

    if replacements == 0:
        if "<hr" in next_html:
            next_html = next_html.replace("<hr", f"{CTA_BLOCK}\n              <hr", 1)
        elif "</body>" in next_html:
            next_html = next_html.replace("</body>", f"{CTA_BLOCK}</body>", 1)
        else:
            next_html = f"{next_html}{CTA_BLOCK}"

    return next_html


def seed_default_email_templates(db: Session) -> None:
    templates = [
        {
            "name": "Educational Video - Soft Intro",
            "subject": "A quick automation idea for {{lead_name}}",
            "content_title": "A practical automation idea for service businesses",
            "html": _base_html(
                """
              <p style="font-size:16px;color:{{text_color}};margin:0 0 16px 0;">Hi {{lead_name}},</p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 16px 0;">
                I came across your business while researching companies in the <strong>{{niche}}</strong> space around <strong>{{location}}</strong>.
              </p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 16px 0;">
                I put together a short piece of content that may be useful if you use forms, spreadsheets, CRM tools, scheduling apps, or manual follow-ups in your daily workflow.
              </p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 24px 0;">
                Here is the content: <strong>{{content_title}}</strong>
              </p>
                """,
                "You are receiving this because your business contact is publicly listed. If this is not relevant, reply 'remove' and I will not contact you again.",
            ),
            "text": "Hi {{lead_name}},\n\nI found your business while researching {{niche}} companies in {{location}}. I wanted to share this content with you:\n\n{{content_title}}\n{{content_link}}\n\nBest,\nCleiton Carvalho\nAutoma Soluct",
        },
        {
            "name": "Workflow Tip - Practical Value",
            "subject": "Small workflow tip for {{niche}} companies",
            "content_title": "How to reduce manual follow-ups with automation",
            "html": _base_html(
                """
              <p style="font-size:16px;color:{{text_color}};margin:0 0 16px 0;">Hi {{lead_name}},</p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 16px 0;">
                Many local service companies lose time copying lead details, sending follow-up messages, and updating different tools by hand.
              </p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 16px 0;">
                I wanted to share a practical resource about using automation to keep those steps organized without adding more software complexity.
              </p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 24px 0;">
                The resource is here: <strong>{{content_title}}</strong>
              </p>
                """,
                "If you would rather not receive occasional automation resources from me, reply 'remove' and I will take care of it.",
            ),
            "text": "Hi {{lead_name}},\n\nI wanted to share a practical workflow resource for {{niche}} companies:\n\n{{content_title}}\n{{content_link}}\n\nBest,\nCleiton Carvalho\nAutoma Soluct",
        },
        {
            "name": "Content Share - Local Service Ops",
            "subject": "Useful resource for service operations",
            "content_title": "Simple ways to connect forms, CRM and follow-ups",
            "html": _base_html(
                """
              <p style="font-size:16px;color:{{text_color}};margin:0 0 16px 0;">Hi {{lead_name}},</p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 16px 0;">
                I work with automation and integrations for service businesses, and I often publish practical content around common operational bottlenecks.
              </p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 16px 0;">
                Since your company is listed in <strong>{{location}}</strong>, I thought this could be a useful reference for your team.
              </p>
              <p style="font-size:16px;color:{{text_color}};line-height:1.7;margin:0 0 24px 0;">
                You can check it out here: <strong>{{content_title}}</strong>
              </p>
                """,
                "This is a low-volume content note from Automa Soluct. Reply 'remove' if you prefer not to receive future resources.",
            ),
            "text": "Hi {{lead_name}},\n\nI wanted to share this service operations resource with you:\n\n{{content_title}}\n{{content_link}}\n\nBest,\nCleiton Carvalho\nAutoma Soluct",
        },
    ]

    for data in templates:
        exists = db.scalar(select(EmailTemplate.id).where(EmailTemplate.name == data["name"]))
        if exists:
            continue

        db.add(
            EmailTemplate(
                **data,
                content_link="",
                logo_url=DEFAULT_LOGO_URL,
                primary_color="#0a0a0a",
                text_color="#333333",
                background_color="#f4f4f4",
            )
        )

    existing_templates = db.scalars(select(EmailTemplate)).all()
    for template in existing_templates:
        next_html = _html_with_content_cta(template.html)
        if next_html != template.html:
            template.html = next_html

    db.commit()
