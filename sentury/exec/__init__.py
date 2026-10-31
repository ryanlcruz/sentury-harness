"""Camada de execucao: um lugar so para rodar processo, script e codigo.

Tres caminhos rodam coisas (o sandbox de Python, o shell e a escrita de
arquivo), cada um com politica propria. Aqui ficam as pecas que os tres
compartilham: o formato do resultado, o ambiente do processo filho e o
tratamento da saida.
"""
from .contrato import CodigoDeErro, Resultado

__all__ = ["CodigoDeErro", "Resultado"]
