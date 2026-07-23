import os

file_path = '/home/huajuanx/Agent_feishu/app/tools/feishu_ws.py'

with open(file_path, 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()

# Find line with 'Parsed - msg_type' and insert mention check after it
insert_idx = None
for i, line in enumerate(lines):
    if 'Parsed - msg_type=' in line:
        insert_idx = i + 1
        break

if insert_idx is not None:
    mention_check_lines = [
        '',
        '        # Check if bot was mentioned in group chat',
        '        bot_name = os.getenv("FEISHU_BOT_NAME", "Ecommerce Agent")',
        '        is_group_chat = chat_id.startswith("oc_")',
        '',
        '        if is_group_chat:',
        '            bot_mentioned = False',
        '            if mentions:',
        '                for m in mentions:',
        '                    m_name = m.get("name", "")',
        '                    m_key = m.get("key", "")',
        '                    if m_name == bot_name or bot_name in m_key:',
        '                        bot_mentioned = True',
        '                        break',
        '            if not bot_mentioned:',
        '                logger.info("[Feishu WS] [%s] Group chat without mention, ignoring" % track_id)',
        '                return',
        '        else:',
        '            logger.info("[Feishu WS] [%s] Private chat, proceeding" % track_id)',
        ''
    ]
    lines = lines[:insert_idx] + [l + '\n' for l in mention_check_lines] + lines[insert_idx:]
    print('Mention check inserted')
else:
    print('Insert point not found')

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Step 1 done')