import os
import base64
import logging
import pandas as pd
from typing import Dict, Any

logger = logging.getLogger("file_parser")

# 支持的图片扩展名
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


class FileParserTool:
    # P9: CSV 编码回退链 —— utf-8 失败后依次尝试常见中文/西欧编码 (F43 GBK)
    _CSV_ENCODINGS = ('utf-8', 'utf-8-sig', 'gbk', 'gb18030', 'latin-1')

    def _read_csv_with_fallback(self, file_path: str) -> pd.DataFrame:
        last_err = None
        for enc in self._CSV_ENCODINGS:
            try:
                return pd.read_csv(file_path, encoding=enc)
            except UnicodeDecodeError as e:
                last_err = e
                continue
        raise last_err or ValueError('unable to decode csv file')

    def _read_excel_all_sheets(self, file_path: str):
        """P9: 读取全部 Sheet —— 仅读首个 Sheet 会漏掉放在后续 Sheet 的数据 (F46)。
        返回 (合并后的 DataFrame, sheet 名列表); 单 Sheet 时与旧行为等价。"""
        sheets = pd.read_excel(file_path, sheet_name=None)
        names = list(sheets.keys())
        if len(names) == 1:
            return sheets[names[0]], names
        frames = []
        for name in names:
            df = sheets[name].copy()
            df.insert(0, '__sheet__', name)
            frames.append(df)
        return pd.concat(frames, ignore_index=True, sort=False), names

    def parse_local_file(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return {'error': f'File not found: {file_path}', 'error_kind': 'not_found'}
        try:
            _, ext = os.path.splitext(file_path)
            ext_lower = ext.lower()
            sheets_info = None
            if ext_lower in ['.xlsx', '.xls']:
                df, sheets_info = self._read_excel_all_sheets(file_path)
            elif ext_lower == '.csv':
                df = self._read_csv_with_fallback(file_path)
            elif ext_lower == '.pdf':
                return self._parse_pdf(file_path)
            elif ext_lower == '.docx':
                return self._parse_word(file_path)
            elif ext_lower in IMAGE_EXTENSIONS:
                return self.parse_image(file_path)
            else:
                return {'error': f'Unsupported file type: {ext}',
                        'error_kind': 'unsupported'}
            columns = list(df.columns)
            row_count = len(df)
            # F42a: 解析成功但内容为空 —— 与损坏文件分开归类, 上层据此给出
            # "文件为空"而非"文件损坏"的确定性话术
            if row_count == 0 and not columns:
                return {'error': '文件内容为空（无表头无数据）',
                        'error_kind': 'empty_file'}
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
            result = {
                'columns': columns,
                'row_count': row_count,
                'summary': summary,
                'sample_rows': sample_rows,
                'file_path': file_path,
            }
            if sheets_info and len(sheets_info) > 1:
                result['sheets'] = sheets_info
                result['note'] = (
                    '该Excel包含%d个Sheet(%s), 已合并全部Sheet数据, '
                    '首列__sheet__标注各行来源' % (len(sheets_info), ', '.join(sheets_info)))
            return result
        except pd.errors.EmptyDataError:
            # F42a: 空文件 (如只有 BOM/换行的 CSV) —— 明确归类, 不冒充解析失败
            return {'error': '文件内容为空，未读取到任何数据',
                    'error_kind': 'empty_file'}
        except Exception as e:
            # F45: 损坏/结构不全 —— 与空文件区分, 便于上层给出针对性建议
            return {'error': f'Failed to parse file: {str(e)}',
                    'error_kind': 'corrupt_file'}

    def parse_image(self, file_path: str) -> Dict[str, Any]:
        """调用 VLM 解析图片, 提取表格数据/关键数值/促销文字"""
        from app.config import config

        if not config.VLM_API_KEY:
            return {'error': 'VLM_API_KEY not configured, cannot parse image'}

        try:
            # 读取图片并转为 base64
            with open(file_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            _, ext = os.path.splitext(file_path)
            mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                        '.png': 'image/png', '.webp': 'image/webp'}
            mime_type = mime_map.get(ext.lower(), 'image/png')
            image_url = f"data:{mime_type};base64,{image_data}"

            # 通过 OpenAI 兼容接口调用 VLM
            from openai import OpenAI
            client = OpenAI(
                api_key=config.VLM_API_KEY,
                base_url=config.VLM_API_BASE,
            )

            prompt = (
                "请分析这张图片，提取其中的关键信息。要求：\n"
                "1. 如果包含表格数据，转为 Markdown 表格格式\n"
                "2. 如果包含数值/价格/百分比，列出关键数值\n"
                "3. 如果包含促销文字/广告语，提取文案内容\n"
                "4. 用中文输出，格式清晰\n"
                "5. 如果图片内容与电商无关，简要描述图片内容"
            )

            response = client.chat.completions.create(
                model=config.VLM_MODEL_NAME,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
                max_tokens=2000,
            )

            content = response.choices[0].message.content or ""
            logger.info(
                "[parse_image] VLM response len=%d, model=%s"
                % (len(content), config.VLM_MODEL_NAME)
            )

            return {
                'columns': ['image_content'],
                'row_count': 1,
                'summary': {
                    'image_content': {
                        'type': 'image_analysis',
                        'model': config.VLM_MODEL_NAME,
                        'file_size': os.path.getsize(file_path),
                    }
                },
                'sample_rows': [{'content': content}],
                'file_path': file_path,
                'image_analysis': content,
            }
        except Exception as e:
            logger.error("[parse_image] error: %s" % str(e), exc_info=True)
            return {'error': f'Image parsing failed: {str(e)}'}

    def _parse_pdf(self, file_path: str) -> Dict[str, Any]:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return {'error': 'PyPDF2 not installed'}
        try:
            reader = PdfReader(file_path)
            pages = list(reader.pages)
        except Exception as e:
            # P9: 损坏/结构不全的 PDF (如缺 startxref) 给出可读诊断, 而非裸异常
            return {
                'columns': ['content'], 'row_count': 0, 'summary': {}, 'sample_rows': [],
                'file_path': file_path,
                'note': '该PDF文件结构不完整(%s), 无法提取内容; '
                        '可能是文件损坏、导出中断或并非真正的PDF文件' % str(e)[:60],
            }
        paragraphs = []
        for page in pages:
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
        result = {
            'columns': columns,
            'row_count': row_count,
            'summary': summary,
            'sample_rows': sample_rows,
            'file_path': file_path,
        }
        if row_count == 0:
            # P9: 明确告知"无文字层", 而不是只说解析为空
            result['note'] = (
                '该PDF共%d页但未提取到任何文字, 很可能是扫描版/图片版PDF(无文字层), '
                '建议改用OCR或提供可复制文字的PDF' % len(pages))
        return result

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

        # 图片解析结果特殊处理
        if parse_result.get("image_analysis"):
            return f"文件信息: {file_name}\n图片解析结果:\n{parse_result['image_analysis']}"

        summary = parse_result.get("summary", {})
        columns = parse_result.get("columns", [])
        row_count = parse_result.get("row_count", 0)
        sample_rows = parse_result.get("sample_rows", [])
        content_parts = [
            f"文件信息: {file_name}",
            f"列: {', '.join(columns)}",
            f"行数: {row_count}",
        ]
        if parse_result.get("note"):
            content_parts.append(f"注意: {parse_result['note']}")
        content_parts.append("数据摘要:")
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