import os
import json
import csv
from typing import Dict, Any


class FileTool:
    def __init__(self, base_dir: str = "./data"):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def read_file(self, file_path: str) -> Dict[str, Any]:
        full_path = os.path.join(self.base_dir, file_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                if file_path.endswith(".json"):
                    return {"content": json.load(f), "format": "json"}
                elif file_path.endswith(".csv"):
                    with open(full_path, "r", encoding="utf-8") as cf:
                        reader = csv.DictReader(cf)
                        return {"content": list(reader), "format": "csv"}
                else:
                    return {"content": f.read(), "format": "text"}
        except Exception as e:
            return {"error": str(e)}

    def write_file(
        self, file_path: str, content: Any, format_type: str = "text"
    ) -> Dict[str, Any]:
        full_path = os.path.join(self.base_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                if format_type == "json":
                    json.dump(content, f, ensure_ascii=False, indent=2)
                elif format_type == "csv":
                    if isinstance(content, list) and content:
                        writer = csv.DictWriter(f, fieldnames=content[0].keys())
                        writer.writeheader()
                        writer.writerows(content)
                else:
                    f.write(str(content))
            return {"success": True, "path": full_path}
        except Exception as e:
            return {"error": str(e)}

    def list_files(self, directory: str = "") -> Dict[str, Any]:
        full_path = os.path.join(self.base_dir, directory)
        try:
            files = []
            for root, dirs, filenames in os.walk(full_path):
                for filename in filenames:
                    files.append(
                        os.path.relpath(os.path.join(root, filename), self.base_dir)
                    )
            return {"files": files}
        except Exception as e:
            return {"error": str(e)}

    def delete_file(self, file_path: str) -> Dict[str, Any]:
        full_path = os.path.join(self.base_dir, file_path)
        try:
            if os.path.exists(full_path):
                os.remove(full_path)
                return {"success": True}
            else:
                return {"error": "File not found"}
        except Exception as e:
            return {"error": str(e)}

    def append_to_file(self, file_path: str, content: str) -> Dict[str, Any]:
        full_path = os.path.join(self.base_dir, file_path)
        try:
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(content + "\n")
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}


file_tool = FileTool()
