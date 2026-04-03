from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CandidateRecord(BaseModel):
    nome_completo: str | None = None
    especializacao: str | None = None
    crm: str | None = None
    crm_uf: str | None = None
    cpf: str | None = None
    data_nascimento: str | None = None
    telefone: str | None = None
    email: str | None = None
    cidade: str | None = None
    uf: str | None = None
    indicacao: str | None = None
    status_sam: str | None = None
    carta_apresentacao: str | None = None
    observacoes: str | None = None
    fonte: str | None = Field(default=None)
    conversa: str | None = None
    mensagem: str | None = None
    pdf_path: str | None = None
    texto_extraido: str | None = None

    def as_export_dict(self) -> dict[str, Any]:
        return self.model_dump()


class MessageBundle(BaseModel):
    chat_name: str
    message_text: str
    pdf_path: Path | None = None
    attachment_context: str | None = None
    matched_term: str | None = None
    source: str | None = None
