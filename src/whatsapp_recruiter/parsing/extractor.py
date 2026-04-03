from __future__ import annotations

import re

from whatsapp_recruiter.models import CandidateRecord


class MedicalCvExtractor:
    CRM_PATTERN = re.compile(
        r"\bCRM\s*[:\-/\.]?\s*(?:n[oº°]?\s*\.?\s*)?[:\-]?\s*"
        r"(?:(?P<uf_before>AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\s*[-/:\.]?\s*)?"
        r"(?P<numero>\d{1,3}(?:\.\d{3})+|\d{4,10})"
        r"(?:\s*[-/–—|]*\s*(?P<uf_after>AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b)?",
        re.IGNORECASE,
    )
    CPF_PATTERN = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
    EMAIL_PATTERN = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
    PHONE_PATTERN = re.compile(
        r"(?<![\w/])(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?(?:9?\d{4})-?\d{4}(?![\w/])"
    )
    NASCIMENTO_PATTERN = re.compile(
        r"(?:data de nascimento|nascimento)\s*[:\-]?\s*(?P<value>\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
        re.IGNORECASE,
    )
    ESPECIALIZACAO_PATTERN = re.compile(
        r"(?:especiali[sz]a[cç][aã]o|especialidade|especialista em|resid[êe]ncia em)\s*[:\-]?\s*"
        r"(?P<value>[A-Za-zÀ-ÿ\s/]+)",
        re.IGNORECASE,
    )
    INDICACAO_PATTERN = re.compile(
        r"(?:indica[cç][aã]o|indicado por)\s*[:\-]?\s*(?P<value>[A-Za-zÀ-ÿ\s]+)",
        re.IGNORECASE,
    )
    CIDADE_UF_PATTERN = re.compile(
        r"\b(?P<cidade>[A-Za-zÀ-ÿ\s]+)\s*[-/]\s*"
        r"(?P<uf>AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b"
    )
    NAME_PATTERN = re.compile(
        r"(?:nome(?: completo)?|dr\.?|dra\.?)\s*[:\-]?\s*"
        r"(?P<value>[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ][A-Za-zÀ-ÿ]+"
        r"(?:\s+[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ][A-Za-zÀ-ÿ]+){1,4})",
        re.IGNORECASE,
    )

    def extract(self, text: str, chat_name: str | None = None, source: str = "mensagem") -> CandidateRecord:
        normalized_text = self._normalize(text)

        crm_match = self.CRM_PATTERN.search(normalized_text)
        cpf_match = self.CPF_PATTERN.search(normalized_text)
        email_match = self.EMAIL_PATTERN.search(normalized_text)
        phone_match = self.PHONE_PATTERN.search(normalized_text)
        specialization_match = self.ESPECIALIZACAO_PATTERN.search(normalized_text)
        indication_match = self.INDICACAO_PATTERN.search(normalized_text)
        city_match = self.CIDADE_UF_PATTERN.search(normalized_text)
        birth_match = self.NASCIMENTO_PATTERN.search(normalized_text)
        name = self._find_name(normalized_text, chat_name, allow_chat_fallback=source != "pdf")

        crm_raw = crm_match.group("numero") if crm_match else None
        crm = re.sub(r"\D", "", crm_raw) if crm_raw else None
        crm_uf_raw = (crm_match.group("uf_before") or crm_match.group("uf_after")) if crm_match else None
        crm_uf = crm_uf_raw.upper() if crm_uf_raw else None
        cidade = city_match.group("cidade").strip() if city_match else None
        uf = city_match.group("uf") if city_match else crm_uf

        return CandidateRecord(
            nome_completo=name,
            especializacao=self._clean_field(specialization_match.group("value")) if specialization_match else None,
            crm=crm,
            crm_uf=crm_uf,
            cpf=cpf_match.group(0) if cpf_match else None,
            data_nascimento=birth_match.group("value") if birth_match else None,
            telefone=phone_match.group(0) if phone_match else None,
            email=email_match.group(0) if email_match else None,
            cidade=cidade,
            uf=uf,
            indicacao=self._clean_field(indication_match.group("value")) if indication_match else None,
            status_sam=None,
            carta_apresentacao="OK" if source == "pdf" else None,
            observacoes=None,
            fonte=None,
            conversa=chat_name,
            mensagem=text,
            texto_extraido=text,
        )

    def has_minimum_fields(self, record: CandidateRecord) -> bool:
        return bool(record.nome_completo and (record.crm or record.especializacao))

    def _find_name(self, text: str, chat_name: str | None, allow_chat_fallback: bool = True) -> str | None:
        match = self.NAME_PATTERN.search(text)
        if match:
            return self._clean_field(match.group("value"))

        line_name = self._find_name_from_lines(text)
        if line_name:
            return line_name

        if allow_chat_fallback and chat_name and len(chat_name.split()) >= 2:
            return chat_name.strip()

        return None

    def _find_name_from_lines(self, text: str) -> str | None:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"\.pdf\b", "", line, flags=re.IGNORECASE)
            line = re.sub(r"\bCPF\b.*", "", line, flags=re.IGNORECASE)
            line = re.sub(r"\bPDF\b", "", line, flags=re.IGNORECASE)
            line = re.sub(r"\s{2,}", " ", line).strip(" -:")
            words = [word for word in line.split() if word]
            if len(words) < 2:
                continue
            if all(re.fullmatch(r"[A-ZÀ-Ý][A-ZÀ-ÿ]+", word) for word in words[:5]):
                return line.title()
        return None

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.replace("\u200e", " ")
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    @staticmethod
    def _clean_field(value: str | None) -> str | None:
        if not value:
            return None
        value = re.sub(r"\s{2,}", " ", value)
        value = re.sub(
            r"\b(?:crm|cpf|telefone|celular|e-?mail|email|especialidade|especializacao|especialização)\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return value.strip(" -:\n\r\t")
