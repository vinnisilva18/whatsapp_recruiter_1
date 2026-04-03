from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

from whatsapp_recruiter.config import Settings
from whatsapp_recruiter.documents.pdf_reader import PdfTextExtractor
from whatsapp_recruiter.export.xlsx_writer import CandidateExporter
from whatsapp_recruiter.models import CandidateRecord, MessageBundle
from whatsapp_recruiter.parsing.extractor import MedicalCvExtractor
from whatsapp_recruiter.whatsapp.client import WhatsAppWebClient


DEFAULT_KEYWORDS = [
    "cv",
    "curriculo",
    "curriculum",
    "vitae",
    "resume",
    "lattes",
    "nome completo",
    "crm",
    "especialidade",
    "especializacao",
    "telefone",
    "celular",
    "email",
    "e-mail",
    "indicacao",
]


def _safe_console_text(value: str) -> str:
    return value.encode("ascii", "backslashreplace").decode("ascii")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extrai dados de curriculos medicos do WhatsApp Web.")
    parser.add_argument(
        "--search",
        default="",
        help="Termo opcional para localizar mensagens/anexos durante a varredura lateral das conversas.",
    )
    parser.add_argument("--limit", type=int, default=30, help="Numero maximo de evidencias por conversa.")
    parser.add_argument(
        "--chat-limit",
        type=int,
        default=50,
        help="Quantidade maxima de conversas a percorrer quando --search estiver vazio.",
    )
    parser.add_argument(
        "--keywords",
        nargs="*",
        default=DEFAULT_KEYWORDS,
        help="Palavras-chave usadas para detectar mensagens relacionadas a curriculo.",
    )
    parser.add_argument(
        "--output",
        default="output/recruiters",
        help="Caminho base para os arquivos finais sem extensao.",
    )
    return parser


def process_messages(
    search: str,
    limit: int,
    chat_limit: int,
    keywords: list[str],
    output: str,
) -> tuple[list[CandidateRecord], Path, Path]:
    settings = Settings.from_env()
    whatsapp = WhatsAppWebClient(settings)
    pdf_extractor = PdfTextExtractor(settings)
    cv_extractor = MedicalCvExtractor()
    exporter = CandidateExporter(settings)
    records: list[CandidateRecord] = []
    normalized_keywords = _build_scan_terms(search, keywords)

    try:
        print("Abrindo WhatsApp Web...")
        whatsapp.open()
        if search.strip():
            print(f"Varredura lateral ativa com termo de mensagem/anexo: {search.strip()}")

        processed_chats = 0
        for chat_name, bundles in whatsapp.iter_chat_messages(
            max_chats=chat_limit,
            message_limit=limit,
            keywords=normalized_keywords,
        ):
            processed_chats += 1
            safe_chat_name = _safe_console_text(chat_name)
            print(f"Analisando conversa: {safe_chat_name}")
            print(f"Evidencias coletadas em '{safe_chat_name}': {len(bundles)}")

            record = _build_chat_record(
                bundles=bundles,
                chat_name=chat_name,
                cv_extractor=cv_extractor,
                pdf_extractor=pdf_extractor,
            )
            if _is_candidate_record(record):
                print(
                    "Registro identificado:",
                    _safe_console_text(record.nome_completo or "(sem nome)"),
                    _safe_console_text(record.crm or ""),
                    _safe_console_text(record.especializacao or ""),
                )
                records.append(record)
        print(f"Conversas processadas na varredura: {processed_chats}")
    finally:
        whatsapp.close()

    records = _deduplicate_records(records)
    output_base = Path(output)
    output_base.parent.mkdir(parents=True, exist_ok=True)
    json_path, xlsx_path = exporter.export(records, output_base)
    return records, json_path, xlsx_path


def _normalize_term(value: str) -> str:
    value = re.sub(r"(?<=[a-z\u00e0-\u00ff])(?=[A-Z\u00c0-\u00dd])", " ", value)
    normalized = "".join(
        c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn"
    )
    normalized = re.sub(r"[_.\-/]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _build_scan_terms(search: str, keywords: list[str]) -> list[str]:
    terms: list[str] = []

    for keyword in keywords:
        normalized = _normalize_term(keyword)
        if normalized and normalized not in terms:
            terms.append(normalized)

    search_normalized = _normalize_term(search)
    if search_normalized and search_normalized not in terms:
        terms.append(search_normalized)

    for part in search_normalized.split():
        if len(part) >= 3 and part not in terms:
            terms.append(part)

    return terms


def _build_chat_record(
    bundles: list[MessageBundle],
    chat_name: str,
    cv_extractor: MedicalCvExtractor,
    pdf_extractor: PdfTextExtractor,
) -> CandidateRecord:
    merged = CandidateRecord(conversa=chat_name, fonte="whatsapp")
    extracted_text_parts: list[str] = []
    message_parts: list[str] = []

    for bundle in bundles:
        context_text = "\n".join(
            part for part in [bundle.message_text, bundle.attachment_context or ""] if part and part.strip()
        )
        if context_text.strip():
            message_record = cv_extractor.extract(
                text=context_text,
                chat_name=bundle.chat_name,
                source="mensagem",
            )
            _merge_candidate_record(merged, message_record, prefer_name=False)
            message_parts.append(context_text)

        if bundle.pdf_path:
            merged.pdf_path = str(bundle.pdf_path)
            try:
                pdf_text = pdf_extractor.extract_text(bundle.pdf_path)
            except Exception as exc:
                print(
                    f"Falha ao extrair texto do anexo '{bundle.pdf_path.name}': "
                    f"{_safe_console_text(str(exc))}"
                )
                pdf_text = ""

            if pdf_text:
                pdf_record = cv_extractor.extract(
                    text=pdf_text,
                    chat_name=bundle.chat_name,
                    source="pdf",
                )
                _merge_candidate_record(merged, pdf_record, prefer_name=True)
                extracted_text_parts.append(pdf_text)

    if message_parts and not merged.mensagem:
        merged.mensagem = "\n\n".join(dict.fromkeys(part for part in message_parts if part.strip()))
    if extracted_text_parts:
        merged.texto_extraido = "\n\n".join(dict.fromkeys(part for part in extracted_text_parts if part.strip()))
    if not merged.nome_completo and chat_name:
        merged.nome_completo = chat_name
    if not merged.indicacao:
        merged.indicacao = chat_name
    return merged


def _merge_candidate_record(target: CandidateRecord, incoming: CandidateRecord, prefer_name: bool) -> None:
    for key, value in incoming.model_dump().items():
        if not value:
            continue
        current = getattr(target, key)
        if key == "nome_completo":
            if _should_use_incoming_name(current, value, target.conversa, prefer_name):
                setattr(target, key, value)
            continue
        if key in {"mensagem", "texto_extraido"}:
            if not current:
                setattr(target, key, value)
            continue
        if not current:
            setattr(target, key, value)


def _should_use_incoming_name(
    current_name: str | None,
    incoming_name: str | None,
    chat_name: str | None,
    prefer_name: bool,
) -> bool:
    if prefer_name:
        return _should_prefer_pdf_name(current_name, incoming_name, chat_name)
    if not incoming_name:
        return False
    if not current_name:
        return True

    normalized_current = _normalize_term(current_name)
    normalized_incoming = _normalize_term(incoming_name)
    normalized_chat = _normalize_term(chat_name or "")

    if normalized_current == normalized_incoming:
        return False
    if normalized_current == normalized_chat:
        return True
    return len(normalized_incoming.split()) > len(normalized_current.split())


def _is_candidate_record(record: CandidateRecord) -> bool:
    has_identity = any(
        [
            record.crm,
            record.cpf,
            record.email,
            record.telefone,
            record.especializacao,
            record.pdf_path,
        ]
    )
    return bool(record.nome_completo and has_identity) or bool(
        any(
            [
                record.crm,
                record.cpf,
                record.email,
                record.telefone,
            ]
        )
    )


def _should_prefer_pdf_name(
    current_name: str | None,
    pdf_name: str | None,
    chat_name: str | None,
) -> bool:
    if not pdf_name:
        return False
    if not current_name:
        return True

    normalized_current = _normalize_term(current_name)
    normalized_pdf = _normalize_term(pdf_name)
    normalized_chat = _normalize_term(chat_name or "")

    if normalized_current == normalized_pdf:
        return False
    if normalized_current == normalized_chat:
        return True
    if len(normalized_pdf.split()) >= len(normalized_current.split()):
        return True
    return False


def _deduplicate_records(records: list[CandidateRecord]) -> list[CandidateRecord]:
    deduplicated: list[CandidateRecord] = []
    seen: set[str] = set()

    for record in records:
        key = "|".join(
            [
                (record.crm or "").strip().lower(),
                (record.email or "").strip().lower(),
                (record.telefone or "").strip().lower(),
                (record.nome_completo or "").strip().lower(),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(record)

    return deduplicated


def main() -> None:
    args = build_parser().parse_args()
    records, json_path, xlsx_path = process_messages(
        search=args.search,
        limit=args.limit,
        chat_limit=args.chat_limit,
        keywords=args.keywords,
        output=args.output,
    )
    print(f"Registros exportados: {len(records)}")
    print(f"JSON: {json_path}")
    print(f"XLSX: {xlsx_path}")


if __name__ == "__main__":
    main()
