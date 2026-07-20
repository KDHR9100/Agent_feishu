import requests
import time
import json
from app.config import config, logger
from typing import Optional, Dict, Any


class FeishuTool:
    def __init__(self, app_id: str = "", app_secret: str = ""):
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token = None
        self.token_expire_time = 0

    def get_access_token(self) -> str:
        """Get tenant_access_token with caching"""
        if not self.app_id or not self.app_secret:
            logger.error("[FeishuTool] App ID or App Secret not configured")
            return ""

        # Return cached token if still valid
        if self.access_token and time.time() < self.token_expire_time:
            return self.access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 0:
                    self.access_token = data.get("tenant_access_token")
                    self.token_expire_time = time.time() + 7000
                    logger.info("[FeishuTool] Access token obtained successfully")
                    return self.access_token
                else:
                    logger.error("[FeishuTool] Failed to get token: %s" % data.get("msg", "Unknown error"))
            else:
                logger.error("[FeishuTool] HTTP error: %d" % response.status_code)
        except Exception as e:
            logger.error("[FeishuTool] Failed to get access token: %s" % str(e))

        return ""

    def _build_content(self, content: str, msg_type: str = "text") -> str:
        """Build message content JSON safely"""
        if msg_type == "text":
            return json.dumps({"text": content}, ensure_ascii=False)
        return content

    def send_message(self, chat_id: str, content: str, msg_type: str = "text") -> Dict[str, Any]:
        """Send message to a chat"""
        token = self.get_access_token()
        if not token:
            return {"error": "Failed to get access token"}

        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json"
        }

        content_json = self._build_content(content, msg_type)
        payload = {
            "receive_id": chat_id,
            "msg_type": msg_type,
            "content": content_json
        }
        params = {"receive_id_type": "chat_id"}

        try:
            response = requests.post(url, headers=headers, json=payload, params=params, timeout=10)
            return response.json()
        except Exception as e:
            logger.error("[FeishuTool] Failed to send message: %s" % str(e))
            return {"error": str(e)}

    def reply_message(self, message_id: str, content: str, msg_type: str = "text") -> Dict[str, Any]:
        """Reply to a specific message"""
        token = self.get_access_token()
        if not token:
            return {"error": "Failed to get access token"}

        url = "https://open.feishu.cn/open-apis/im/v1/messages/%s/reply" % message_id
        headers = {
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json"
        }

        content_json = self._build_content(content, msg_type)
        payload = {
            "msg_type": msg_type,
            "content": content_json
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            return response.json()
        except Exception as e:
            logger.error("[FeishuTool] Failed to reply message: %s" % str(e))
            return {"error": str(e)}

    def create_document(self, folder_token: str, title: str, content: str) -> Dict[str, Any]:
        """Create a document in Feishu Docs"""
        token = self.get_access_token()
        if not token:
            return {"error": "Failed to get access token"}

        url = "https://open.feishu.cn/open-apis/docx/v1/documents"
        headers = {
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json"
        }
        payload = {
            "folder_token": folder_token,
            "title": title,
            "content": content
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            return response.json()
        except Exception as e:
            logger.error("[FeishuTool] Failed to create document: %s" % str(e))
            return {"error": str(e)}

    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get user information"""
        token = self.get_access_token()
        if not token:
            return {"error": "Failed to get access token"}

        url = "https://open.feishu.cn/open-apis/contact/v3/users/%s" % user_id
        headers = {"Authorization": "Bearer %s" % token}

        try:
            response = requests.get(url, headers=headers, timeout=10)
            return response.json()
        except Exception as e:
            logger.error("[FeishuTool] Failed to get user info: %s" % str(e))
            return {"error": str(e)}


feishu_tool = FeishuTool(
    app_id=config.FEISHU_APP_ID,
    app_secret=config.FEISHU_APP_SECRET
)
