import os
import pandas as pd
from typing import Dict, Any, List

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

file_parser_tool = FileParserTool()
