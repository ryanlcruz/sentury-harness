from pathlib import Path

from robinbandit import RobinGateway


def test_robinbandit_carrega_perfil_yaml_do_sentury():
    path = (
        Path(__file__).resolve().parents[1]
        / "sentury"
        / "plugins"
        / "robinbandit"
        / "config"
        / "sentury.yaml"
    )
    router = RobinGateway.from_yaml(path)
    assert router.backend_name == "robinbandit"
    assert router.config.agent_mode == "sentury"
    assert router.context("critical", "analysis") == "analysis:CRITICAL"
    assert router.config.strategy == "adaptive"
    assert router.config.chain_order[-1] == "fallback"
