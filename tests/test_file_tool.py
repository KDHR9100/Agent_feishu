"""测试 FileTool 路径穿越防护和基本文件操作"""
import os
import pytest


class TestPathTraversal:
    def test_normal_path_allowed(self, file_tool, tmp_dir):
        result = file_tool.write_file("test.txt", "hello", "text")
        assert result.get("success") is True
        assert tmp_dir in result["path"]

    def test_subdir_path_allowed(self, file_tool, tmp_dir):
        result = file_tool.write_file("subdir/test.txt", "hello", "text")
        assert result.get("success") is True

    def test_traversal_read_blocked(self, file_tool):
        result = file_tool.read_file("../../etc/passwd")
        assert "error" in result

    def test_traversal_write_blocked(self, file_tool):
        result = file_tool.write_file("../../etc/evil.txt", "malicious", "text")
        assert "error" in result

    def test_traversal_delete_blocked(self, file_tool):
        result = file_tool.delete_file("../../etc/passwd")
        assert "error" in result

    def test_traversal_list_blocked(self, file_tool):
        result = file_tool.list_files("../../etc")
        assert "error" in result

    def test_traversal_append_blocked(self, file_tool):
        result = file_tool.append_to_file("../../etc/evil.txt", "malicious")
        assert "error" in result


class TestFileOperations:
    def test_write_and_read_text(self, file_tool):
        file_tool.write_file("hello.txt", "world", "text")
        result = file_tool.read_file("hello.txt")
        assert result["content"] == "world"
        assert result["format"] == "text"

    def test_write_and_read_json(self, file_tool):
        data = {"key": "value", "num": 42}
        file_tool.write_file("data.json", data, "json")
        result = file_tool.read_file("data.json")
        assert result["content"]["key"] == "value"
        assert result["format"] == "json"

    def test_write_and_read_csv(self, file_tool):
        data = [{"name": "a", "val": 1}, {"name": "b", "val": 2}]
        file_tool.write_file("data.csv", data, "csv")
        result = file_tool.read_file("data.csv")
        assert len(result["content"]) == 2
        assert result["format"] == "csv"

    def test_list_files(self, file_tool):
        file_tool.write_file("a.txt", "a", "text")
        file_tool.write_file("b.txt", "b", "text")
        result = file_tool.list_files()
        assert len(result["files"]) >= 2

    def test_delete_file(self, file_tool):
        file_tool.write_file("del.txt", "bye", "text")
        result = file_tool.delete_file("del.txt")
        assert result["success"] is True
        result2 = file_tool.read_file("del.txt")
        assert "error" in result2

    def test_append_to_file(self, file_tool):
        file_tool.write_file("app.txt", "line1", "text")
        file_tool.append_to_file("app.txt", "line2")
        result = file_tool.read_file("app.txt")
        assert "line2" in result["content"]