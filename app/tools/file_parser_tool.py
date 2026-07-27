import os
import pandas as pd
from typing import Dict, Any


class FileParserTool:
    def parse_local_file(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return {'error': f'File not found: {file_path}'}
        try:
            _, ext = os.path.splitext(file_path)
            if ext.lower() in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            elif ext.lower() == '.csv':
                df = pd.read_csv(file_path)
            elif ext.lower() == '.pdf':
                return self._parse_pdf(file_path)
            elif ext.lower() == '.docx':
                return self._parse_word(file_path)
            else:
                return {'error': f'Unsupported file type: {ext}'}
            columns = list(df.columns)
            row_count = len(df)
            summary = {}
            for col in columns:
                if df[col].dtype in ['int64', 'float64']:
                    summary[col] = {
                        'type': 'numeric',
                        'mean': df[col].mean(),
                        'max': df[col].max(),
                        'min': df[col].min(),
                        'sum': df[col].sum(),
                        'std': df[col].std(),
                    }
                else:
                    summary[col] = {
                        'type': 'text',
                        'unique_count': df[col].nunique(),
                        'sample_values': df[col].dropna().unique()[:3].tolist(),
                    }
            sample_rows = df.head(3).to_dict('records')
            return {
                'columns': columns,
                'row_count': row_count,
                'summary': summary,
                'sample_rows': sample_rows,
                'file_path': file_path,
            }
        except Exception as e:
            return {'error': f'Failed to parse file: {str(e)}'}

    def _parse_pdf(self, file_path: str) -> Dict[str, Any]:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return {'error': 'PyPDF2 not installed'}
        reader = PdfReader(file_path)
        paragraphs = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                for para in text.split('\n\n'):
                    para = para.strip()
                    if para:
                        paragraphs.append(para)
        columns = ['content']
        row_count = len(paragraphs)
        total_chars = sum(len(p) for p in paragraphs)
        summary = {
            'content': {
                'type': 'text',
                'total_paragraphs': row_count,
                'total_characters': total_chars,
                'avg_paragraph_length': (total_chars // row_count if row_count > 0 else 0),
            }
        }
        sample_rows = [{'content': p[:200] + '...' if len(p) > 200 else p} for p in paragraphs[:3]]
        return {
            'columns': columns,
            'row_count': row_count,
            'summary': summary,
            'sample_rows': sample_rows,
            'file_path': file_path,
        }

    def _parse_word(self, file_path: str) -> Dict[str, Any]:
        try:
            from docx import Document
        except ImportError:
            return {'error': 'python-docx not installed'}
        doc = Document(file_path)
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        columns = ['content']
        row_count = len(paragraphs)
        total_chars = sum(len(p) for p in paragraphs)
        summary = {
            'content': {
                'type': 'text',
                'total_paragraphs': row_count,
                'total_characters': total_chars,
                'avg_paragraph_length': (total_chars // row_count if row_count > 0 else 0),
            }
        }
        sample_rows = [{'content': p[:200] + '...' if len(p) > 200 else p} for p in paragraphs[:3]]
        return {
            'columns': columns,
            'row_count': row_count,
            'summary': summary,
            'sample_rows': sample_rows,
            'file_path': file_path,
        }

    def format_file_summary(self, parse_result, file_name=""):
        """将解析结果格式化为摘要文本，供多个调用方复用"""
        if parse_result.get("error"):
            return ""
        summary = parse_result.get("summary", {})
        columns = parse_result.get("columns", [])
        row_count = parse_result.get("row_count", 0)
        sample_rows = parse_result.get("sample_rows", [])
        content_parts = [
            f"文件信息: {file_name}",
            f"列: {', '.join(columns)}",
            f"行数: {row_count}",
            "数据摘要:"
        ]
        for col, info in summary.items():
            if info.get("type") == "numeric":
                content_parts.append(
                    f"  - {col}: 均值={info.get('mean', 'N/A'):.2f}, "
                    f"最大={info.get('max', 'N/A')}, 最小={info.get('min', 'N/A')}"
                )
            else:
                content_parts.append(
                    f"  - {col}: 去重数={info.get('unique_count', 'N/A')}, "
                    f"样例={info.get('sample_values', [])}"
                )
        if sample_rows:
            content_parts.append("数据样例 (前3行):")
            for i, row in enumerate(sample_rows):
                content_parts.append(f"  第{i+1}行: {row}")
        return "\n".join(content_parts)


file_parser_tool = FileParserTool()
