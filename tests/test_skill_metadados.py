import pytest

from sentury.skills.skill_loader import SkillLoader


@pytest.mark.parametrize("cabecalho", [
    "tags: [arquivo]\ncategory: pesquisa",
    "metadata:\n  importada:\n    tags: [arquivo]\n    category: pesquisa",
])
def test_metadados_no_indice_e_conteudo(tmp_path, cabecalho):
    pasta = tmp_path / "exemplo"
    pasta.mkdir()
    (pasta / "SKILL.md").write_text(
        f"---\nname: exemplo\ndescription: Uma skill de teste\n{cabecalho}\n---\nCorpo",
        encoding="utf-8")
    loader = SkillLoader(tmp_path)
    entrada = loader.scan_skills()[0]
    conteudo = loader.load_skill("exemplo")
    assert entrada.tags == conteudo.metadata.tags == ["arquivo"]
    assert entrada.category == conteudo.metadata.category == "pesquisa"


def test_topo_tem_prioridade_inclusive_lista_vazia(tmp_path):
    pasta = tmp_path / "exemplo"
    pasta.mkdir()
    (pasta / "SKILL.md").write_text(
        "---\nname: exemplo\ntags: []\ncategory: propria\nmetadata:\n"
        "  outro:\n    tags: [antiga]\n    category: antiga\n---\nCorpo",
        encoding="utf-8")
    loader = SkillLoader(tmp_path)
    entrada = loader.scan_skills()[0]
    assert entrada.tags == []
    assert entrada.category == "propria"
    assert loader.load_skill("exemplo").metadata.tags == []
