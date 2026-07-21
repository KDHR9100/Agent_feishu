import unittest
import logging
import json
from unittest.mock import MagicMock, patch


class TestRouterIntentRecognition(unittest.TestCase):
    def setUp(self):
        logging.basicConfig(level=logging.INFO)

    @patch('app.agent.router.llm_with_tools')
    def test_intent_recognition_product_skill(self, mock_llm):
        mock_response = MagicMock()
        mock_response.tool_calls = [{"name": "product_skill", "args": {"user_input": "analyze product A"}}]
        mock_response.response_metadata = {}
        mock_llm.invoke.return_value = mock_response

        from app.agent.router import router

        state = {"user_input": "analyze product A sales data"}
        result = router(state)

        self.assertEqual(result["intent"], "product_skill")
        self.assertEqual(result["tool_result"]["skill"], "product_skill")
        mock_llm.invoke.assert_called_once()

    @patch('app.agent.router.llm_with_tools')
    def test_intent_recognition_ads_skill(self, mock_llm):
        mock_response = MagicMock()
        mock_response.tool_calls = [{"name": "ads_skill", "args": {"user_input": "analyze ads"}}]
        mock_response.response_metadata = {}
        mock_llm.invoke.return_value = mock_response

        from app.agent.router import router

        state = {"user_input": "analyze recent ad performance"}
        result = router(state)

        self.assertEqual(result["intent"], "ads_skill")
        self.assertEqual(result["tool_result"]["skill"], "ads_skill")

    @patch('app.agent.router.llm_with_tools')
    def test_intent_recognition_content_skill(self, mock_llm):
        mock_response = MagicMock()
        mock_response.tool_calls = [{"name": "content_skill", "args": {"user_input": "generate copy"}}]
        mock_response.response_metadata = {}
        mock_llm.invoke.return_value = mock_response

        from app.agent.router import router

        state = {"user_input": "write product promotion copy"}
        result = router(state)

        self.assertEqual(result["intent"], "content_skill")
        self.assertEqual(result["tool_result"]["skill"], "content_skill")

    @patch('app.agent.router.llm_with_tools')
    def test_intent_recognition_unknown(self, mock_llm):
        mock_response = MagicMock()
        mock_response.tool_calls = None
        mock_response.response_metadata = {}
        mock_llm.invoke.return_value = mock_response

        from app.agent.router import router

        state = {"user_input": "hello"}
        result = router(state)

        self.assertEqual(result["intent"], "unknown")
        self.assertEqual(result["tool_result"]["skill"], "unknown")

    @patch('app.agent.router.llm_with_tools')
    def test_router_token_usage_logging(self, mock_llm):
        mock_response = MagicMock()
        mock_response.tool_calls = [{"name": "product_skill", "args": {"user_input": "analyze"}}]
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        }
        mock_llm.invoke.return_value = mock_response

        from app.agent.router import router

        state = {"user_input": "analyze product"}
        result = router(state)

        self.assertEqual(result["intent"], "product_skill")


class TestWorkflowTokenTracking(unittest.TestCase):
    @patch('app.agent.workflow.get_llm')
    def test_token_usage_capture(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "test response"
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80}
        }
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        from app.agent.workflow import skill_executor

        state = {
            "tool_result": {"skill": "unknown", "user_input": "hello"},
            "user_input": "hello"
        }
        result = skill_executor(state)

        self.assertEqual(result["token_usage"]["prompt_tokens"], 50)
        self.assertEqual(result["token_usage"]["completion_tokens"], 30)
        self.assertEqual(result["token_usage"]["total_tokens"], 80)

    @patch('app.agent.workflow.get_llm')
    def test_token_usage_default_when_error(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("LLM error")
        mock_get_llm.return_value = mock_llm

        from app.agent.workflow import skill_executor

        state = {
            "tool_result": {"skill": "unknown", "user_input": "test"},
            "user_input": "test"
        }
        result = skill_executor(state)

        self.assertEqual(result["token_usage"]["prompt_tokens"], 0)
        self.assertEqual(result["token_usage"]["completion_tokens"], 0)
        self.assertEqual(result["token_usage"]["total_tokens"], 0)


class TestFeishuToolUserInfo(unittest.TestCase):
    @patch('app.tools.feishu_tool.requests.get')
    @patch('app.tools.feishu_tool.FeishuTool.get_access_token')
    def test_get_user_info_success(self, mock_get_token, mock_get):
        mock_get_token.return_value = "test_token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": {"name": "Zhang San", "open_id": "ou_123"}
        }
        mock_get.return_value = mock_response

        from app.tools.feishu_tool import FeishuTool

        tool = FeishuTool(app_id="test", app_secret="test")
        result = tool.get_user_info("ou_123")

        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["name"], "Zhang San")

    @patch('app.tools.feishu_tool.requests.get')
    @patch('app.tools.feishu_tool.FeishuTool.get_access_token')
    def test_get_user_info_failure(self, mock_get_token, mock_get):
        mock_get_token.return_value = "test_token"
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"code": 1, "msg": "User not found"}
        mock_get.return_value = mock_response

        from app.tools.feishu_tool import FeishuTool

        tool = FeishuTool(app_id="test", app_secret="test")
        result = tool.get_user_info("ou_unknown")

        self.assertEqual(result["code"], 1)


class TestFeishuWsMessageParsing(unittest.TestCase):
    def test_message_parsing_with_mention(self):
        import lark_oapi as lark
        from app.tools.feishu_ws import do_p2_im_message_receive_v1

        class MockEventData:
            def __init__(self, data):
                self.data = data

        event_dict = {
            "event": {
                "message": {
                    "message_id": "msg_123",
                    "chat_id": "chat_456",
                    "content": json.dumps({"text": "@bot hello"}),
                    "mentions": [{"key": "@bot"}]
                },
                "sender": {"sender_id": {"open_id": "ou_789"}}
            }
        }

        do_p2_im_message_receive_v1(event_dict)

        self.assertTrue(True)

    def test_message_parsing_without_mention(self):
        from app.tools.feishu_ws import do_p2_im_message_receive_v1

        event_dict = {
            "event": {
                "message": {
                    "message_id": "msg_123",
                    "chat_id": "chat_456",
                    "content": json.dumps({"text": "hello"}),
                    "mentions": []
                },
                "sender": {"sender_id": {"open_id": "ou_789"}}
            }
        }

        do_p2_im_message_receive_v1(event_dict)

        self.assertTrue(True)


if __name__ == '__main__':
    unittest.main()