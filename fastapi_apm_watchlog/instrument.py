# fastapi_watchlog_apm/instrument.py

import os
import dns.resolver
from datetime import datetime

import requests
from google.protobuf.json_format import MessageToDict
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, sampling
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter, Compression
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource

def _is_running_in_k8s() -> bool:
    # same k8s detection you already have
    if os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'):
        return True
    try:
        with open('/proc/1/cgroup') as f:
            if 'kubepods' in f.read():
                return True
    except:
        pass
    try:
        dns.resolver.resolve('kubernetes.default.svc.cluster.local', 'A')
        return True
    except:
        return False

def _detect_endpoint(default: str, user_provided_url: str = None) -> str:
    # If user explicitly provided a URL (different from default), use it directly (skip auto-detection)
    if user_provided_url:
        return user_provided_url
    # Otherwise, use auto-detection
    return (
        'http://watchlog-python-agent.monitoring.svc.cluster.local:3774/apm'
        if _is_running_in_k8s()
        else default
    )

class OTLPJsonSpanExporter(SpanExporter):
    def __init__(self, endpoint: str, headers: dict):
        # We'll still leverage the normal proto exporter for its headers+endpoint logic
        self._endpoint = endpoint
        self._headers = dict(headers or {})
        # enforce JSON
        self._headers['Content-Type'] = 'application/json'

    def export(self, spans) -> SpanExportResult:
        try:
            proto_req = encode_spans(spans)

            body = MessageToDict(
                proto_req,
                preserving_proto_field_name=False,
                including_default_value_fields=False
            )

            # Normalize status.code values (string -> int)
            STATUS_CODE_MAP = {
                "STATUS_CODE_UNSET": 0,
                "STATUS_CODE_OK": 1,
                "STATUS_CODE_ERROR": 2
            }

            for rs in body.get("resourceSpans", []):
                if "scopeSpans" in rs:
                    rs["instrumentationLibrarySpans"] = rs.pop("scopeSpans")
                for ils in rs.get("instrumentationLibrarySpans", []):
                    for span in ils.get("spans", []):
                        code = span.get("status", {}).get("code")
                        if isinstance(code, str) and code in STATUS_CODE_MAP:
                            span["status"]["code"] = STATUS_CODE_MAP[code]

            resp = requests.post(self._endpoint, json=body, headers=self._headers, timeout=5)
            resp.raise_for_status()
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE
    
    def shutdown(self):
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

def instrument(
    app,
    *,
    service_name: str,
    otlp_endpoint: str = 'http://localhost:3774/apm',
    headers: dict = None,
    batch_max_size: int = 200,
    batch_delay_ms: int = 5000,
    sample_rate: float = 1.0,
    send_error_spans: bool = False,
    error_tps: int = None,
    slow_threshold_ms: int = 0,
):
    """
    Initialize Watchlog APM for FastAPI — JSON-over-HTTP spans identical
    to your Node SDK’s output.
    """
    headers = headers or {}
    rate = min(sample_rate, 0.3)
    # Priority: 1) otlp_endpoint option (if different from default), 2) auto-detection
    default_endpoint = 'http://localhost:3774/apm'
    # If user provided otlp_endpoint explicitly (different from default), use it (skip auto-detection)
    # Otherwise, use auto-detection
    user_url = otlp_endpoint if otlp_endpoint != default_endpoint else None
    base = _detect_endpoint(default_endpoint, user_url)

    # 1) TracerProvider + ParentBased Ratio sampler
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(
        resource=resource,
        sampler=sampling.ParentBased(sampling.TraceIdRatioBased(rate))
    )
    trace.set_tracer_provider(provider)

    # 2) Determine final URL
    url = f"{base}/{service_name}/v1/traces"

    # 3) Wrap into our JSON exporter
    json_exporter = OTLPJsonSpanExporter(url, headers)

    # 4) Optional error/speed filters
    last_sec = int(datetime.utcnow().timestamp())
    err_count = 0
    def _filter(span):
        nonlocal last_sec, err_count
        now = int(datetime.utcnow().timestamp())
        if now != last_sec:
            last_sec, err_count = now, 0
        # error spans
        if send_error_spans and span.status.status_code.value != 0:
            if error_tps is None or err_count < error_tps:
                err_count += 1
                return True
            return False
        # slow spans
        if slow_threshold_ms > 0 and span.start_time and span.end_time:
            dur_ms = (span.end_time - span.start_time) / 1e6
            if dur_ms > slow_threshold_ms:
                return True
        # sampling
        if rate < 1.0:
            from random import random
            return random() < rate
        return True

    # 5) Install the processor
    bsp = BatchSpanProcessor(json_exporter,
        max_export_batch_size=batch_max_size,
        schedule_delay_millis=batch_delay_ms
    )
    if send_error_spans or slow_threshold_ms > 0 or rate < 1.0:
        # wrap to filter
        class _FilteringProcessor(BatchSpanProcessor):
            def __init__(self, exporter, fn, **kw):
                super().__init__(exporter, **kw)
                self._fn = fn
            def on_end(self, span):
                if self._fn(span):
                    super().on_end(span)
        proc = _FilteringProcessor(
            json_exporter,
            _filter,
            max_export_batch_size=batch_max_size,
            schedule_delay_millis=batch_delay_ms
        )
    else:
        proc = bsp
    provider.add_span_processor(proc)

    # 6) Auto-instrument FastAPI & HTTP
    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()

    return app
