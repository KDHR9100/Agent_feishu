import requests
from typing import Optional, Dict, Any


class FeishuTool:
    def __init__(self, app_id: str = "", app_secret: str = ""):
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token = None
    
    def get_access_token(self) -> str:
        if not self.access_token:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            payload = {
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                self.access_token = response.json().get("tenant_access_token")
        return self.access_token
    
    def send_message(self, chat_id: str, content: str) -> Dict[str, Any]:
        token = self.get_access_token()
        if not token:
            return {"error": "Failed to get access token"}
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": f'{{"text":"{content}"}}'
        }
        response = requests.post(url, headers=headers, json=payload)
        return response.json()
    
    def create_document(self, folder_token: str, title: str, content: str) -> Dict[str, Any]:
        token = self.get_access_token()
        if not token:
            return {"error": "Failed to get access token"}
        
        url = "https://open.feishu.cn/open-apis/docx/v1/documents"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "folder_token": folder_token,
            "title": title,
            "content": content
        }
        response = requests.post(url, headers=headers, json=payload)
        return response.json()
    
    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        token = self.get_access_token()
        if not token:
            return {"error": "Failed to get access token"}
        
        url = f"https://open.feishu.cn/open-apis/contact/v3/users/{user_id}"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(url, headers=headers)
        return response.json()
    
    def search_messages(self, keyword: str, count: int = 10) -> Dict[str, Any]:
        token = self.get_access_token()
        if not token:
            return {"error": "Failed to get access token"}
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages/search"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"keyword": keyword, "count": count}
        response = requests.get(url, headers=headers, params=params)
        return response.json()


feishu_tool = FeishuTool()
