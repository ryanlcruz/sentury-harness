"""A tela de modos diz se a conta é assinatura ou API paga e mostra o catálogo vivo."""
from pathlib import Path

TELA = Path("sentury/client/src/features/runtime/SelecaoDeModo.tsx").read_text(encoding="utf-8")
PROVEDORES = Path("sentury/client/src/features/runtime/ProvidersView.tsx").read_text(encoding="utf-8")


def test_o_selo_vem_do_cost_class_e_nao_de_lista_no_codigo():
    """Assinatura e API custam e limitam diferente; quem diz qual é o provedor,
    pelo `cost_class` do RobinBandit, e não uma lista de tipos de login aqui."""
    assert "custo === 'subscription'" in TELA and ">assinatura<" in TELA and ">API paga<" in TELA
    assert "codex_cli" not in TELA
    assert "custoDoProvedor={custoPorProvedor}" in PROVEDORES


def test_o_catalogo_vivo_aparece_ao_lado_dos_modelos_declarados():
    """A lista que a conta declara envelhece; o modelo novo do provedor só
    aparecia pela busca."""
    assert "/sentury/providers/${provedor}/models" in TELA and "MAX_VIVOS_COMO_BOTAO" in TELA


def test_trocar_de_conversa_nao_derruba_o_estado_da_conexao():
    """O rodapé mostrava "Offline" com a API no ar: trocar de conversa zerava
    o estado da conexão junto com o turno mostrado."""
    loja = Path("sentury/client/src/stores/harness-store.ts").read_text(encoding="utf-8")
    inicio = loja.index("seguirSessao: (id: string | null) => set(")
    trecho = loja[inicio:loja.index("updateHarnessState:", inicio)]
    assert "status: 'offline'" not in trecho and "state.status === 'busy' ? 'online' : state.status" in trecho


def test_o_automatico_nao_promete_o_deliberate():
    composer = Path("sentury/client/src/features/chat/Composer.tsx").read_text(encoding="utf-8")
    assert "pede mais quando precisa" not in composer
