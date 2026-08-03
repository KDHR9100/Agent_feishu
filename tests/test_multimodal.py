"""任务2: 原生多模态接入 - 图片/海报解析 单元测试"""
import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.file_parser_tool import FileParserTool, IMAGE_EXTENSIONS


class TestImageExtensions:

    def test_supported_extensions(self):
        assert '.jpg' in IMAGE_EXTENSIONS
        assert '.jpeg' in IMAGE_EXTENSIONS
        assert '.png' in IMAGE_EXTENSIONS
        assert '.webp' in IMAGE_EXTENSIONS

    def test_unsupported_not_in_set(self):
        assert '.gif' not in IMAGE_EXTENSIONS
        assert '.bmp' not in IMAGE_EXTENSIONS


class TestParseImageRouting:

    def setup_method(self):
        self.parser = FileParserTool()

    def test_image_extension_routes_to_parse_image(self):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
            tmp_path = f.name
        try:
            with patch.object(self.parser, 'parse_image', return_value={'image_analysis': 'test'}) as mock:
                result = self.parser.parse_local_file(tmp_path)
                mock.assert_called_once_with(tmp_path)
                assert result == {'image_analysis': 'test'}
        finally:
            os.unlink(tmp_path)

    def test_file_not_found(self):
        result = self.parser.parse_local_file('/nonexistent/image.png')
        assert 'error' in result

    def test_unsupported_extension(self):
        with tempfile.NamedTemporaryFile(suffix='.xyz', delete=False) as f:
            f.write(b'data')
            tmp_path = f.name
        try:
            result = self.parser.parse_local_file(tmp_path)
            assert 'error' in result
            assert 'Unsupported' in result['error']
        finally:
            os.unlink(tmp_path)


class TestParseImageVLM:

    def setup_method(self):
        self.parser = FileParserTool()

    def test_no_api_key_returns_error(self):
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            f.write(b'\xff\xd8\xff\xe0' + b'\x00' * 50)
            tmp_path = f.name
        try:
            with patch("app.config.config") as mock_cfg:
                mock_cfg.VLM_API_KEY = ""
                result = self.parser.parse_image(tmp_path)
                assert 'error' in result
                assert 'VLM_API_KEY' in result['error']
        finally:
            os.unlink(tmp_path)

    def test_successful_image_parse(self):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
            tmp_path = f.name
        try:
            mock_choice = MagicMock()
            mock_choice.message.content = "| 商品 | 价格 |\n|---|---|\n| A | 99 |"
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[mock_choice]
            )

            with patch("app.config.config") as mock_cfg, \
                 patch("openai.OpenAI", return_value=mock_client) as mock_openai_cls:
                mock_cfg.VLM_API_KEY = "test-key"
                mock_cfg.VLM_API_BASE = "https://test.api/v1"
                mock_cfg.VLM_MODEL_NAME = "qwen-vl-max"

                result = self.parser.parse_image(tmp_path)
                assert 'error' not in result
                assert "商品" in result['image_analysis']
                assert result['summary']['image_content']['type'] == 'image_analysis'
                assert result['summary']['image_content']['model'] == 'qwen-vl-max'
                mock_openai_cls.assert_called_once_with(
                    api_key="test-key", base_url="https://test.api/v1"
                )
        finally:
            os.unlink(tmp_path)

    def test_vlm_api_error_graceful(self):
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            f.write(b'\xff\xd8\xff\xe0' + b'\x00' * 50)
            tmp_path = f.name
        try:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = RuntimeError("API timeout")

            with patch("app.config.config") as mock_cfg, \
                 patch("openai.OpenAI", return_value=mock_client):
                mock_cfg.VLM_API_KEY = "test-key"
                mock_cfg.VLM_API_BASE = "https://test.api/v1"
                mock_cfg.VLM_MODEL_NAME = "qwen-vl-max"

                result = self.parser.parse_image(tmp_path)
                assert 'error' in result
                assert 'API timeout' in result['error']
        finally:
            os.unlink(tmp_path)


class TestFormatFileSummaryImage:

    def setup_method(self):
        self.parser = FileParserTool()

    def test_image_analysis_format(self):
        parse_result = {
            'image_analysis': '图片中包含促销信息：满100减20',
            'columns': ['image_content'],
            'row_count': 1,
            'summary': {},
            'sample_rows': [],
        }
        result = self.parser.format_file_summary(parse_result, "promo.png")
        assert "promo.png" in result
        assert "满100减20" in result
        assert "图片解析结果" in result

    def test_normal_file_format_unchanged(self):
        parse_result = {
            'columns': ['name', 'price'],
            'row_count': 10,
            'summary': {'price': {'type': 'numeric', 'mean': 50.0, 'max': 100, 'min': 10}},
            'sample_rows': [{'name': 'A', 'price': 50}],
        }
        result = self.parser.format_file_summary(parse_result, "data.csv")
        assert "data.csv" in result
        assert "行数: 10" in result


class TestConfigVLM:

    def test_vlm_config_exists(self):
        from app.config import config
        assert hasattr(config, 'VLM_API_KEY')
        assert hasattr(config, 'VLM_API_BASE')
        assert hasattr(config, 'VLM_MODEL_NAME')

    def test_vlm_model_default(self):
        from app.config import config
        assert config.VLM_MODEL_NAME  # non-empty string