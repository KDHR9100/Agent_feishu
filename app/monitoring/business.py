# -*- coding: utf-8 -*-
"""业务价值度量层: 按用户/任务维度量化使用规模与效率收益

商业价值证据链: 谁在用(活跃用户) -> 用了多少(任务量/成功率) -> 值多少(节省工时估算)

- record_task(): 每次用户任务完成后落一条 BusinessTaskLog (SQLite)
- get_summary(days): 任务量/成功率/DAU/技能分布/节省工时估算/Top 用户
- generate_value_report(days): 生成 Markdown 业务价值报告 (定时任务/按需查看)

节省工时换算: 按 MANUAL_TIME_MINUTES (各技能人工基准耗时) 累计成功任务,
系数为经验估算值, 可按实际业务校准。DB 不可用时自动降级为内存统计,
度量失败永远不影响主流程。
"""
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("business_metrics")

# 人工基准耗时(分钟): 成功完成一次任务相对人工操作节省的时间
MANUAL_TIME_MINUTES = {
    "product_skill": 15,       # 商品销售数据分析
    "ads_skill": 15,           # 广告效果分析
    "inventory_skill": 10,     # 库存盘点与预警
    "content_skill": 20,       # 营销文案撰写
    "report_skill": 30,        # 运营报告撰写
    "competitor_skill": 30,    # 竞品情报收集
    "data_analysis_skill": 25,  # 深度数据分析
    "seo_skill": 20,           # SEO 关键词研究
    "support_skill": 8,        # 客服工单处理
    "file_analysis_skill": 12,  # 表格/文件分析
    "rag_skill": 5,            # 规则知识查询
    "pricing_skill": 45,       # 定价测算(人工需拉表+模拟)
    "help_skill": 1,
    "general": 5,
}
DEFAULT_MANUAL_MINUTES = 10

_MAX_MEMORY_RECORDS = 5000


class BusinessMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._db_checked = False
        self._db_ok = False
        # DB 不可用时的内存兜底: (created_at, user_id, skill_name, success, duration)
        self._memory_records = []

    # ---------- DB 探测 (只探测一次) ----------
    def _ensure_db(self):
        if not self._db_checked:
            try:
                from app.models.database import engine, Base
                import app.models.models  # ensure ORM models registered before create_all
                Base.metadata.create_all(bind=engine)
                self._db_ok = True
            except Exception as e:
                logger.warning("[business] DB unavailable, memory fallback: %s", e)
                self._db_ok = False
            self._db_checked = True
        return self._db_ok

    # ---------- 记录 ----------
    def record_task(self, user_id, skill_name, success=True, duration_seconds=0.0,
                    conversation_id="", channel="feishu"):
        """记录一次用户任务; 任何失败都静默降级, 不影响主流程"""
        try:
            if self._ensure_db():
                from app.models.database import SessionLocal
                from app.models.models import BusinessTaskLog

                session = SessionLocal()
                try:
                    session.add(BusinessTaskLog(
                        user_id=str(user_id or "unknown")[:100],
                        conversation_id=str(conversation_id or "")[:100],
                        skill_name=str(skill_name or "general")[:100],
                        channel=str(channel or "feishu")[:50],
                        success=bool(success),
                        duration_seconds=float(duration_seconds or 0.0),
                        created_at=datetime.utcnow(),
                    ))
                    session.commit()
                finally:
                    session.close()
                return
        except Exception as e:
            logger.warning("[business] DB record failed, memory fallback: %s", e)
        with self._lock:
            self._memory_records.append((
                datetime.utcnow(), str(user_id or "unknown"),
                str(skill_name or "general"), bool(success),
                float(duration_seconds or 0.0),
            ))
            if len(self._memory_records) > _MAX_MEMORY_RECORDS:
                self._memory_records = self._memory_records[-_MAX_MEMORY_RECORDS:]

    # ---------- 汇总 ----------
    def get_summary(self, days=7):
        """业务价值汇总: 覆盖最近 days 天"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        if self._ensure_db():
            try:
                return self._summary_from_db(cutoff, days)
            except Exception as e:
                logger.warning("[business] DB summary failed, memory fallback: %s", e)
        return self._summary_from_memory(cutoff, days)

    def _summary_from_db(self, cutoff, days):
        from sqlalchemy import func
        from app.models.database import SessionLocal
        from app.models.models import BusinessTaskLog

        session = SessionLocal()
        try:
            base_q = session.query(BusinessTaskLog).filter(
                BusinessTaskLog.created_at >= cutoff)

            total_tasks = base_q.count()
            success_count = base_q.filter(BusinessTaskLog.success == True).count()  # noqa: E712
            unique_users = session.query(
                func.count(func.distinct(BusinessTaskLog.user_id))
            ).filter(BusinessTaskLog.created_at >= cutoff).scalar() or 0
            avg_duration = base_q.with_entities(
                func.avg(BusinessTaskLog.duration_seconds)).scalar() or 0.0

            # DAU 分布 (按天)
            dau_rows = base_q.with_entities(
                func.date(BusinessTaskLog.created_at).label("day"),
                func.count(func.distinct(BusinessTaskLog.user_id)),
            ).group_by("day").order_by("day").all()
            daily_active_users = {str(r[0]): r[1] for r in dau_rows}

            # 技能分布
            skill_rows = base_q.with_entities(
                BusinessTaskLog.skill_name, func.count(BusinessTaskLog.id)
            ).group_by(BusinessTaskLog.skill_name).order_by(
                func.count(BusinessTaskLog.id).desc()).all()
            skill_distribution = {r[0]: r[1] for r in skill_rows}

            # Top 用户
            user_rows = base_q.with_entities(
                BusinessTaskLog.user_id, func.count(BusinessTaskLog.id).label("tasks")
            ).group_by(BusinessTaskLog.user_id).order_by(
                func.count(BusinessTaskLog.id).desc()).limit(10).all()
            top_users = [{"user_id": r[0], "tasks": r[1]} for r in user_rows]

            # 节省工时: 仅成功任务按人工基准耗时累计
            saved_rows = base_q.filter(BusinessTaskLog.success == True).with_entities(  # noqa: E712
                BusinessTaskLog.skill_name, func.count(BusinessTaskLog.id)
            ).group_by(BusinessTaskLog.skill_name).all()
            minutes_saved = sum(
                cnt * MANUAL_TIME_MINUTES.get(skill, DEFAULT_MANUAL_MINUTES)
                for skill, cnt in saved_rows
            )
        finally:
            session.close()

        return self._build_summary(
            days, total_tasks, success_count, unique_users, avg_duration,
            daily_active_users, skill_distribution, top_users, minutes_saved,
        )

    def _summary_from_memory(self, cutoff, days):
        with self._lock:
            records = [r for r in self._memory_records if r[0] >= cutoff]

        total_tasks = len(records)
        success_records = [r for r in records if r[3]]
        success_count = len(success_records)
        unique_users = len({r[1] for r in records})
        avg_duration = (sum(r[4] for r in records) / total_tasks) if total_tasks else 0.0

        daily_active_users = {}
        for r in records:
            day = r[0].strftime("%Y-%m-%d")
            daily_active_users.setdefault(day, set()).add(r[1])
        daily_active_users = {d: len(u) for d, u in sorted(daily_active_users.items())}

        skill_distribution = {}
        for r in records:
            skill_distribution[r[2]] = skill_distribution.get(r[2], 0) + 1

        user_counter = {}
        for r in records:
            user_counter[r[1]] = user_counter.get(r[1], 0) + 1
        top_users = [{"user_id": u, "tasks": c}
                     for u, c in sorted(user_counter.items(),
                                        key=lambda x: x[1], reverse=True)[:10]]

        minutes_saved = sum(
            MANUAL_TIME_MINUTES.get(r[2], DEFAULT_MANUAL_MINUTES)
            for r in success_records
        )
        return self._build_summary(
            days, total_tasks, success_count, unique_users, avg_duration,
            daily_active_users, skill_distribution, top_users, minutes_saved,
        )

    @staticmethod
    def _build_summary(days, total_tasks, success_count, unique_users, avg_duration,
                       daily_active_users, skill_distribution, top_users, minutes_saved):
        success_rate = round(success_count / total_tasks * 100.0, 1) if total_tasks else 0.0
        return {
            "period_days": days,
            "generated_at": datetime.utcnow().isoformat(),
            "total_tasks": total_tasks,
            "success_count": success_count,
            "success_rate_percent": success_rate,
            "unique_users": unique_users,
            "daily_active_users": daily_active_users,
            "skill_distribution": skill_distribution,
            "top_users": top_users,
            "avg_duration_seconds": round(float(avg_duration), 2),
            "estimated_minutes_saved": minutes_saved,
            "estimated_hours_saved": round(minutes_saved / 60.0, 1),
            "estimate_basis": "成功任务数 x 各技能人工基准耗时(MANUAL_TIME_MINUTES, 可按业务校准)",
        }

    # ---------- 报告 ----------
    def generate_value_report(self, days=7):
        """生成 Markdown 业务价值报告"""
        s = self.get_summary(days=days)
        lines = [
            "# 电商运营 Agent 业务价值报告（近 %d 天）" % days,
            "",
            "> 生成时间: %s (UTC)" % s["generated_at"],
            "",
            "## 使用规模",
            "- 服务用户数: **%d**" % s["unique_users"],
            "- 完成任务数: **%d**（成功率 %.1f%%）" % (s["total_tasks"], s["success_rate_percent"]),
            "- 平均响应耗时: %.2f 秒" % s["avg_duration_seconds"],
            "",
            "## 效率收益（估算）",
            "- 累计节省人工: **约 %.1f 小时**（%.0f 分钟）" % (
                s["estimated_hours_saved"], s["estimated_minutes_saved"]),
            "- 口径: %s" % s["estimate_basis"],
            "",
            "## 技能使用分布",
        ]
        if s["skill_distribution"]:
            for skill, cnt in s["skill_distribution"].items():
                lines.append("- %s: %d 次" % (skill, cnt))
        else:
            lines.append("- 暂无数据")
        lines += ["", "## 活跃用户 Top 10"]
        if s["top_users"]:
            for idx, u in enumerate(s["top_users"], 1):
                lines.append("%d. %s — %d 次任务" % (idx, u["user_id"], u["tasks"]))
        else:
            lines.append("- 暂无数据")
        lines += ["", "## 每日活跃用户(DAU)"]
        if s["daily_active_users"]:
            for day, cnt in s["daily_active_users"].items():
                lines.append("- %s: %d 人" % (day, cnt))
        else:
            lines.append("- 暂无数据")
        return "\n".join(lines) + "\n"


# 全局单例
business_metrics = BusinessMetrics()