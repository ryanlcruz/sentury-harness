"""Mensagens e tracebacks passam pela redação antes de sair nos handlers."""
import logging

from .segredos import redigir_segredos


def proteger_registro(record):
    # O segredo pode estar só nos argumentos, então a conferência é na mensagem
    # já montada. Sem segredo, o registro fica como veio: formatador que lê os
    # argumentos (o log de acesso do uvicorn) precisa deles.
    try:
        montada = record.getMessage()
        redigida = redigir_segredos(montada)
    except Exception:
        record.msg, record.args = "Mensagem de log indisponível", ()
    else:
        if redigida != montada:
            record.msg, record.args = redigida, ()
    if record.exc_info:
        record.exc_text = redigir_segredos(logging.Formatter().formatException(record.exc_info))
    if record.stack_info:
        record.stack_info = redigir_segredos(record.stack_info)
    return record


class FormatoSeguro(logging.Formatter):
    def __init__(self, original=None):
        super().__init__()
        self.original = original or logging.Formatter()

    def format(self, record):
        proteger_registro(record)
        return redigir_segredos(self.original.format(record))


def instalar_redacao():
    anterior = logging.getLogRecordFactory()
    if not getattr(anterior, "_redacao_sentury", False):
        def criar(*args, **kwargs):
            return proteger_registro(anterior(*args, **kwargs))
        criar._redacao_sentury = True
        logging.setLogRecordFactory(criar)
    loggers = [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
    for logger in loggers:
        if not isinstance(logger, logging.Logger):
            continue
        for handler in logger.handlers:
            if not isinstance(handler.formatter, FormatoSeguro):
                handler.setFormatter(FormatoSeguro(handler.formatter))
