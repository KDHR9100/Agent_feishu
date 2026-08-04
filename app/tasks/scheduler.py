import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


logger = logging.getLogger("app.tasks")


class TaskScheduler:
    """基于 APScheduler 的定时任务调度器"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self._registered_tasks = {}

    def start(self):
        if self.scheduler.running:
            logger.warning("Scheduler already running")
            return

        self._register_tasks()
        self.scheduler.start()
        logger.info("TaskScheduler started with %d tasks", len(self._registered_tasks))

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("TaskScheduler stopped")

    def _register_tasks(self):
        self._add_task(
            job_id="inventory_check",
            func=self._run_inventory_check,
            trigger=IntervalTrigger(hours=4),
            name="库存预警检查",
        )

        self._add_task(
            job_id="daily_report",
            func=self._run_daily_report,
            trigger=CronTrigger(hour=9, minute=0),
            name="每日运营日报生成",
        )

        self._add_task(
            job_id="weekly_business_report",
            func=self._run_weekly_business_report,
            trigger=CronTrigger(day_of_week="mon", hour=9, minute=30),
            name="每周业务价值报告",
        )

    def _add_task(self, job_id, func, trigger, name):
        self.scheduler.add_job(func, trigger=trigger, id=job_id, name=name)
        self._registered_tasks[job_id] = name
        logger.info("Registered task: %s (%s)", job_id, name)

    def get_status(self):
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            })
        return {
            "running": self.scheduler.running,
            "task_count": len(jobs),
            "tasks": jobs,
        }

    def _run_inventory_check(self):
        logger.info("Running scheduled task: inventory_check")
        try:
            from app.tools.database_tool import db_tool

            products = db_tool.get_all_products()
            low_stock = []
            for p in products:
                sku = p.get("sku", "")
                sales = db_tool.get_product_sales(sku=sku, days=1)
                if sales:
                    for s in sales:
                        inventory = s.get("inventory", 0)
                        sales_volume = s.get("sales_volume", 0)
                        if inventory > 0 and inventory < sales_volume * 2:
                            low_stock.append({
                                "sku": sku,
                                "product_name": s.get("product_name", ""),
                                "inventory": inventory,
                                "daily_sales": sales_volume,
                            })

            if low_stock:
                logger.warning("Inventory alert: %d products low on stock", len(low_stock))
                for item in low_stock:
                    logger.warning(
                        "  %s (%s): inventory=%d, daily_sales=%d",
                        item["sku"],
                        item["product_name"],
                        item["inventory"],
                        item["daily_sales"],
                    )
            else:
                logger.info("Inventory check passed: all products well-stocked")
        except Exception as e:
            logger.error("Inventory check failed: %s", str(e), exc_info=True)

    def _run_daily_report(self):
        logger.info("Running scheduled task: daily_report")
        try:
            from app.tools.database_tool import db_tool

            products = db_tool.get_product_sales(days=1)
            ads = db_tool.get_ads_performance(days=1)

            total_revenue = sum(p.get("revenue", 0) for p in products if "revenue" in p)
            total_ad_spend = sum(a.get("spend", 0) for a in ads if "spend" in a)
            total_ad_conversions = sum(
                a.get("conversions", 0) for a in ads if "conversions" in a
            )

            logger.info(
                "Daily report: revenue=%.2f, ad_spend=%.2f, ad_conversions=%d",
                total_revenue,
                total_ad_spend,
                total_ad_conversions,
            )
        except Exception as e:
            logger.error("Daily report generation failed: %s", str(e), exc_info=True)

    def _run_weekly_business_report(self):
        """每周业务价值报告: 汇总活跃用户/任务量/节省工时, 落盘 data/reports/"""
        logger.info("Running scheduled task: weekly_business_report")
        try:
            from datetime import datetime as _dt

            from app.monitoring.business import business_metrics
            from app.tools.file_tool import file_tool

            report = business_metrics.generate_value_report(days=7)
            file_name = "reports/business_value_report_%s.md" % _dt.now().strftime("%Y%m%d")
            write_result = file_tool.write_file(file_name, report)
            if write_result.get("error"):
                logger.error("Weekly business report save failed: %s", write_result.get("error"))
            else:
                logger.info("Weekly business value report saved: data/%s", file_name)
        except Exception as e:
            logger.error("Weekly business report generation failed: %s", str(e), exc_info=True)


task_scheduler = TaskScheduler()
