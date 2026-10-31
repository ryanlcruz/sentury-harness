"""O modelo sabe que o treino tem data de corte e que a web existe."""


def test_prompt_avisa_que_o_treino_tem_data_de_corte():
    from sentury.llm.prompts import GROUNDING_GUIDANCE

    texto = GROUNDING_GUIDANCE.lower()
    assert "data de corte" in texto
    assert "buscar_web" in texto
