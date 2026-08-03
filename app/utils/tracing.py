"""OpenTelemetry 链路追踪工具 - 优雅降级(未安装时为 no-op)"""
import functools
import logging

logger = logging.getLogger("tracing")

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource

    _tracer = None

    def init_tracing(service_name: str = "ecommerce-agent"):
        """初始化 OpenTelemetry TracerProvider"""
        global _tracer
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        # 尝试配置 OTLP 导出器(可选)
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            import os
            otlp_endpoint = os.getenv("OTLP_ENDPOINT", "http://localhost:4317")
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("[tracing] OTLP exporter configured: %s", otlp_endpoint)
        except Exception as e:
            logger.info("[tracing] OTLP exporter not available, using console: %s", e)

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        logger.info("[tracing] OpenTelemetry initialized for %s", service_name)

    def get_tracer():
        global _tracer
        if _tracer is None:
            init_tracing()
        return _tracer

    def trace_node(node_name: str):
        """装饰器: 为工作流节点添加 trace span"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                tracer = get_tracer()
                with tracer.start_as_current_span(node_name) as span:
                    try:
                        result = func(*args, **kwargs)
                        span.set_status(trace.StatusCode.OK)
                        return result
                    except Exception as e:
                        span.set_status(trace.StatusCode.ERROR, str(e))
                        span.record_exception(e)
                        raise
            return wrapper
        return decorator

    OTEL_AVAILABLE = True

except ImportError:
    OTEL_AVAILABLE = False
    logger.info("[tracing] opentelemetry not installed, tracing disabled")

    def init_tracing(service_name: str = "ecommerce-agent"):
        pass

    def get_tracer():
        return None

    def trace_node(node_name: str):
        """No-op 装饰器"""
        def decorator(func):
            return func
        return decorator