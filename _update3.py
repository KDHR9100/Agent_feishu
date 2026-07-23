import re

with open('/home/huajuanx/Agent_feishu/app/tools/feishu_ws.py', 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Add file_content = None
content = content.replace('            file_path = None', '            file_path = None\n            file_content = None')

# Add file parsing after download success
old_success = '''                    if download_result.get("success"):
                        file_path = save_path
                        logger.info("[Feishu WS] [%s] File downloaded successfully: %s" % (track_id, file_path))
                    else:'''

new_success = '''                    if download_result.get("success"):
                        file_path = save_path
                        logger.info("[Feishu WS] [%s] File downloaded successfully: %s" % (track_id, file_path))

                        parse_start = time.time()
                        try:
                            from app.tools.file_parser_tool import file_parser_tool
                            parse_result = file_parser_tool.parse_local_file(file_path)
                            if parse_result.get("error"):
                                file_content = "File parse failed: " + parse_result["error"]
                                logger.warning("[Feishu WS] [%s] File parsing failed: %s" % (track_id, parse_result["error"]))
                            else:
                                columns = parse_result.get("columns", [])
                                row_count = parse_result.get("row_count", 0)
                                summary = parse_result.get("summary", {})
                                sample_rows = parse_result.get("sample_rows", [])
                                content_parts = []
                                content_parts.append("File: " + os.path.basename(file_path))
                                content_parts.append("Columns: " + ", ".join(columns))
                                content_parts.append("Rows: " + str(row_count))
                                content_parts.append("")
                                content_parts.append("Summary:")
                                for col, stats in summary.items():
                                    if stats.get("type") == "numeric":
                                        content_parts.append("- " + col + ": mean=" + str(round(stats["mean"], 2)) + ", max=" + str(stats["max"]) + ", min=" + str(stats["min"]))
                                    else:
                                        content_parts.append("- " + col + ": unique=" + str(stats["unique_count"]) + ", sample=" + str(stats["sample_values"]))
                                if sample_rows:
                                    content_parts.append("")
                                    content_parts.append("First 3 rows:")
                                    for i, row in enumerate(sample_rows):
                                        content_parts.append(str(i+1) + ". " + json.dumps(row, ensure_ascii=False))
                                file_content = "\\n".join(content_parts)
                                logger.info("[Feishu WS] [%s] File parsed, content length: %d" % (track_id, len(file_content)))
                        except Exception as e:
                            file_content = "File parse error: " + str(e)
                            logger.error("[Feishu WS] [%s] Error parsing file: %s" % (track_id, str(e)))
                        monitoring_stats.record_feishu_api_call(time.time() - parse_start)
                    else:'''

content = content.replace(old_success, new_success)

# Add file_content to agent_input
old_agent = '''                if file_path:
                    agent_input["file_path"] = file_path
                    logger.info("[Feishu WS] [%s] File path added to agent input: %s" % (track_id, file_path))
                else:
                    logger.info("[Feishu WS] [%s] No file path to add" % track_id)

                result = agent.invoke(agent_input)'''

new_agent = '''                if file_path:
                    agent_input["file_path"] = file_path
                    logger.info("[Feishu WS] [%s] File path added to agent input: %s" % (track_id, file_path))
                else:
                    logger.info("[Feishu WS] [%s] No file path to add" % track_id)
                if file_content:
                    agent_input["file_content"] = file_content
                    logger.info("[Feishu WS] [%s] File content added to agent input, length: %d" % (track_id, len(file_content)))
                else:
                    logger.info("[Feishu WS] [%s] No file content to add" % track_id)

                result = agent.invoke(agent_input)'''

content = content.replace(old_agent, new_agent)

with open('/home/huajuanx/Agent_feishu/app/tools/feishu_ws.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done')