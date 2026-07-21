import os

def fix_w391(path):
    with open(path, 'r') as f:
        lines = f.readlines()
    if lines and lines[-1].strip() == '':
        lines = lines[:-1]
    if lines and not lines[-1].endswith('\n'):
        lines[-1] = lines[-1] + '\n'
    with open(path, 'w') as f:
        f.writelines(lines)

def fix_blank_lines(path):
    with open(path, 'r') as f:
        content = f.read()
    
    content = content.replace('\n\n\n', '\n\n')
    content = content.replace('\n\n\n', '\n\n')
    
    lines = content.splitlines()
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == '':
            if i > 0 and lines[i-1].strip() == '':
                i += 1
                continue
        result.append(line)
        i += 1
    
    with open(path, 'w') as f:
        f.write('\n'.join(result) + '\n')

files_to_fix = [
    '/home/huajuanx/Agent_feishu/app/__init__.py',
    '/home/huajuanx/Agent_feishu/app/agent/__init__.py',
    '/home/huajuanx/Agent_feishu/app/agents/__init__.py',
    '/home/huajuanx/Agent_feishu/app/api/__init__.py',
    '/home/huajuanx/Agent_feishu/app/agents/ads_agent.py',
    '/home/huajuanx/Agent_feishu/app/agents/content_agent.py',
    '/home/huajuanx/Agent_feishu/app/agents/coordinator.py',
    '/home/huajuanx/Agent_feishu/app/agents/product_agent.py',
    '/home/huajuanx/Agent_feishu/app/api/feishu.py',
    '/home/huajuanx/Agent_feishu/app/config.py',
]

for fpath in files_to_fix:
    if os.path.exists(fpath):
        fix_w391(fpath)
        fix_blank_lines(fpath)
        print(f'Fixed: {os.path.basename(fpath)}')

print('All fixes applied!')
