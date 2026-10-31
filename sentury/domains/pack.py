"""DomainPack: um setor plugável (contrato de especialização)."""
from dataclasses import dataclass, field, field
from typing import Any, Dict, FrozenSet, Optional, Tuple

# As formas que o motor sabe desenhar; o setor escolhe uma por ferramenta.
FORMAS_DE_GRAFICO = ("linha", "rosca", "barra_horizontal")


@dataclass(frozen=True)
class DomainPack:
    # cx_metrics = experiência (feedbacks); ops_metrics = operação (tickets).

    name: str
    metric_meta: Dict[str, Dict[str, str]]
    higher_is_better: Dict[str, bool]
    cx_metrics: FrozenSet[str]
    ops_metrics: FrozenSet[str]
    # Resto do contrato (B). Opcionais: CX ainda usa o prompt-núcleo direto até
    # B1 preencher a persona. expected_sources é abstrato (o TenantBinding liga ao
    # sistema real do cliente); capabilities = tools/skills que o setor expõe.
    persona: Optional[str] = None
    responder_persona: Optional[str] = None
    # O que o PLANEJADOR precisa saber para trabalhar neste setor: as
    # ferramentas dele, o schema dos dados, as regras de quando rodar o
    # que. Somado ao prompt base, nunca substituindo: o motor continua
    # sendo o motor.
    planner: Optional[str] = None
    # Como o agente RESPONDE neste setor: as ferramentas dele, o schema, o
    # jeito de apresentar. Irmao do `planner`, e pelo mesmo motivo: o
    # NUCLEO_DO_AGENTE tinha 45 de 188 linhas de CX, e como
    # `build_system_persona()` faz `identidade + NUCLEO`, o GENERALISTA
    # recebia tudo isso junto.
    responder: Optional[str] = None
    # Ferramentas do setor cujo resultado carrega texto escrito por TERCEIRO
    # comentario de pesquisa, descricao de chamado, avaliacao de produto.
    # Esse texto entra no contexto, entao alguem de fora pode escrever ali
    # uma instrucao e o modelo obedecer. A lista estava cravada com nomes de
    # CX: num pacote de e-commerce, a avaliacao do cliente nao seria marcada.
    texto_de_terceiros: FrozenSet[str] = frozenset()
    # Qual analise do setor sustenta um grafico sobre cada assunto.
    # Recuperacao para quando o planejador pede o grafico e esquece a
    # fonte; sem setor nao ha o que recuperar, e a tabela fica vazia.
    dicas_de_grafico: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    # O que o setor oferece quando o pedido de material nao diz de que dado:
    # cada fonte tem rotulo, descricao e, quando sustenta um grafico, a
    # ferramenta e os termos que a apontam. Sem setor, o motor oferece fontes
    # neutras (arquivo, dado colado, web).
    fontes_de_dados: Tuple[Dict[str, Any], ...] = ()
    # Quem costuma usar a entrega neste setor. Sem setor, publicos neutros.
    publicos: Tuple[Dict[str, str], ...] = ()
    # Comandos curtos dos canais de mensagem (Telegram): comando, descricao e
    # a pergunta que ele vira. Sem setor, so os comandos do motor.
    atalhos: Tuple[Dict[str, str], ...] = ()
    # Exemplos de pedido para a ajuda dos canais. Sem setor, exemplos neutros.
    exemplos_de_pedido: Tuple[str, ...] = ()
    # Categorias do setor que o grafico pinta com cor fixa: papel (positivo,
    # neutro, negativo) -> termos. Sem setor, so o sentimento generico.
    cores_de_rotulo: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    # Titulo de cada secao do painel cruzado, por ferramenta, e o rotulo
    # legivel de cada coluna dos resultados do setor.
    titulos_de_secao: Dict[str, str] = field(default_factory=dict)
    rotulos_de_coluna: Dict[str, str] = field(default_factory=dict)
    # Titulo do passo na tela, por ferramenta do setor ("Cruzando o NPS...").
    titulos_de_passo: Dict[str, str] = field(default_factory=dict)
    # ferramenta -> (coluna do eixo x, coluna do eixo y)
    colunas_de_grafico: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    # ferramenta -> forma preferida do grafico: linha, rosca ou barra_horizontal
    formas_de_grafico: Dict[str, str] = field(default_factory=dict)
    # ferramenta -> titulo do painel que ela gera
    titulos_de_painel: Dict[str, str] = field(default_factory=dict)
    # Analise que da chao antes de opinar (o conselho usa).
    analise_de_base: str = ""
    # Qual ferramenta MEDE causa neste setor. Quando o pedido e causal
    # ("por que", "o que esta causando"), o motor a injeta no comeco do
    # plano em vez de devolver "me peca pra rodar". Sem setor nao ha
    # ferramenta de causa, e o motor nao injeta nada.
    ferramenta_de_causa: Optional[str] = None
    # Ferramentas cuja SAIDA e a entrega: o markdown delas vai para a
    # conversa em vez de virar contexto para o modelo redigir por cima.
    # Cada uma diz como quer ser entregue: como texto, como anexo com
    # titulo e nome de arquivo, ou como esqueleto que o modelo reescreve.
    entregas: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # Guardas: quando o pedido casa um gatilho, a ferramenta entra no
    # plano mesmo que o planejador nao a tenha escolhido. O que e
    # gatilho, e que dimensao vale extrair da frase, e do setor: um
    # cliente cuja operacao e por pais ou por produto nao tem regiao.
    # Por quais recortes este dominio se divide, e que valores cada um
    # aceita. Serve a guarda (extrair o recorte da frase) e a
    # persistencia de filtro (decidir se o usuario pediu o recorte ou
    # se ele veio por heranca). Uma operacao por pais, unidade ou
    # produto declara outra coisa aqui: nada disso e do motor.
    dimensoes: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    guardas: Tuple[Dict[str, Any], ...] = ()
    # Tabelas que o setor quer ver como DataFrame dentro do `executar_python`.
    # Eram tres nomes de CX cravados no motor; agora quem sabe o nome da
    # tabela e quem conhece o negocio.
    # O corpus conceitual que `buscar_conhecimento` recupera. Nove das onze
    # entradas do motor eram de CX: e vazavam num lugar que a regua nao
    # olhava: o que o agente RECUPERA, nao o que ele le no prompt.
    conhecimento: Tuple[Dict[str, str], ...] = ()
    tabelas_no_sandbox: Tuple[str, ...] = ()
    expected_sources: FrozenSet[str] = frozenset()
    capabilities: FrozenSet[str] = frozenset()

    @property
    def metric_names(self) -> FrozenSet[str]:
        return self.cx_metrics | self.ops_metrics
