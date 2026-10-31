"""O chat e a conversa do residente aceitam o mesmo arquivo recebido."""
from pydantic import BaseModel, Field


class ArquivoAnexado(BaseModel):
    nome: str = Field(default="arquivo", max_length=200)
    data_url: str = Field(..., max_length=11_500_000)
