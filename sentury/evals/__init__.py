from .golden import EvalResult, run_golden_evals

__all__ = [
    "BenchmarkCase",
    "BenchmarkResult",
    "BenchmarkTarget",
    "EvalResult",
    "build_benchmark_targets",
    "build_case_pack",
    "render_benchmark_report",
    "run_golden_evals",
    "run_live_benchmark",
]


def __getattr__(name):
    if name in {
        "BenchmarkCase",
        "BenchmarkResult",
        "BenchmarkTarget",
        "build_benchmark_targets",
        "build_case_pack",
        "render_benchmark_report",
        "run_live_benchmark",
    }:
        from . import live_benchmark as _live_benchmark

        return getattr(_live_benchmark, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
