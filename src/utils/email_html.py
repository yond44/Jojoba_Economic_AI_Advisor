from datetime import datetime
from typing import Optional


def generate_economic_news_email(
    question: str,
    answer: str,
    processing_time: float = 0,
    iterations: int = 0,
    queue_remaining: int = 0,
    next_question: Optional[str] = None,
    email_count: int = 0
) -> str:
    """
    Generate HTML email template for Jojoba Economic News
    
    Args:
        question: The economic question asked
        answer: The AI-generated answer/analysis
        processing_time: Time taken to process (seconds)
        iterations: Number of iterations used
        queue_remaining: Questions left in queue
        next_question: The next question in queue
        email_count: Number of recipients this email is sent to
    
    Returns:
        HTML string for email body
    """
    
    # Format next question display
    if next_question:
        if len(next_question) > 30:
            next_display = next_question[:30] + '...'
        else:
            next_display = next_question
    else:
        next_display = 'None'
    
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jojoba Economic News - {question}</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #f5f7fa; margin: 0; padding: 0; color: #1a2332; }}
    .container {{ max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; }}
    .header {{ background: #0f1a2e; padding: 20px 25px; }}
    .header h1 {{ margin: 0; color: #ffffff; font-weight: 400; font-size: 20px; }}
    .header h1 span {{ font-weight: 700; color: #e8b82a; }}
    .header .date {{ color: #8899aa; font-size: 12px; margin-top: 2px; }}
    .content {{ padding: 20px 25px; }}
    .question-box {{ background: #f0f4fe; border-radius: 6px; padding: 12px 16px; margin-bottom: 18px; border-left: 3px solid #1a5c9e; }}
    .question-box .label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: #1a5c9e; font-weight: 700; }}
    .question-box .text {{ font-size: 15px; font-weight: 500; color: #0f1a2e; margin: 4px 0 0 0; }}
    .answer-box .label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: #6b7a8a; font-weight: 700; display: block; margin-bottom: 5px; }}
    .answer-box .content {{ 
        background: #fafbfc; 
        border-radius: 6px; 
        padding: 14px 16px; 
        border: 1px solid #eaeef2; 
        font-size: 14px; 
        line-height: 1.6; 
        color: #1e2a3a; 
        margin: 0 0 18px 0; 
        white-space: pre-wrap; 
        word-wrap: break-word; 
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
    }}
    .answer-box .content table {{
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0;
        font-size: 13px;
    }}
    .answer-box .content table th,
    .answer-box .content table td {{
        border: 1px solid #d0d7de;
        padding: 8px 12px;
        text-align: left;
    }}
    .answer-box .content table th {{
        background: #f0f4fe;
        font-weight: 600;
        color: #0f1a2e;
    }}
    .answer-box .content table tr:nth-child(even) {{
        background: #f8f9fb;
    }}
    .answer-box .content table tr:hover {{
        background: #e8ecf1;
    }}
    .answer-box .content ul, 
    .answer-box .content ol {{
        margin: 8px 0;
        padding-left: 20px;
    }}
    .answer-box .content li {{
        margin: 4px 0;
    }}
    .answer-box .content h3 {{
        margin: 12px 0 8px 0;
        color: #0f1a2e;
        font-size: 15px;
    }}
    .answer-box .content strong {{
        color: #0f1a2e;
    }}
    .status-box {{ background: #f8f9fb; border-radius: 6px; padding: 12px 16px; border: 1px solid #eaeef2; }}
    .status-box .stat {{ display: inline-block; margin-right: 20px; }}
    .status-box .stat .value {{ font-weight: 600; color: #1a5c9e; }}
    .footer {{ background: #f8f9fb; padding: 14px 25px; border-top: 1px solid #eaeef2; font-size: 11px; color: #7a8a9a; }}
    .footer .disclaimer {{ color: #c0392b; font-weight: 600; }}
    
    @media only screen and (max-width: 480px) {{
        .header {{ padding: 16px 18px; }}
        .header h1 {{ font-size: 18px; }}
        .content {{ padding: 16px 18px; }}
        .answer-box .content {{ padding: 12px 14px; font-size: 13px; }}
        .status-box .stat {{ display: block; margin-bottom: 4px; }}
        .footer {{ padding: 12px 18px; }}
    }}
</style>
</head>
<body>
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f5f7fa">
    <tr><td align="center" style="padding: 20px 0;">
        <div class="container">
            <div class="header">
                <h1>📊 Jojoba <span>Economic News</span></h1>
                <div class="date">{datetime.now().strftime('%d %b %Y')} &bull; {datetime.now().strftime('%H:%M')}</div>
            </div>
            <div class="content">
                <div class="question-box">
                    <div class="label">📋 Today's Question</div>
                    <div class="text">{question}</div>
                </div>
                <div class="answer-box">
                    <span class="label">💡 Analysis</span>
                    <div class="content">{answer}</div>
                </div>
                <div class="status-box">
                    <div class="stat">⏱ <span class="value">{processing_time}s</span></div>
                    <div class="stat">🔄 <span class="value">{iterations}</span> iterations</div>
                    <div class="stat">📊 <span class="value">{queue_remaining}</span> remaining</div>
                    <div class="stat">⏭️ Next: <span class="value">{next_display}</span></div>
                </div>
            </div>
            <div class="footer">
                <span class="disclaimer">⚠️ Not financial advice</span> &bull; For educational purposes only
                <br>Generated by Jojoba Economic Advisor AI
                <br><span style="color:#7a8a9a;font-size:10px;">Sent to {email_count} recipients</span>
            </div>
        </div>
    </td></tr>
</table>
</body>
</html>
    """
    
    return html_body


def generate_simple_email(
    question: str,
    answer: str,
    recipient_count: int = 0
) -> str:
    """
    Generate a simpler email template (fallback)
    
    Args:
        question: The economic question asked
        answer: The AI-generated answer/analysis
        recipient_count: Number of recipients
    
    Returns:
        HTML string for email body
    """
    
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jojoba Economic News</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #f5f7fa; margin: 0; padding: 20px; color: #1a2332; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; padding: 25px; }}
    .header {{ border-bottom: 2px solid #e8b82a; padding-bottom: 15px; margin-bottom: 20px; }}
    .header h1 {{ margin: 0; color: #0f1a2e; font-size: 22px; }}
    .header h1 span {{ color: #e8b82a; }}
    .header .date {{ color: #8899aa; font-size: 12px; }}
    .question {{ background: #f0f4fe; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px; border-left: 3px solid #1a5c9e; }}
    .question .label {{ font-size: 10px; text-transform: uppercase; color: #1a5c9e; font-weight: 700; }}
    .question .text {{ font-size: 15px; font-weight: 500; margin: 4px 0 0 0; }}
    .answer {{ background: #fafbfc; padding: 14px 16px; border-radius: 6px; border: 1px solid #eaeef2; line-height: 1.6; }}
    .footer {{ margin-top: 20px; padding-top: 15px; border-top: 1px solid #eaeef2; font-size: 11px; color: #7a8a9a; }}
    .footer .disclaimer {{ color: #c0392b; font-weight: 600; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 Jojoba <span>Economic News</span></h1>
        <div class="date">{datetime.now().strftime('%d %b %Y')} &bull; {datetime.now().strftime('%H:%M')}</div>
    </div>
    
    <div class="question">
        <div class="label">📋 Question</div>
        <div class="text">{question}</div>
    </div>
    
    <div class="answer">
        <strong>💡 Analysis</strong>
        <div style="margin-top: 8px;">{answer}</div>
    </div>
    
    <div class="footer">
        <span class="disclaimer">⚠️ Not financial advice</span> &bull; For educational purposes only
        <br>Generated by Jojoba Economic Advisor AI
        {f'<br>Sent to {recipient_count} recipients' if recipient_count > 0 else ''}
    </div>
</div>
</body>
</html>
    """
    
    return html_body