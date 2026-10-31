"""O pacote deixa de so adicionar ferramenta e passa a ensinar o setor.

Duas pecas que faltavam para "jogar dentro da pasta e so ligar":

`steering/` e contexto que entra sempre naquele setor, por regra. Skill e
procedimento recuperado quando o agente tem uma duvida; steering vale antes de
ele suspeitar de qualquer coisa.

E `mcp.json` no pacote: some na LEITURA e nunca na escrita. Gravar o servidor do
pacote no arquivo do usuario deixaria orfao quando o setor fosse desinstalado.
"""
from pathlib import Path

import pytest

from sentury.domains import steering
from sentury.domains.carregador import PREFIXO_MCP, mcp_do_pacote


def _pack(tmp_path: Path, nome: str = "teste") -> Path:
    alvo = tmp_path / nome
    (alvo / steering.PASTA).mkdir(parents=True)
    return alvo


def _play(pasta: Path, arquivo: str, cabecalho: str, corpo: str = "o corpo do playbook") -> None:
    (pasta / steering.PASTA / arquivo).write_text(
        "---" + chr(10) + cabecalho + chr(10) + "---" + chr(10) + corpo + chr(10),
        encoding="utf-8",
    )


# -------------------------------------------------------------- steering

def test_pacote_sem_steering_nao_quebra(tmp_path):
    (tmp_path / "vazio").mkdir()
    assert steering.ler(tmp_path / "vazio") == []


def test_le_o_playbook_com_a_regra(tmp_path):
    pack = _pack(tmp_path)
    _play(pack, "a.md", "titulo: Como mexer" + chr(10) + "quando: sempre")
    (play,) = steering.ler(pack)
    assert play.titulo == "Como mexer" and play.quando == "sempre"


def test_sempre_entra_e_manual_nao(tmp_path):
    pack = _pack(tmp_path)
    _play(pack, "a.md", "quando: sempre")
    _play(pack, "b.md", "quando: manual")
    nomes = [p.nome for p in steering.aplicaveis(steering.ler(pack))]
    assert nomes == ["a"]


def test_manual_entra_quando_pedido_pelo_nome(tmp_path):
    pack = _pack(tmp_path)
    _play(pack, "b.md", "quando: manual")
    escolhidos = steering.aplicaveis(steering.ler(pack), pedidos=["b"])
    assert [p.nome for p in escolhidos] == ["b"]


def test_por_arquivo_so_entra_quando_o_turno_toca(tmp_path):
    pack = _pack(tmp_path)
    _play(pack, "sql.md", "quando: arquivos" + chr(10) + "arquivos: ['*.sql']")
    todos = steering.ler(pack)
    assert steering.aplicaveis(todos) == []
    assert steering.aplicaveis(todos, arquivos_do_turno=["db/001.sql"])
    assert steering.aplicaveis(todos, arquivos_do_turno=["app.py"]) == []


def test_o_padrao_casa_o_caminho_e_o_nome(tmp_path):
    """`*.sql` tem que pegar `db/001.sql`: o usuario escreve a extensao e nao
    espera ter que saber se o caminho vem inteiro ou so o nome."""
    pack = _pack(tmp_path)
    _play(pack, "m.md", "quando: arquivos" + chr(10) + "arquivos: ['**/migrations/*.py']")
    todos = steering.ler(pack)
    assert steering.aplicaveis(todos, arquivos_do_turno=["app/migrations/003.py"])


def test_regra_desconhecida_vira_manual(tmp_path):
    """Regra que ninguem entende nao pode virar a mais cara por engano."""
    pack = _pack(tmp_path)
    _play(pack, "a.md", "quando: toda_hora")
    (play,) = steering.ler(pack)
    assert play.quando == "manual"
    assert steering.aplicaveis([play]) == []


def test_playbook_vazio_nao_entra(tmp_path):
    pack = _pack(tmp_path)
    _play(pack, "a.md", "quando: sempre", corpo="")
    assert steering.ler(pack) == []


def test_a_ordem_e_do_nome_do_arquivo(tmp_path):
    """Nao da ordem do sistema de arquivos, que muda entre maquinas e faria o
    mesmo pacote gerar prompts diferentes."""
    pack = _pack(tmp_path)
    for nome in ("zebra.md", "alfa.md", "meio.md"):
        _play(pack, nome, "quando: sempre")
    assert [p.nome for p in steering.ler(pack)] == ["alfa", "meio", "zebra"]


def test_playbook_gigante_e_cortado(tmp_path):
    pack = _pack(tmp_path)
    _play(pack, "a.md", "quando: sempre", corpo="x" * (steering.MAX_CARACTERES + 500))
    (play,) = steering.ler(pack)
    assert len(play.corpo) < steering.MAX_CARACTERES + 100
    assert "cortado" in play.corpo


def test_o_conjunto_tambem_tem_teto(tmp_path):
    """Dez playbooks dentro do limite individual somam trinta mil caracteres, e
    o que sai da janela para eles caberem e a conversa."""
    pack = _pack(tmp_path)
    for i in range(10):
        _play(pack, f"p{i}.md", "quando: sempre", corpo="x" * 3500)
    texto = steering.como_texto(steering.aplicaveis(steering.ler(pack)))
    assert len(texto) <= steering.MAX_NO_CONJUNTO + 200


def test_sem_playbook_o_texto_e_vazio(tmp_path):
    assert steering.como_texto([]) == ""


def test_o_texto_traz_o_titulo_e_o_corpo(tmp_path):
    pack = _pack(tmp_path)
    _play(pack, "a.md", "titulo: Regra do time" + chr(10) + "quando: sempre", corpo="nao use x")
    texto = steering.como_texto(steering.aplicaveis(steering.ler(pack)))
    assert "Regra do time" in texto and "nao use x" in texto


def test_sem_setor_nao_ha_steering():
    """O generalista nao tem playbook de setor, e cair no do CX faria ele
    ensinar um dominio que o usuario desligou de proposito."""
    assert steering.do_turno(object()) is None


def test_pacote_quebrado_nao_derruba_o_turno(tmp_path, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("pacote corrompido")

    monkeypatch.setattr(steering, "do_setor", explode)
    assert steering.para_o_turno("qualquer") == ""


# ------------------------------------------------------------------- mcp

def test_pacote_sem_mcp_devolve_vazio(tmp_path):
    (tmp_path / "p").mkdir()
    assert mcp_do_pacote("p", str(tmp_path)) == []


def test_o_id_ganha_o_prefixo_do_pacote(tmp_path):
    """Sem prefixo, um servidor do pacote colidiria com um id do usuario: e
    nada saberia dizer qual dos dois pode ser editado."""
    pack = tmp_path / "p"
    pack.mkdir()
    (pack / "mcp.json").write_text(
        '{"servidores": [{"id": "github", "nome": "GitHub", "transporte": "stdio",'
        ' "comando": "npx"}]}',
        encoding="utf-8",
    )
    (servidor,) = mcp_do_pacote("p", str(tmp_path))
    assert servidor["id"] == PREFIXO_MCP + "p:github"
    assert servidor["origem"] == "pacote p"


def test_mcp_json_quebrado_nao_derruba_a_tela(tmp_path):
    pack = tmp_path / "p"
    pack.mkdir()
    (pack / "mcp.json").write_text("{nao e json", encoding="utf-8")
    assert mcp_do_pacote("p", str(tmp_path)) == []


def test_servidor_sem_id_nem_nome_e_ignorado(tmp_path):
    pack = tmp_path / "p"
    pack.mkdir()
    (pack / "mcp.json").write_text('{"servidores": [{"transporte": "stdio"}]}', encoding="utf-8")
    assert mcp_do_pacote("p", str(tmp_path)) == []


def test_o_pacote_declara_o_nome_da_variavel_nao_o_valor(tmp_path):
    pack = tmp_path / "p"
    pack.mkdir()
    (pack / "mcp.json").write_text(
        '{"servidores": [{"id": "x", "nome": "X", "transporte": "stdio",'
        ' "comando": "y", "env_vars": ["GITHUB_TOKEN", "  "]}]}',
        encoding="utf-8",
    )
    (servidor,) = mcp_do_pacote("p", str(tmp_path))
    assert servidor["env_vars"] == ["GITHUB_TOKEN"]


def test_escrita_recusa_servidor_de_pacote(monkeypatch, tmp_path):
    """Gravar o do pacote no arquivo do usuario deixaria orfao quando o setor
    fosse desinstalado, e impediria a atualizacao do pacote de chegar."""
    from sentury.external import mcp_registry

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="pacote"):
        mcp_registry.salvar({
            "id": mcp_registry.PREFIXO_DE_PACOTE + "coder:github",
            "nome": "X", "transporte": "stdio", "comando": "y",
        })
    with pytest.raises(ValueError, match="pacote"):
        mcp_registry.remover(mcp_registry.PREFIXO_DE_PACOTE + "coder:github")


def test_remover_de_pacote_nao_mente_devolvendo_falso(monkeypatch, tmp_path):
    """`False` diria "nao encontrado" para um servidor que esta ali na lista."""
    from sentury.external import mcp_registry

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    try:
        mcp_registry.remover(mcp_registry.PREFIXO_DE_PACOTE + "x:y")
    except ValueError as exc:
        assert "pacote" in str(exc)
    else:
        pytest.fail("removeu em silencio")


# --------------------------------------------- o exemplo que vem no repo


# --------------------------------------- o motor para de ser de CX por dentro

def _mesa(monkeypatch, setor: str) -> list:
    """Os nomes que chegam ao modelo com aquele setor ligado.

    Fixa a ESCOLHA, nao o arquivo: onde o setor e persistido ja tem teste
    proprio, e mexer em `SENTURY_HOME` por variavel de ambiente nao funciona
    aqui: `settings` le uma vez, na importacao.
    """
    from sentury.domains import escolha
    from sentury.llm.tool_schemas import build_tool_schemas

    monkeypatch.setattr(escolha, "ler", lambda *a, **k: setor)
    return [s["function"]["name"] for s in build_tool_schemas() if "function" in s]


def test_o_generalista_nao_recebe_ferramenta_de_cx(monkeypatch):
    """Era a queixa do `consultar_sql`: dezesseis ferramentas de um dominio na
    mesa de quem desligou o dominio de proposito. `consultar_medida` e `consultar_medida`
    nao significam nada para quem pediu "analise o banco de dados nesta pasta"
e cada uma delas ocupa espaco onde caberia a que serve."""
    nomes = _mesa(monkeypatch, "generalista")
    from sentury.tools.registry import TOOL_REGISTRY

    de_setor = [n for n in nomes if (TOOL_REGISTRY.get(n) or {}).get("setor")]
    assert de_setor == [], de_setor


def test_com_o_setor_ligado_elas_voltam(monkeypatch):
    """Filtrar nao pode virar apagar: o produto de CX depende delas."""
    nomes = _mesa(monkeypatch, "setor_teste")
    assert "consultar_medida" in nomes and "consultar_medida" in nomes


def test_a_mesa_do_generalista_e_menor(monkeypatch):
    generalista = _mesa(monkeypatch, "generalista")
    cx = _mesa(monkeypatch, "setor_teste")
    assert len(generalista) < len(cx)
    assert set(generalista) < set(cx), "o generalista ganhou algo que o CX nao tem"


def test_o_que_e_generico_fica_para_todo_mundo(monkeypatch):
    """Ferramentas genéricas aparecem em qualquer setor, mas exportar exige uma fonte."""
    nomes = _mesa(monkeypatch, "generalista")
    for generica in ("executar_python",
                     "executar_comando", "ler_arquivo", "entregar_arquivo"):
        assert generica in nomes, generica
    for de_receita in ("generate_chart", "export_csv", "export_xlsx", "export_pdf", "export_html"):
        assert de_receita in nomes, de_receita
        from sentury.harness.policy import sentury_harness
        from sentury.harness.state import AnalysisState

        assert not sentury_harness.evaluate(
            AnalysisState.new("sem-fonte", "u"), de_receita, "exporte", {}).allowed


def test_ferramenta_sem_setor_e_do_motor():
    from sentury.tools.registry import do_motor, setor_da_ferramenta

    assert setor_da_ferramenta("consultar_medida") == "setor_teste"
    assert setor_da_ferramenta("ler_arquivo") == ""
    assert "ler_arquivo" in do_motor() and "consultar_medida" not in do_motor()
