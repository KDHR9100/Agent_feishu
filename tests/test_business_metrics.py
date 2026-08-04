# -*- coding: utf-8 -*-
"""业务价值度量层 (app/monitoring/business.py) 与限流器 (app/utils/rate_limiter.py) 测试"""
import time

import pytest


@pytest.fixture
def metrics():
    """独立的 BusinessMetrics 实例; 测试前清空 business_task_logs 保证断言确定性"""
    from app.monitoring.business import BusinessMetrics

    m = BusinessMetrics()
    m._ensure_db()  # 确保 business_task_logs 表已创建
    if m._db_ok:
        from app.models.database import SessionLocal
        from app.models.models import BusinessTaskLog

        session = SessionLocal()
        try:
            session.query(BusinessTaskLog).delete()
            session.commit()
        finally:
            session.close()
    return m


class TestBusinessMetricsRecord:
    def test_record_and_summary_counts(self, metrics):
        metrics.record_task("user_a", "product_skill", success=True, duration_seconds=3.0)
        metrics.record_task("user_a", "ads_skill", success=True, duration_seconds=5.0)
        metrics.record_task("user_b", "content_skill", success=False, duration_seconds=2.0)

        s = metrics.get_summary(days=7)
        assert s["total_tasks"] == 3
        assert s["unique_users"] == 2
        assert s["success_count"] == 2
        assert s["success_rate_percent"] == pytest.approx(66.7, abs=0.1)
        assert s["period_days"] == 7
        assert s["avg_duration_seconds"] > 0

    def test_time_saved_counts_only_success_with_manual_baseline(self, metrics):
        # product_skill=15min, pricing_skill=45min; 失败任务不计入
        metrics.record_task("user_a", "product_skill", success=True)
        metrics.record_task("user_a", "pricing_skill", success=True)
        metrics.record_task("user_b", "report_skill", success=False)

        s = metrics.get_summary(days=7)
        assert s["estimated_minutes_saved"] == 60
        assert s["estimated_hours_saved"] == 1.0
        assert "MANUAL_TIME_MINUTES" in s["estimate_basis"]

    def test_daily_active_users_and_top_users(self, metrics):
        metrics.record_task("user_a", "rag_skill", success=True)
        metrics.record_task("user_a", "rag_skill", success=True)
        metrics.record_task("user_b", "seo_skill", success=True)

        s = metrics.get_summary(days=7)
        # 全部是今天的数据: DAU 只有一个日期, 2 个活跃用户
        assert len(s["daily_active_users"]) == 1
        assert list(s["daily_active_users"].values())[0] == 2
        # Top 用户按任务数降序
        assert s["top_users"][0]["user_id"] == "user_a"
        assert s["top_users"][0]["tasks"] == 2

    def test_skill_distribution(self, metrics):
        metrics.record_task("u1", "product_skill", success=True)
        metrics.record_task("u2", "product_skill", success=True)
        metrics.record_task("u3", "help_skill", success=True)

        s = metrics.get_summary(days=7)
        assert s["skill_distribution"]["product_skill"] == 2
        assert s["skill_distribution"]["help_skill"] == 1


class TestBusinessMetricsMemoryFallback:
    def test_memory_fallback_summary(self, metrics):
        # 模拟 DB 不可用: 强制走内存兜底路径
        metrics._db_checked = True
        metrics._db_ok = False

        metrics.record_task("user_x", "product_skill", success=True, duration_seconds=4.0)
        metrics.record_task("user_x", "product_skill", success=False)
        metrics.record_task("user_y", "report_skill", success=True)

        s = metrics.get_summary(days=7)
        assert s["total_tasks"] == 3
        assert s["unique_users"] == 2
        assert s["success_count"] == 2
        # 15(product) + 30(report) = 45 分钟
        assert s["estimated_minutes_saved"] == 45
        assert len(s["daily_active_users"]) == 1

    def test_generate_value_report_contains_key_sections(self, metrics):
        metrics.record_task("user_a", "product_skill", success=True)
        report = metrics.generate_value_report(days=7)
        assert "业务价值报告" in report
        assert "使用规模" in report
        assert "效率收益" in report
        assert "技能使用分布" in report
        assert "每日活跃用户" in report


class TestRateLimiter:
    def test_allows_within_limit_and_blocks_over(self):
        from app.utils.rate_limiter import RateLimiter

        rl = RateLimiter(max_requests=3, window_seconds=60)
        assert rl.allow("k") is True
        assert rl.allow("k") is True
        assert rl.allow("k") is True
        assert rl.allow("k") is False  # 第 4 次被限流
        # 不同 key 互不影响
        assert rl.allow("other") is True

    def test_remaining_and_reset(self):
        from app.utils.rate_limiter import RateLimiter

        rl = RateLimiter(max_requests=2, window_seconds=60)
        assert rl.remaining("k") == 2
        rl.allow("k")
        assert rl.remaining("k") == 1
        rl.reset("k")
        assert rl.remaining("k") == 2

    def test_window_expiry(self):
        from app.utils.rate_limiter import RateLimiter

        rl = RateLimiter(max_requests=2, window_seconds=1)
        assert rl.allow("k") is True
        assert rl.allow("k") is True
        assert rl.allow("k") is False
        time.sleep(1.1)  # 等待窗口滑过
        assert rl.allow("k") is True

    def test_default_limit_from_env(self):
        import os
        from app.utils import rate_limiter as rl_module

        os.environ["RATE_LIMIT_PER_MINUTE"] = "5"
        try:
            rl = rl_module.RateLimiter()
            assert rl.max_requests == 5
        finally:
            del os.environ["RATE_LIMIT_PER_MINUTE"]

    def test_invalid_limit_env_fallback(self):
        # 非法/越界配置不应导致启动崩溃, 回退默认值并夹取下限
        import os
        from app.utils import rate_limiter as rl_module

        os.environ["RATE_LIMIT_PER_MINUTE"] = "not_a_number"
        try:
            assert rl_module._get_limit() == rl_module.DEFAULT_LIMIT
        finally:
            del os.environ["RATE_LIMIT_PER_MINUTE"]
        os.environ["RATE_LIMIT_PER_MINUTE"] = "0"
        try:
            assert rl_module._get_limit() == 1
        finally:
            del os.environ["RATE_LIMIT_PER_MINUTE"]

    def test_expired_keys_pruned(self):
        # 完全过期的键应被定期清扫, 防止 _hits 无界增长
        from app.utils.rate_limiter import RateLimiter

        rl = RateLimiter(max_requests=2, window_seconds=1)
        rl.allow("gone")
        time.sleep(1.1)
        for _ in range(RateLimiter._PRUNE_EVERY):
            rl.allow("active")
        assert "gone" not in rl._hits

    def test_chat_rate_identity_ignores_body_fields(self):
        # 限流身份只取决于凭据: 轮换 user_id/conversation_id 不能绕过限流
        from app.main import _rate_limit_identity

        a = _rate_limit_identity("secret", "conv1")
        b = _rate_limit_identity("secret", "conv2")
        assert a == b
        assert _rate_limit_identity("other_key", "conv1") != a
        assert _rate_limit_identity(None, "conv1").startswith("conv:")