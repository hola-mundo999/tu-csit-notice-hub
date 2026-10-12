import requests
from typing import Dict, Optional


class TelegramNotifier:
    """
    Formats and dispatches high-priority TU CSIT notice alerts to Telegram channels.
    """

    @staticmethod
    def format_message(notice: Dict) -> str:
        urgent_badge = "🚨 **[URGENT TU NOTICE]**" if notice.get("is_urgent") else "📢 **[NEW TU NOTICE]**"
        return f"""
{urgent_badge}

📌 **Title:** {notice['title']}
🏷️ **Category:** `{notice['category']}`
🎓 **Semester:** `{notice['semester']}`
📅 **Date:** {notice['publish_date']}

🔗 **Official Link:** [Click to View on TU IOST]({notice['url']})

---
*TU CSIT Alert Bot · Dispatched via Samyog's Notice Hub*
""".strip()

    @classmethod
    def send_telegram_alert(cls, notice: Dict, bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> Dict:
        """
        Sends message to a live Telegram bot/channel, or returns simulation if tokens not provided.
        """
        formatted_text = cls.format_message(notice)

        if bot_token and chat_id:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": formatted_text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False
                }
                res = requests.post(url, json=payload, timeout=5)
                return {
                    "success": res.status_code == 200,
                    "message": "Sent live to Telegram channel!",
                    "formatted": formatted_text
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Telegram API error: {str(e)}",
                    "formatted": formatted_text
                }

        # Simulated dispatch for local testing
        return {
            "success": True,
            "simulated": True,
            "message": "Simulated Telegram dispatch successful!",
            "formatted": formatted_text
        }
