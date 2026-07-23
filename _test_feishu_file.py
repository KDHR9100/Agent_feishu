import sys
sys.path.insert(0, '/home/huajuanx/Agent_feishu')
from app.tools.file_parser_tool import file_parser_tool
from app.tools.feishu_tool import feishu_tool
import tempfile
import pandas as pd
import os

print('=== Feishu File Handling Validation ===')

print('\n1. Testing CSV file parsing...')
test_data = {'product': ['A', 'B', 'C'], 'price': [100, 200, 300], 'sales': [50, 30, 20]}
df = pd.DataFrame(test_data)
with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
    temp_path = f.name
df.to_csv(temp_path, index=False)
result = file_parser_tool.parse_local_file(temp_path)
status = 'SUCCESS' if 'error' not in result else 'FAILED'
print(f'   Result: {status}')
if 'error' not in result:
    print(f'   Columns: {result[" columns\]}')
