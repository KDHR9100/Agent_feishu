"""Tests for TaskScheduler"""
import pytest
from unittest.mock import patch, MagicMock


class TestTaskScheduler:
    def test_scheduler_init(self):
        from app.tasks.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        assert scheduler is not None
        assert not scheduler.scheduler.running

    def test_scheduler_start_stop(self):
        from app.tasks.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        scheduler.start()
        assert scheduler.scheduler.running
        assert scheduler.get_status()["running"] is True
        scheduler.stop()
        assert not scheduler.scheduler.running

    def test_registered_tasks(self):
        from app.tasks.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        scheduler.start()
        status = scheduler.get_status()
        assert status["task_count"] == 4
        task_ids = [t["id"] for t in status["tasks"]]
        assert "inventory_check" in task_ids
        assert "daily_report" in task_ids
        assert "weekly_business_report" in task_ids
        assert "log_retention_cleanup" in task_ids
        scheduler.stop()

    def test_get_status_structure(self):
        from app.tasks.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        status = scheduler.get_status()
        assert "running" in status
        assert "task_count" in status
        assert "tasks" in status
        assert isinstance(status["tasks"], list)

    def test_inventory_check_safe(self):
        from app.tasks.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        with patch("app.tools.database_tool.db_tool") as mock_db:
            mock_db.get_all_products.return_value = []
            scheduler._run_inventory_check()

    def test_daily_report_safe(self):
        from app.tasks.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        with patch("app.tools.database_tool.db_tool") as mock_db:
            mock_db.get_product_sales.return_value = []
            mock_db.get_ads_performance.return_value = []
            scheduler._run_daily_report()

    def test_double_start_safe(self):
        from app.tasks.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        scheduler.start()
        scheduler.start()
        assert scheduler.scheduler.running
        scheduler.stop()

    def test_task_has_next_run_time(self):
        from app.tasks.scheduler import TaskScheduler
        scheduler = TaskScheduler()
        scheduler.start()
        status = scheduler.get_status()
        for task in status["tasks"]:
            assert task["next_run_time"] is not None
            assert task["next_run_time"] != "None"
        scheduler.stop()
