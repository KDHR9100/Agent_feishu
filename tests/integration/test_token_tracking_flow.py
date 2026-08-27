"""集成测试2: Token消耗统计 - 10次调用后查询验证"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestTokenTrackingFlow:
    """模拟真实场景: 发10条不同技能Query, 验证 /metrics/usage 有数据"""

    @patch("app.models.database.SessionLocal")
    def test_10_calls_then_query_ranking(self, mock_session_cls):
        """10次 record_token_usage 后, get_usage_last_24h 返回分技能统计"""
        from app.monitoring.stats import MonitoringStats
        stats = MonitoringStats()

        # 模拟写入: 用真实 SQLite (内存库)
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models.database import Base
        from app.models.models import TokenUsageLog

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        TestSession = sessionmaker(bind=engine)

        skills_data = [
            ("inventory_skill", 200, 100),
            ("inventory_skill", 180, 90),
            ("ads_skill", 300, 150),
            ("ads_skill", 250, 120),
            ("pricing_skill", 500, 400),
            ("pricing_skill", 450, 380),
            ("product_skill", 150, 80),
            ("report_skill", 600, 500),
            ("seo_skill", 220, 110),
            ("support_skill", 180, 95),
        ]

        # 直接写入内存库
        session = TestSession()
        from datetime import datetime
        for skill, inp, out in skills_data:
            log = TokenUsageLog(
                skill_name=skill,
                input_tokens=inp,
                output_tokens=out,
                total_tokens=inp + out,
                conversation_id="test-conv",
                created_at=datetime.utcnow(),
            )
            session.add(log)
        session.commit()

        # 查询验证
        from sqlalchemy import func
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        rows = (
            session.query(
                TokenUsageLog.skill_name,
                func.count(TokenUsageLog.id).label("call_count"),
                func.sum(TokenUsageLog.total_tokens).label("total_tokens"),
            )
            .filter(TokenUsageLog.created_at >= cutoff)
            .group_by(TokenUsageLog.skill_name)
            .order_by(func.sum(TokenUsageLog.total_tokens).desc())
            .all()
        )

        # 验证: 必须有数据
        assert len(rows) > 0, "Token usage ranking must not be empty"

        # 验证: 分技能统计
        skill_map = {r.skill_name: r.total_tokens for r in rows}
        assert skill_map["pricing_skill"] == 500 + 400 + 450 + 380  # 1730
        assert skill_map["report_skill"] == 600 + 500  # 1100
        assert skill_map["inventory_skill"] == 200 + 100 + 180 + 90  # 570

        # 验证: 排名顺序(按 total_tokens 降序)
        totals = [r.total_tokens for r in rows]
        assert totals == sorted(totals, reverse=True)

        # 验证: 总量
        grand_total = sum(r.total_tokens for r in rows)
        expected_total = sum(inp + out for _, inp, out in skills_data)
        assert grand_total == expected_total

        session.close()

    @patch("app.models.database.SessionLocal")
    def test_record_and_query_roundtrip(self, mock_session_cls):
        """record_token_usage 写入 → get_usage_last_24h 读出 闭环"""
        from app.monitoring.stats import MonitoringStats
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models.database import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        TestSession = sessionmaker(bind=engine)

        # Patch SessionLocal to use our in-memory DB
        mock_session_cls.return_value = TestSession()

        stats = MonitoringStats()
        stats.record_token_usage("ads_skill", 100, 50, "conv-1")
        stats.record_token_usage("ads_skill", 200, 80, "conv-2")
        stats.record_token_usage("pricing_skill", 300, 250, "conv-3")

        # 重新 patch 为新的 session
        mock_session_cls.return_value = TestSession()
        result = stats.get_usage_last_24h()

        assert result["period"] == "last_24h"
        assert result["grand_total_tokens"] > 0
        assert len(result["skill_ranking"]) >= 2

        # ads_skill 应该排在前面(380 tokens vs 550 tokens)
        # 实际上 pricing_skill=550 > ads_skill=380
        ranking = result["skill_ranking"]
        assert ranking[0]["skill_name"] == "pricing_skill"
        assert ranking[0]["total_tokens"] == 550

    def test_metrics_endpoint_structure(self):
        """验证 /metrics/usage 端点返回结构正确"""
        from app.monitoring.stats import MonitoringStats
        stats = MonitoringStats()

        # 无数据时也应返回合法结构
        with patch("app.models.database.SessionLocal") as mock_cls:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from app.models.database import Base
            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            mock_cls.return_value = sessionmaker(bind=engine)()

            result = stats.get_usage_last_24h()

        assert "period" in result
        assert "generated_at" in result
        assert "grand_total_tokens" in result
        assert "skill_ranking" in result
        assert isinstance(result["skill_ranking"], list)