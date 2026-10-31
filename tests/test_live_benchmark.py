from sentury.config import Settings


def test_build_benchmark_targets_prefere_groq_e_openrouter_por_padrao(monkeypatch):
    from sentury.evals.live_benchmark import build_benchmark_targets

    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    cfg = Settings(_env_file=None)
    targets = build_benchmark_targets(cfg)

    assert targets
    assert {target.provider for target in targets} == {"groq", "openrouter"}
    assert {target.profile for target in targets} == {"analysis", "artifact", "coding"}


def test_build_benchmark_targets_so_inclui_gemini_quando_opt_in(monkeypatch):
    from sentury.evals.live_benchmark import build_benchmark_targets

    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    cfg = Settings(_env_file=None)
    targets = build_benchmark_targets(cfg, profiles=("coding",), include_gemini=True)

    assert any(
        target.provider == "gemini" and target.model == "antigravity-preview-05-2026"
        for target in targets
    )


def test_build_benchmark_targets_ignora_provider_sem_chave(monkeypatch):
    from sentury.evals.live_benchmark import build_benchmark_targets

    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cfg = Settings(_env_file=None)
    targets = build_benchmark_targets(cfg)

    assert targets
    assert {target.provider for target in targets} == {"groq"}


def test_build_case_pack_limita_casos_por_perfil():
    from sentury.evals.live_benchmark import build_case_pack

    cases = build_case_pack(profiles=("analysis", "artifact", "coding"), max_cases_per_profile=1)

    assert len(cases) == 3
    assert {case.profile for case in cases} == {"analysis", "artifact", "coding"}


def test_render_benchmark_report_tem_secoes_obrigatorias():
    from sentury.evals.live_benchmark import BenchmarkResult, render_benchmark_report

    report = render_benchmark_report(
        [
            BenchmarkResult(
                profile="analysis",
                provider="groq",
                model="openai/gpt-oss-120b",
                case_key="nps_exec",
                case_title="Leitura executiva de NPS",
                latency_ms=812.4,
                ok=True,
                response_text="O NPS caiu 6,2 pontos e pede acao imediata.",
            )
        ]
    )

    assert "## Strengths" in report
    assert "## Weaknesses" in report
    assert "## Adoption Recommendation" in report
    assert "## Do Not Copy" in report
    assert "## Sentury Use Case" in report


def test_render_benchmark_report_nao_duplica_use_case_do_mesmo_perfil():
    from sentury.evals.live_benchmark import BenchmarkResult, render_benchmark_report

    report = render_benchmark_report(
        [
            BenchmarkResult(
                profile="analysis",
                provider="groq",
                model="openai/gpt-oss-120b",
                case_key="nps_exec",
                case_title="Leitura executiva de NPS",
                latency_ms=812.4,
                ok=True,
                response_text="Resumo forte.",
            ),
            BenchmarkResult(
                profile="analysis",
                provider="openrouter",
                model="openai/gpt-oss-120b:free",
                case_key="nps_exec_2",
                case_title="Leitura executiva de NPS",
                latency_ms=1300.0,
                ok=True,
                response_text="Resumo alternativo.",
            ),
            BenchmarkResult(
                profile="artifact",
                provider="groq",
                model="openai/gpt-oss-120b",
                case_key="dashboard_choice",
                case_title="Escolha do melhor entregável visual",
                latency_ms=900.0,
                ok=True,
                response_text="Dashboard.",
            ),
        ]
    )

    assert report.count("Leitura executiva de NPS` pode virar um fluxo forte do Sentury em `analysis`") == 1
    assert report.count("Escolha do melhor entregável visual` pode virar um fluxo forte do Sentury em `artifact`") == 1
