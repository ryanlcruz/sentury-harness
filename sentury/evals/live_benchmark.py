"""Benchmark local-first de provedores/modelos para fases de qualidade.

Foco desta primeira fatia:
- comparar candidatos relevantes para Sentury por perfil de tarefa
- preferir Groq e OpenRouter por padrão
- deixar Gemini como opt-in para não queimar a cota da live sem necessidade

O runner é deliberadamente pequeno: ele monta poucos casos, escolhe um modelo por
provider/profile e produz um relatório legível em Markdown.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ..config import Settings, settings
from robinbandit import RobinConfig
from robinbandit.providers import build_provider
from robinbandit.profiles import resolve_profile_models

DEFAULT_BENCHMARK_PROFILES: tuple[str, ...] = ("analysis", "artifact", "coding")
DEFAULT_BENCHMARK_PROVIDERS: tuple[str, ...] = ("groq", "openrouter")

_PROFILE_MODEL_HINTS: Dict[str, tuple[str, ...]] = {
    "analysis": ("gpt-oss", "qwen3-32b", "qwen-3-32b", "70b", "flash"),
    "artifact": ("gpt-oss", "70b", "llama-3.3", "mistral", "flash"),
    "coding": ("antigravity", "coder", "qwen3-coder", "deepseek", "gpt-oss"),
}


@dataclass(frozen=True)
class BenchmarkTarget:
    profile: str
    provider: str
    model: str


@dataclass(frozen=True)
class BenchmarkCase:
    key: str
    profile: str
    title: str
    prompt: str
    complexity: str = "CRITICAL"


@dataclass(frozen=True)
class BenchmarkResult:
    profile: str
    provider: str
    model: str
    case_key: str
    case_title: str
    latency_ms: float
    ok: bool
    response_text: str = ""
    error: Optional[str] = None


DEFAULT_BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        key="nps_exec",
        profile="analysis",
        title="Leitura executiva de NPS",
        prompt=(
            "Como está o NPS geral? Resuma em poucas linhas, destaque o principal risco "
            "operacional e proponha a próxima ação mais útil para um time de CX."
        ),
    ),
    BenchmarkCase(
        key="tickets_priority",
        profile="analysis",
        title="Priorização de tickets e leads",
        prompt=(
            "Cruze tickets, leads e queda de NPS e me diga o que precisa ser atacado "
            "primeiro sem enrolação."
        ),
    ),
    BenchmarkCase(
        key="dashboard_choice",
        profile="artifact",
        title="Escolha do melhor entregável visual",
        prompt=(
            "Tenho NPS, NPS, CSAT e tickets por região. Qual é o melhor entregável para "
            "um gestor: dashboard, tabela, gráfico ou relatório? Explique e proponha a estrutura."
        ),
    ),
    BenchmarkCase(
        key="chart_strategy",
        profile="artifact",
        title="Estratégia de visualização",
        prompt=(
            "Quero mostrar deterioração do NPS por mês e por unidade. Diga qual gráfico "
            "usar, quais eixos, agregação e como evitar uma visualização ruim."
        ),
    ),
    BenchmarkCase(
        key="sql_cross",
        profile="coding",
        title="SQL de cruzamento CX/Ops",
        prompt=(
            "Escreva uma query SQL para cruzar a pesquisa de satisfação com tickets por unidade e mês, "
            "mostrando NPS médio, volume e taxa de detratores."
        ),
        complexity="COMPLEX",
    ),
    BenchmarkCase(
        key="python_export",
        profile="coding",
        title="Script de exportação operacional",
        prompt=(
            "Escreva um script Python curto que leia um CSV de respostas, agregue NPS por "
            "região e gere uma tabela pronta para exportação."
        ),
        complexity="COMPLEX",
    ),
)


def _robin_config(cfg: Settings) -> RobinConfig:
    path = Path(cfg.SENTURY_ROBINBANDIT_CONFIG)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return RobinConfig.from_yaml(path)


def _provider_has_key(cfg: Settings, provider: str) -> bool:
    return build_provider(_robin_config(cfg), provider, cfg) is not None


def _provider_models(cfg: Settings, provider: str, profile: str) -> List[str]:
    config = _robin_config(cfg)
    spec = config.providers.get(provider) or {}
    role = "planner" if provider == "groq" and profile in {
        "analysis", "artifact", "coding"
    } else None
    env_name = str(spec.get(f"{role}_models_env" if role else "models_env") or "")
    overridden = [
        item.strip() for item in str(getattr(cfg, env_name, "") or "").split(",")
        if item.strip()
    ]
    return overridden or config.provider_models(provider, role)


def _heuristic_model_for_profile(models: Sequence[str], profile: str) -> Optional[str]:
    if not models:
        return None
    lowered = [(model, model.lower()) for model in models]
    for hint in _PROFILE_MODEL_HINTS.get(profile, ()):
        for model, normalized in lowered:
            if hint in normalized:
                return model
    return models[0]


def select_benchmark_model(cfg: Settings, provider: str, profile: str) -> Optional[str]:
    """Escolhe um modelo enxuto para o benchmark daquele provider/profile.

    Ordem:
    1. preferência explícita do profile gateway (ex.: coding+gemini -> antigravity)
    2. heurística baseada na lista configurada do provider
    """
    config = _robin_config(cfg)
    resolved_profiles = resolve_profile_models(cfg, config.profiles)
    for item in resolved_profiles.get(profile, []):
        if item["provider"] == provider:
            return item["model"]
    return _heuristic_model_for_profile(_provider_models(cfg, provider, profile), profile)


def build_benchmark_targets(
    cfg: Settings,
    *,
    profiles: Sequence[str] = DEFAULT_BENCHMARK_PROFILES,
    allowed_providers: Optional[Sequence[str]] = None,
    include_gemini: bool = False,
) -> List[BenchmarkTarget]:
    allowed = {item.strip().lower() for item in (allowed_providers or DEFAULT_BENCHMARK_PROVIDERS) if item.strip()}
    if include_gemini:
        allowed.add("gemini")
    else:
        allowed.discard("gemini")

    targets: List[BenchmarkTarget] = []
    seen = set()
    for profile in profiles:
        normalized_profile = str(profile).strip().lower()
        for provider in sorted(allowed):
            if not _provider_has_key(cfg, provider):
                continue
            model = select_benchmark_model(cfg, provider, normalized_profile)
            if not model:
                continue
            key = (normalized_profile, provider, model)
            if key in seen:
                continue
            seen.add(key)
            targets.append(BenchmarkTarget(*key))
    return targets


def build_case_pack(
    *,
    profiles: Sequence[str] = DEFAULT_BENCHMARK_PROFILES,
    max_cases_per_profile: int = 1,
) -> List[BenchmarkCase]:
    selected = {str(profile).strip().lower() for profile in profiles}
    per_profile: Dict[str, int] = {}
    cases: List[BenchmarkCase] = []
    for case in DEFAULT_BENCHMARK_CASES:
        if case.profile not in selected:
            continue
        used = per_profile.get(case.profile, 0)
        if used >= max_cases_per_profile:
            continue
        cases.append(case)
        per_profile[case.profile] = used + 1
    return cases


def _instantiate_provider(cfg: Settings, provider: str, model: str):
    instance = build_provider(_robin_config(cfg), provider, cfg, models=[model])
    if instance is None:
        raise ValueError(f"provider de benchmark não configurado: {provider}")
    return instance


async def _call_provider(provider, messages: List[Dict[str, str]], case: BenchmarkCase, model: str) -> str:
    try:
        return await provider.complete(
            messages,
            temperature=0.2,
            complexity=case.complexity,
            preferred_model=model,
        )
    except TypeError:
        try:
            return await provider.complete(messages, temperature=0.2, complexity=case.complexity)
        except TypeError:
            return await provider.complete(messages, temperature=0.2)


async def run_live_benchmark(
    cfg: Settings,
    *,
    profiles: Sequence[str] = DEFAULT_BENCHMARK_PROFILES,
    allowed_providers: Optional[Sequence[str]] = None,
    include_gemini: bool = False,
    max_cases_per_profile: int = 1,
) -> List[BenchmarkResult]:
    targets = build_benchmark_targets(
        cfg,
        profiles=profiles,
        allowed_providers=allowed_providers,
        include_gemini=include_gemini,
    )
    cases = build_case_pack(profiles=profiles, max_cases_per_profile=max_cases_per_profile)
    case_map: Dict[str, List[BenchmarkCase]] = {}
    for case in cases:
        case_map.setdefault(case.profile, []).append(case)

    results: List[BenchmarkResult] = []
    system_prompt = (
        "Você está participando de um benchmark do Sentury. Responda de forma útil, "
        "concreta e curta. Evite prefácio, não invente dados e escolha o melhor "
        "entregável quando a pergunta pedir um formato."
    )
    for target in targets:
        provider = _instantiate_provider(cfg, target.provider, target.model)
        for case in case_map.get(target.profile, []):
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": case.prompt},
            ]
            started = time.perf_counter()
            try:
                response_text = await _call_provider(provider, messages, case, target.model)
                elapsed = (time.perf_counter() - started) * 1000.0
                results.append(
                    BenchmarkResult(
                        profile=target.profile,
                        provider=target.provider,
                        model=target.model,
                        case_key=case.key,
                        case_title=case.title,
                        latency_ms=elapsed,
                        ok=bool((response_text or "").strip()),
                        response_text=(response_text or "").strip(),
                    )
                )
            except Exception as exc:
                elapsed = (time.perf_counter() - started) * 1000.0
                results.append(
                    BenchmarkResult(
                        profile=target.profile,
                        provider=target.provider,
                        model=target.model,
                        case_key=case.key,
                        case_title=case.title,
                        latency_ms=elapsed,
                        ok=False,
                        error=str(exc)[:240],
                    )
                )
    return results


def render_benchmark_report(results: Iterable[BenchmarkResult]) -> str:
    rows = list(results)

    strengths = [
        (
            f"- `{row.provider}:{row.model}` foi bem em `{row.profile}` no caso "
            f"`{row.case_title}` ({row.latency_ms:.0f} ms)."
        )
        for row in rows
        if row.ok
    ]
    weaknesses = [
        (
            f"- `{row.provider}:{row.model}` falhou em `{row.case_title}`: "
            f"{row.error or 'resposta vazia'}."
        )
        for row in rows
        if not row.ok
    ]

    winners: Dict[str, BenchmarkResult] = {}
    for row in rows:
        if not row.ok:
            continue
        current = winners.get(row.profile)
        if current is None or row.latency_ms < current.latency_ms:
            winners[row.profile] = row

    adoption = [
        (
            f"- Em `{profile}`, o melhor candidato desta rodada foi "
            f"`{row.provider}:{row.model}` para `{row.case_title}`."
        )
        for profile, row in sorted(winners.items())
    ]

    use_cases = []
    seen_use_case_profiles = set()
    for row in rows:
        if not row.ok:
            continue
        key = (row.profile, row.case_title)
        if key in seen_use_case_profiles:
            continue
        seen_use_case_profiles.add(key)
        use_cases.append(
            f"- `{row.case_title}` pode virar um fluxo forte do Sentury em `{row.profile}`."
        )

    if not strengths:
        strengths = ["- Ainda não há sucessos registrados nesta rodada."]
    if not weaknesses:
        weaknesses = [
            "- Nenhuma falha apareceu nesta rodada curta; o risco principal continua sendo depender de um único provider."
        ]
    if not adoption:
        adoption = [
            "- Ainda não há recomendação fechada porque esta rodada não teve respostas válidas suficientes."
        ]
    if not use_cases:
        use_cases = [
            "- Use o benchmark para decidir qual provider deve puxar análise, artefatos visuais e tarefas de código."
        ]

    report_lines = [
        "# Sentury Live Benchmark",
        "",
        "## Strengths",
        *strengths,
        "",
        "## Weaknesses",
        *weaknesses,
        "",
        "## Adoption Recommendation",
        *adoption,
        "",
        "## Do Not Copy",
        "- Não transforme benchmark em dependência cega de um único provider.",
        "- Não inclua Gemini no caminho padrão desta rodada sem necessidade real de comparação.",
        "- Não aumente o pack de casos antes de confirmar que o recorte atual já responde o que queremos aprender.",
        "",
        "## Sentury Use Case",
        *use_cases,
        "",
    ]
    return "\n".join(report_lines)


def _parse_csv(raw: str) -> List[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roda benchmark local-first de providers do Sentury.")
    parser.add_argument("--profiles", default="analysis,artifact,coding")
    parser.add_argument("--providers", default="groq,openrouter")
    parser.add_argument("--include-gemini", action="store_true")
    parser.add_argument("--max-cases-per-profile", type=int, default=1)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--md-out", default="")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    profiles = _parse_csv(args.profiles) or list(DEFAULT_BENCHMARK_PROFILES)
    providers = _parse_csv(args.providers) or list(DEFAULT_BENCHMARK_PROVIDERS)

    results = asyncio.run(
        run_live_benchmark(
            settings,
            profiles=profiles,
            allowed_providers=providers,
            include_gemini=bool(args.include_gemini),
            max_cases_per_profile=int(args.max_cases_per_profile),
        )
    )
    report = render_benchmark_report(results)
    print(report)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.md_out:
        Path(args.md_out).write_text(report, encoding="utf-8")
    return 0 if any(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
