"""
Performance Profiler Module
===========================
High-resolution monotonic timer and performance profiler for the document
extraction and fusion pipeline.

Records stage durations per document and outputs structured diagnostics without
exposing sensitive student personal data (Aadhaar, names, addresses, API keys, etc.).
"""

import time
import threading
from contextlib import contextmanager
from typing import Dict, Any, List, Optional


class DocumentTimer:
    """High-resolution timer for an individual document's lifecycle."""

    def __init__(self, document_id: str, doc_type: str = "UNKNOWN"):
        self.document_id = document_id
        self.doc_type = doc_type
        self.start_time = time.perf_counter()
        self.end_time: Optional[float] = None
        self.stages: Dict[str, float] = {
            "validation_ms": 0.0,
            "preprocess_ms": 0.0,
            "ocr_ms": 0.0,
            "classification_ms": 0.0,
            "gemini_ms": 0.0,
            "gemini_queue_wait_ms": 0.0,
            "gemini_retry_wait_ms": 0.0,
            "json_parsing_ms": 0.0,
            "normalization_ms": 0.0,
            "canonicalization_ms": 0.0,
            "validation_engine_ms": 0.0,
        }

    @contextmanager
    def track(self, stage_name: str):
        """Context manager to measure elapsed milliseconds in a named stage."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            stage_key = f"{stage_name}_ms" if not stage_name.endswith("_ms") else stage_name
            self.stages[stage_key] = self.stages.get(stage_key, 0.0) + elapsed_ms

    def record(self, stage_name: str, elapsed_ms: float):
        """Directly record elapsed milliseconds for a stage."""
        stage_key = f"{stage_name}_ms" if not stage_name.endswith("_ms") else stage_name
        self.stages[stage_key] = self.stages.get(stage_key, 0.0) + elapsed_ms

    def finish(self) -> float:
        """Mark completion and compute total elapsed milliseconds."""
        self.end_time = time.perf_counter()
        return (self.end_time - self.start_time) * 1000.0

    @property
    def total_ms(self) -> float:
        end = self.end_time or time.perf_counter()
        return (end - self.start_time) * 1000.0

    @property
    def timings(self) -> Dict[str, float]:
        return self.stages

    def to_log_dict(self) -> Dict[str, Any]:
        """Output sanitized dictionary for logging."""
        d = {
            "document_id": self.document_id,
            "type": self.doc_type,
            "total_ms": round(self.total_ms, 2),
        }
        for k, v in self.stages.items():
            d[k] = round(v, 2)
        return d

    def print_log(self):
        """Print safe structured log matching specification."""
        print("\n[PERF]", flush=True)
        print(f"document_id={self.document_id}", flush=True)
        print(f"type={self.doc_type}", flush=True)
        for k, v in self.stages.items():
            print(f"{k}={round(v, 2)}", flush=True)
        print(f"total_ms={round(self.total_ms, 2)}\n", flush=True)


class PipelineProfiler:
    """
    Thread-safe batch pipeline performance profiler.
    Measures pipeline-level stages (merge, excel, overall) and collects DocumentTimers.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.batch_start_time = time.perf_counter()
        self.batch_end_time: Optional[float] = None
        self.document_timers: List[DocumentTimer] = []
        self.pipeline_stages: Dict[str, float] = {
            "merge_ms": 0.0,
            "excel_ms": 0.0,
            "smart_lookup_ms": 0.0,
        }

    def start_document(self, document_id: str, doc_type: str = "UNKNOWN") -> DocumentTimer:
        """Create and register a new document timer."""
        dt = DocumentTimer(document_id=document_id, doc_type=doc_type)
        with self._lock:
            self.document_timers.append(dt)
        return dt

    @contextmanager
    def track_pipeline(self, stage_name: str):
        """Context manager to measure pipeline-wide stages (e.g. merge, excel)."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            stage_key = f"{stage_name}_ms" if not stage_name.endswith("_ms") else stage_name
            with self._lock:
                self.pipeline_stages[stage_key] = self.pipeline_stages.get(stage_key, 0.0) + elapsed_ms

    def finish(self) -> float:
        self.batch_end_time = time.perf_counter()
        return (self.batch_end_time - self.batch_start_time) * 1000.0

    @property
    def total_batch_ms(self) -> float:
        end = self.batch_end_time or time.perf_counter()
        return (end - self.batch_start_time) * 1000.0

    def print_batch_summary(self):
        """Print detailed summary table showing exact bottleneck breakdown."""
        total_time_ms = self.total_batch_ms
        doc_count = len(self.document_timers)
        avg_doc_ms = (total_time_ms / doc_count) if doc_count > 0 else 0.0

        print("\n" + "=" * 90, flush=True)
        print("PIPELINE PERFORMANCE BENCHMARK REPORT", flush=True)
        print("=" * 90, flush=True)
        print(f"Total Batch Documents: {doc_count}", flush=True)
        print(f"Total Pipeline Time  : {round(total_time_ms, 2)} ms ({round(total_time_ms / 1000.0, 2)} s)", flush=True)
        print(f"Average Per Document : {round(avg_doc_ms, 2)} ms ({round(avg_doc_ms / 1000.0, 2)} s)", flush=True)
        print("-" * 90, flush=True)

        # Print per-document breakdown table
        print(f"{'DOCUMENT ID':<25} | {'TYPE':<12} | {'GEMINI (ms)':<12} | {'OCR (ms)':<10} | {'PREPROC (ms)':<12} | {'TOTAL (ms)':<10}", flush=True)
        print("-" * 90, flush=True)
        for dt in self.document_timers:
            g_ms = round(dt.stages.get("gemini_ms", 0.0), 1)
            o_ms = round(dt.stages.get("ocr_ms", 0.0), 1)
            p_ms = round(dt.stages.get("preprocess_ms", 0.0), 1)
            t_ms = round(dt.total_ms, 1)
            print(f"{dt.document_id[:24]:<25} | {dt.doc_type[:11]:<12} | {g_ms:<12} | {o_ms:<10} | {p_ms:<12} | {t_ms:<10}", flush=True)
        print("-" * 90, flush=True)

        # Aggregate stage totals
        stage_totals: Dict[str, float] = {}
        for dt in self.document_timers:
            for k, v in dt.stages.items():
                stage_totals[k] = stage_totals.get(k, 0.0) + v
        for k, v in self.pipeline_stages.items():
            stage_totals[k] = stage_totals.get(k, 0.0) + v

        print("STAGE AGGREGATE BREAKDOWN:", flush=True)
        sorted_stages = sorted(stage_totals.items(), key=lambda x: x[1], reverse=True)
        for stage, ms in sorted_stages:
            pct = (ms / total_time_ms * 100.0) if total_time_ms > 0 else 0.0
            print(f"  * {stage:<25}: {round(ms, 2):>8} ms ({pct:>5.1f}% of total)", flush=True)
        print("=" * 90 + "\n", flush=True)
