"""评测系统与 FeishuAgent 的唯一对接层（只读，不修改主代码）。

- ``MockFeishuAgent``：EVAL_MODE=mock 的进程内替身，按 skills_manifest
  关键词确定性路由 + 模板回复，CI 零 token 且完全不 import app.*；
- ``RealFeishuAgent``：进程内 stream 调用 ``app.agent.workflow.agent``，
  采集逐节点轨迹与 Guardrails（security logger）事件。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Protocol, runtime_checkable

import structlog

from evaluation.trajectory import make_turn_record

logger = structlog.get_logger(__name__)

#: 仓库根目录下的技能清单（真值来源，只读）
SKILLS_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "skills_manifest.json"

#: 攻击语料（安全维评测 + mock 拦截模拟）
ATTACKS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "attacks.jsonl"

#: 评测隔离用业务数据目录
FIXTURES_DATA_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "data"

_SKU_RE = re.compile(r"[A-Za-z]{2,}[-_]?[A-Za-z0-9\-_]{2,}")

# 写作语境词：命中的"降价/打折"只是创作素材而非执行指令（与主项目语义一致）
_WRITING_CONTEXT_WORDS = ("文案", "标题", "描述", "广告语", "话术", "写一段", "帮写", "撰写")

# 明示调价指令判别（mock 版，与主项目 has_explicit_directive 语义对齐但独立实现）：
# 咨询/比较语境（"有没有降价""要不要降价"）不算指令，必须带执行语义
_PRICING_DIRECTIVE_RE = re.compile(
    r"(降|涨)\s*\d+\s*[%％]"              # 降 20%
    r"|(降|涨)价?\s*到\s*¥?\s*\d"          # 降到 9.9 / 降价到 9.9
    r"|(改|调)\s*价"                        # 改价 / 调价
    r"|打\s*折\s*\d|折扣\s*\d"              # 打折 5 折
)
_PRICING_IMPERATIVE_RE = re.compile(
    r"(降价|涨价)[^。？！\n]{0,8}(执行|立即|直接)"
    r"|(执行|立即|直接)[^。？！\n]{0,8}(降价|涨价)"
)


def load_skills_manifest(path: Optional[Path] = None) -> Dict[str, object]:
    """加载 FeishuAgent 现有 skills_manifest.json（只读）。"""

    manifest_path = Path(path) if path else SKILLS_MANIFEST_PATH
    with open(manifest_path, "r", encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def manifest_skill_names(manifest: Optional[Dict[str, object]] = None) -> set:
    """manifest 中全部合法技能名。"""

    data = manifest if manifest is not None else load_skills_manifest()
    return {s["name"] for s in data.get("skills", [])}  # type: ignore[union-attr]


def load_attacks(path: Optional[Path] = None) -> List[Dict[str, object]]:
    """加载攻击语料 attacks.jsonl（每行含 payload/category/should_block）。"""

    attack_path = Path(path) if path else ATTACKS_PATH
    items: List[Dict[str, object]] = []
    with open(attack_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def has_pricing_directive(text: str) -> bool:
    """是否含明示调价指令（咨询问价/竞品比较不算）。"""

    if any(w in text for w in _WRITING_CONTEXT_WORDS):
        return False
    return bool(_PRICING_DIRECTIVE_RE.search(text) or _PRICING_IMPERATIVE_RE.search(text))


@runtime_checkable
class AgentAdapter(Protocol):
    """被测 Agent 适配器协议：发一条消息，返回一轮轨迹记录。

    ``history_user_msgs`` 为评测侧已知的历史用户消息（mock 替身用来
    模拟"记得前文"；真实 Agent 自带 memory，忽略该参数）。
    """

    def send(
        self,
        message: str,
        conversation_id: str,
        history_user_msgs: Optional[List[str]] = None,
    ) -> Dict[str, object]: ...


# ============================================================
# Mock 路径：关键词路由 + 模板回复（确定性，CI 零 token）
# ============================================================
def _det_int(seed: str, mod: int) -> int:
    """由种子确定性派生整数（同一 SKU/技能跨轮数值稳定，供一致性校验）。

    注意：仅用于生成确定性的模拟数据，不用于任何安全目的。
    """

    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(h, 16) % mod


_SKILL_TEMPLATES: Dict[str, str] = {
    "product_skill": (
        "『商品诊断』{sku} 近 7 天销量 {n1} 件、销售额 ¥{n2}，环比 {n3}%。"
        "Top SKU 表现稳定，建议关注评价与退货率，单品经营情况整体健康。"
    ),
    "ads_skill": (
        "『广告诊断』近 7 天 ACOS 由 18% 升至 32%，ROI 从 4.2 降至 2.1，"
        "花费集中在 CAMP001。建议：否定低效词、降低出价 10%、聚焦高转化渠道。"
    ),
    "inventory_skill": (
        "『库存体检』{sku} 当前库存 {n1} 件，近 30 天销量 {n2} 件，"
        "库存周转天数约 {n3} 天，{status}。补货建议：按安全库存的一半分批补货。"
    ),
    "competitor_skill": (
        "『竞品监控』监测到 5 个同款竞品，均价 ¥{n1}，竞品降价 8% 抢量。"
        "建议持续跟踪其广告投放与评分变化，竞品情报已入池。"
    ),
    "report_skill": (
        "『运营报告』本周运营报告已生成：销售额环比 +12%，广告花费占比 18%，"
        "库存周转改善，Top SKU 贡献 62% 销量。报告文件：report_{date}.md"
    ),
    "rag_skill": (
        "『知识库问答』根据平台规则文档：佣金按类目阶梯计算，申报价即供货价，"
        "核价通过后 48 小时内上架。更多细则可追问。（来源：平台规则知识库）"
    ),
    "seo_skill": (
        "『SEO 优化』核心关键词月搜索量 {n1}，建议标题埋入长尾词，"
        "五点描述覆盖使用场景词，后台关键词去重后控制在 200 字节内。"
    ),
    "support_skill": (
        "『客服支持』订单 {oid} 已查询：物流状态运输中，预计 3 日达。"
        "退款政策：7 天无理由退货。已生成回复话术，可直接发送买家。"
    ),
    "data_analysis_skill": (
        "『数据概况』近 30 天整体数据：销量同比 +9%，环比 -3%，"
        "广告花费同比 +21%，未检测到异常波动，统计明细可导出。"
    ),
    "file_analysis_skill": (
        "『文件解析』已解析上传表格：共 {n1} 行，识别关键字段 "
        "SKU/销量/花费/ROI，摘要统计已生成，可继续追问单字段分析。"
    ),
    "help_skill": (
        "『功能导航』我可以：查销量与商品数据、库存预警、广告 ROI 分析、"
        "竞品监控、生成运营报告、定价建议（走审批）、平台规则问答、Listing 生成。"
    ),
    "listing": (
        "『Listing 生成』已生成多语言合规 Listing：标题、五点描述、后台关键词"
        "（覆盖 EN/DE/FR/ES），可直接复制到平台上架。"
    ),
    "pricing_skill": (
        "『定价建议』{sku} 建议活动价 ¥{n1}（蒙特卡洛 1000 次模拟，"
        "ROI 提升区间 8%~15%，置信度 90%）。如需执行调价请明确指令，将走人工审批。"
    ),
}

_APPROVAL_RESPONSE = (
    "⏳ 该操作属于高危调价指令（{sku} 降价/调价执行），"
    "需要人工审批。已发送审批卡片，请在卡片上点击【批准并执行】或【拒绝】。"
)
_SAFE_BLOCK_RESPONSE = (
    "⚠️ 检测到潜在风险指令，已拦截。请换一种方式描述您的电商运营需求。"
)
_UNKNOWN_RESPONSE = (
    "抱歉，我暂时无法识别这个需求，可以换种说法吗？"
    "例如：查销量、看库存、分析广告 ROI、生成运营报告。"
)


class MockFeishuAgent:
    """mock 模式被测 Agent 替身：关键词路由 + 确定性模板。"""

    def __init__(self, manifest: Optional[Dict[str, object]] = None) -> None:
        manifest = manifest if manifest is not None else load_skills_manifest()
        self._skills: List[Dict[str, object]] = list(manifest.get("skills", []))  # type: ignore[arg-type]
        self._attacks = load_attacks()

    # ---- 关键词评分路由（对齐主项目 keyword fallback 思路）----
    def _route(self, message: str) -> List[str]:
        scores: Dict[str, int] = {}
        for skill in self._skills:
            name = str(skill["name"])
            hit = sum(1 for kw in skill.get("keywords", []) if kw in message)  # type: ignore[union-attr]
            if hit:
                scores[name] = hit
        if not scores:
            return ["unknown"]
        top = max(scores.values())
        return [name for name, sc in scores.items() if sc == top]

    def _match_attack(self, message: str) -> Optional[Dict[str, object]]:
        for atk in self._attacks:
            payload = str(atk["payload"])
            if payload and payload in message:
                return atk
        return None

    def _render(self, skill: str, message: str, history_user_msgs: List[str]) -> str:
        date = time.strftime("%Y%m%d")
        if skill == "ads_skill":
            return _SKILL_TEMPLATES[skill].format(n1="", n2="", n3="")
        sku = self._pick_sku(message, history_user_msgs)
        seed = f"{sku}:{skill}"
        if skill in ("product_skill", "inventory_skill", "pricing_skill"):
            status = "库存偏高，建议关注周转" if _det_int(seed + "st", 2) else "库存健康"
            return _SKILL_TEMPLATES[skill].format(
                sku=sku, n1=_det_int(seed + "1", 900) + 100,
                n2=_det_int(seed + "2", 8000) + 1000,
                n3=_det_int(seed + "3", 70) + 10, status=status,
            )
        if skill == "report_skill":
            return _SKILL_TEMPLATES[skill].format(date=date)
        if skill == "support_skill":
            m = re.search(r"\d{6,}", message)
            oid = m.group(0) if m else "1000" + str(_det_int(seed, 9000) + 1000)
            return _SKILL_TEMPLATES[skill].format(oid=oid)
        if skill in ("competitor_skill", "seo_skill", "file_analysis_skill"):
            return _SKILL_TEMPLATES[skill].format(n1=_det_int(seed, 900) + 100)
        return _SKILL_TEMPLATES[skill]

    @staticmethod
    def _pick_sku(message: str, history_user_msgs: List[str]) -> str:
        """当前消息或历史中最近提到的 SKU（模拟"记得前文"）。"""

        m = _SKU_RE.search(message)
        if m:
            return m.group(0).upper()
        for prev in reversed(history_user_msgs):
            m = _SKU_RE.search(prev)
            if m:
                return m.group(0).upper()
        return "SKU-DEFAULT"

    @staticmethod
    def _first_sku(history_user_msgs: List[str]) -> str:
        for prev in history_user_msgs:
            m = _SKU_RE.search(prev)
            if m:
                return m.group(0).upper()
        return "SKU-DEFAULT"

    def send(
        self,
        message: str,
        conversation_id: str,
        history_user_msgs: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        history = list(history_user_msgs or [])

        # 1) 攻击拦截（should_block 类）：模拟 Guardrails 双防线拦截
        atk = self._match_attack(message)
        if atk is not None and atk.get("should_block"):
            return make_turn_record(
                turn=0,  # 由 orchestrator 覆写
                user_message=message,
                agent_answer=_SAFE_BLOCK_RESPONSE,
                intent="injection_blocked",
                skills_to_execute=[],
                skill_results=[],
                safety_events=[{"category": atk.get("category"), "blocked": True, "source": "mock_guardrails"}],
            )

        # 2) 明示调价指令 → 审批门（不可绕过），回显目标 SKU 供一致性校验
        if has_pricing_directive(message):
            answer = _APPROVAL_RESPONSE.format(
                sku=self._pick_sku(message, history)
            )
            return make_turn_record(
                turn=0,
                user_message=message,
                agent_answer=answer,
                intent="pricing_skill",
                skills_to_execute=["pricing_skill"],
                skill_results=[{"skill": "pricing_skill", "type": "approval_required", "data": answer}],
                safety_events=[{"category": "approval_gate", "blocked": False, "source": "mock_approval"}],
            )

        # 3) 关键词路由 + 模板
        skills = self._route(message)
        if skills == ["unknown"]:
            answer = _UNKNOWN_RESPONSE
            intent = "unknown"
            results: List[Dict[str, object]] = []
        else:
            intent = skills[0]
            # 探针类追问（"最开始问的那个"）回指首个 SKU，模拟长期记忆
            if any(mk in message for mk in ("最开始", "最一开始", "最早", "第一个")):
                answer = self._render_anchored(skills[0], history + [message])
            else:
                answer = self._render(skills[0], message, history)
            results = [{"skill": skills[0], "type": "analysis", "data": answer}]

        return make_turn_record(
            turn=0,
            user_message=message,
            agent_answer=answer,
            intent=intent,
            skills_to_execute=skills,
            skill_results=results,
        )

    def _render_anchored(self, skill: str, msgs: List[str]) -> str:
        """探针追问：以对话中首个被提及的 SKU 锚定回答。"""

        first = self._first_sku(msgs)
        seed = f"{first}:{skill}:anchor"
        if skill == "inventory_skill":
            return _SKILL_TEMPLATES[skill].format(
                sku=first, n1=_det_int(seed + "1", 900) + 100,
                n2=_det_int(seed + "2", 800) + 80,
                n3=_det_int(seed + "3", 60) + 15, status="库存健康",
            )
        if skill == "pricing_skill":
            return _SKILL_TEMPLATES[skill].format(sku=first, n1=_det_int(seed, 60) + 39)
        if skill == "product_skill":
            return _SKILL_TEMPLATES[skill].format(
                sku=first, n1=_det_int(seed + "1", 900) + 100,
                n2=_det_int(seed + "2", 8000) + 1000,
                n3=_det_int(seed + "3", 70) + 10,
            )
        return self._render(skill, " ".join(msgs[-2:]), msgs[:-2])


# ============================================================
# Real 路径：进程内 stream 调用真实 LangGraph（方案选型 A）
# ============================================================
class _SecurityLogCollector:
    """挂在 security logger 上的只读 Handler，采集 Guardrails 命中日志。"""

    def __init__(self) -> None:
        import logging

        self.records: List[Dict[str, object]] = []
        self._handler = logging.Handler()
        self._handler.emit = self._emit  # type: ignore[method-assign]

    def _emit(self, record: object) -> None:
        try:
            rec = record  # type: ignore[has-type]
            self.records.append(
                {
                    "level": getattr(rec, "levelname", "INFO"),
                    "message": str(getattr(rec, "getMessage", lambda: "")())[:500],
                    "source": "security_logger",
                }
            )
        except Exception:  # noqa: BLE001 - 日志采集永不影响主流程
            pass

    def attach(self) -> None:
        import logging

        logging.getLogger("security").addHandler(self._handler)

    def detach(self) -> None:
        import logging

        logging.getLogger("security").removeHandler(self._handler)

    def drain(self) -> List[Dict[str, object]]:
        records, self.records = self.records, []
        return records


class RealFeishuAgent:
    """进程内调用真实 FeishuAgent（import 前完成环境隔离）。"""

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = Path(run_dir)
        self._run_dir.mkdir(parents=True, exist_ok=True)

        # ---- 环境隔离（必须在 import app.* 之前）----
        os.environ["ROUTER_CACHE_ENABLED"] = "false"
        os.environ["DATABASE_URL"] = f"sqlite:///{self._run_dir / 'agent.db'}"
        os.environ["BIZ_DATA_DIR"] = str(FIXTURES_DATA_DIR)
        os.environ.setdefault("APPROVAL_ENABLED", "true")

        import app.agent.workflow as wf  # 延迟导入：mock 模式不加载主项目

        self._agent = wf.agent

        # 评测进程没有 FastAPI startup，需显式建表（conversations 等），
        # 否则 save_history 写隔离库会因表缺失而丢历史（调用主项目公开函数，不改其代码）
        try:
            from app.models import init_db

            init_db()
        except Exception as exc:  # noqa: BLE001 - 建表失败不阻塞评测
            logger.warning("real_agent_init_db_failed", error=str(exc))

        self._collector = _SecurityLogCollector()
        logger.info("real_agent_ready", db=str(self._run_dir / "agent.db"))

    def send(
        self,
        message: str,
        conversation_id: str,
        history_user_msgs: Optional[List[str]] = None,  # 真实 Agent 自带 memory, 忽略
    ) -> Dict[str, object]:
        self._collector.attach()
        t0 = time.time()
        updates: List[Dict[str, object]] = []
        timings: Dict[str, float] = {}
        intent, skills, plan = "", [], None
        skill_results: List[Dict[str, object]] = []
        reflect_decision, answer, token_usage = "sufficient", "", {}
        router_rounds = 0

        try:
            stream = self._agent.stream(
                {"user_input": message, "conversation_id": conversation_id},
                config={"recursion_limit": 60},
                stream_mode="updates",
            )
            for chunk in stream:
                node_t0 = time.time()
                if isinstance(chunk, tuple):  # 兼容不同 langgraph 版本的产出形态
                    chunk = chunk[-1]
                if not isinstance(chunk, dict):
                    continue
                for node, delta in chunk.items():
                    if not isinstance(delta, dict):
                        continue
                    timings[node] = round((time.time() - node_t0) * 1000, 1)
                    if node == "router":
                        router_rounds += 1
                        intent = delta.get("intent") or intent
                        skills = delta.get("skills_to_execute") or skills
                    elif node == "planner":
                        plan = delta.get("execution_plan") or plan
                    elif node == "skill_executor":
                        skill_results = delta.get("skill_results") or skill_results
                        token_usage = delta.get("token_usage") or token_usage
                    elif node == "reflect":
                        reflect_decision = delta.get("reflect_decision") or reflect_decision
                    elif node == "answer":
                        answer = delta.get("answer") or answer
                    updates.append({"node": node})
        finally:
            self._collector.detach()

        if not answer:  # 兜底：stream 异常时至少留下可评测的错误轨迹
            answer = "[eval] agent 未返回 answer（stream 异常或被中断）"
        logger.info(
            "real_agent_turn_done",
            conversation_id=conversation_id,
            elapsed_ms=round((time.time() - t0) * 1000, 1),
        )

        return make_turn_record(
            turn=0,
            user_message=message,
            agent_answer=answer,
            intent=intent or "unknown",
            skills_to_execute=skills,
            skill_results=skill_results,
            execution_plan=plan,
            reflect_decision=reflect_decision,
            retry_rounds=max(0, router_rounds - 1),
            token_usage=token_usage,
            node_timings_ms=timings,
            safety_events=self._collector.drain(),
        )
