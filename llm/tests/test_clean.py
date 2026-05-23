from __future__ import annotations

import json
from pathlib import Path

from pcdt_ingest.clean import cleaner as cleaner_mod
from pcdt_ingest.clean.cleaner import clean_page_markdown, clean_pages, clean_pages_jsonl, default_output_path
from pcdt_ingest.clean.heuristics import (
    classify_document,
    find_clinical_content_start_page,
    is_junk_text,
    repeated_edge_line_keys,
)
from pcdt_ingest.clean.models import CleanConfig
from pcdt_ingest.clean.utils import dehyphenate, normalize_table_breaks
from pcdt_ingest.chunk import sidecar_stem


def test_remove_image_placeholder_line() -> None:
    text, flags, stats = clean_page_markdown(
        "**==> picture [63 x 55] intentionally omitted <==**\n\nTexto clínico com conteúdo suficiente.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "picture" not in text.lower()
    assert "removed_image_placeholder" in flags
    assert stats.placeholders_removed == 1


def test_remove_bold_page_number_admin_portaria_and_figure_caption() -> None:
    text, flags, stats = clean_page_markdown(
        "**1**\n\nPORTARIA SECTICS/MS No 83, DE 7 DE OUTUBRO DE 2025\n\n"
        "**Figura 5** - Fluxo de tratamento de adenocarcinoma de reto.\n\n"
        "## **FIGURA I - FLUXOGRAMA PARA IDENTIFICAÇÃO DE SERPENTES.**\n\n"
        "## **INTRODUÇÃO**\n\nTexto clínico com conteúdo suficiente.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "**1**" not in text
    assert "PORTARIA SECTICS" not in text
    assert "Figura 5" not in text
    assert "FIGURA I" not in text
    assert "## **INTRODUÇÃO**" in text
    assert "removed_page_number" in flags
    assert "removed_admin_noise" in flags
    assert "removed_figure_caption" in flags
    assert stats.lines_removed == 4


def test_remove_picture_text_block_content() -> None:
    text, flags, stats = clean_page_markdown(
        "Texto clínico antes.\n"
        "**==> picture [570 x 230] intentionally omitted <==**\n"
        "**----- Start of picture text -----**<br>\n"
        "|**SABL ou**|texto OCR visual|6|\n"
        "**----- End of picture text -----**<br>\n"
        "Texto clínico depois.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "picture" not in text.lower()
    assert "SABL ou" not in text
    assert "Start of picture text" not in text
    assert "Texto clínico antes." in text
    assert "Texto clínico depois." in text
    assert "removed_image_placeholder" in flags
    assert "removed_picture_text_block" in flags
    assert stats.lines_removed == 4


def test_remove_known_signature_but_preserve_uppercase_medical_title() -> None:
    text, flags, stats = clean_page_markdown(
        "## CRITÉRIOS DE INCLUSÃO\n\nFERNANDA DE NEGRI\n\nPaciente com quadro compatível.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "CRITÉRIOS DE INCLUSÃO" in text
    assert "FERNANDA DE NEGRI" not in text
    assert "removed_signature" in flags
    assert stats.signatures_removed == 1


def test_dehyphenation_keeps_same_line_compound_words() -> None:
    got, changed = dehyphenate("A interven-\nção foi descrita. Manejo clínico-cirúrgico.")

    assert changed is True
    assert "intervenção" in got
    assert "clínico-cirúrgico" in got


def test_header_footer_detection_removes_repeated_edges() -> None:
    pages = [
        "CABECALHO REPETIDO\n## 1. INTRODUÇÃO\nTexto clínico relevante.",
        "CABECALHO REPETIDO\n## 2. DIAGNÓSTICO\nTexto clínico relevante.",
        "CABECALHO REPETIDO\n## 3. TRATAMENTO\nTexto clínico relevante.",
    ]
    repeated = repeated_edge_line_keys(pages, threshold=0.5, window=1)
    text, flags, stats = clean_page_markdown(
        pages[0],
        repeated_keys=repeated,
        config=CleanConfig(min_words=3),
    )

    assert "CABECALHO REPETIDO" not in text
    assert "## 1. INTRODUÇÃO" in text
    assert "removed_header_footer" in flags
    assert stats.headers_footers_removed == 1


def test_junk_detection_preserves_useful_titles_and_cid() -> None:
    assert is_junk_text("") is True
    assert is_junk_text("### 1. INTRODUÇÃO", min_words=6) is False
    assert is_junk_text("CID-10 A41.9", min_words=6) is False
    assert is_junk_text("abc", min_words=6) is True


def test_find_clinical_content_start_page_is_conservative() -> None:
    rows = [
        {"page": 1, "markdown": "PORTARIA SECTICS/MS Nº 59\nFERNANDA DE NEGRI"},
        {"page": 2, "markdown": "## ANEXO PROTOCOLO CLÍNICO\n## 1. INTRODUÇÃO"},
    ]

    assert find_clinical_content_start_page(rows) == 2
    assert find_clinical_content_start_page(["sem marcador"]) == 1


def test_classify_document() -> None:
    complete = [
        "ANEXO PROTOCOLO CLÍNICO E DIRETRIZES TERAPÊUTICAS\n"
        "## 1. INTRODUÇÃO\n"
        + "conteúdo clínico " * 80
        + "\n## 2. DIAGNÓSTICO\n"
        + "tratamento monitoramento " * 80
    ]
    visual = ["**==> picture intentionally omitted <==**\nBOX\n" * 4]

    assert classify_document(complete) == "pcdt_completo"
    assert classify_document(visual) == "pcdt_resumido_visual"
    assert classify_document(["texto comum"]) == "desconhecido"


def test_table_breaks_are_normalized() -> None:
    text = "|Soro|Apresentação|\n|---|---|\n|SABR|imuno-<br>globulina contra veneno<br>de serpentes|"
    got, changed = normalize_table_breaks(text)

    assert changed is True
    assert "imunoglobulina" in got
    assert "<br>" not in got
    assert "veneno de serpentes" in got


def test_malformed_table_block_and_caption_are_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "Texto clínico antes.\n\n"
        "**Quadro 3** - Avaliações para seguimento clínico dos pacientes com ATTR\n"
        "||||||||\n"
        "|---|---|---|---|---|---|---|\n"
        "||guir a conduta adotada p|elo centro transplantador.|||||\n"
        "||**3**- Avaliações para seguiment|o clínico dos pacientes com ATTR|||||\n"
        "|Histó|ria médica||X|X|||\n\n"
        "Texto clínico depois.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "Quadro 3" not in text
    assert "||||" not in text
    assert "Histó|ria" not in text
    assert "Texto clínico antes." in text
    assert "Texto clínico depois." in text
    assert "removed_malformed_table" in flags


def test_search_strategy_table_is_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "## APÊNDICE\n\n"
        "|||**Estratégia de busca**||||**resultados** **encontrados**|||\n"
        "||||||||||\n"
        "|---|---|---|\n"
        "||||||||||\n"
        "Texto clínico depois.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "Estratégia de busca" not in text
    assert "||||" not in text
    assert "Texto clínico depois." in text
    assert "removed_search_strategy_caption" in flags


def test_empty_and_separator_table_rows_are_removed_but_content_rows_remain() -> None:
    text, flags, _stats = clean_page_markdown(
        "|Item|Conduta|Dose|\n"
        "||||\n"
        "|---|---|---|\n"
        "|Moderado|dor e edema|6 frascos|\n"
        "||||",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "||||" not in text
    assert "|---|---|---|" not in text
    assert "Item | Conduta | Dose" in text
    assert "Moderado | dor e edema | 6 frascos" in text
    assert "removed_empty_table_row" in flags
    assert "normalized_table_rows" in flags


def test_loose_pipe_table_rows_keep_first_and_last_cells() -> None:
    text, flags, _stats = clean_page_markdown(
        "Agente | Indicação | 1a escolha | Alternativas\n"
        "_Pneumocystis_ _jiroveci_ | LT-CD4+ <200 céls/mm3 | SMX-TMP | Dapsona",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "Agente | Indicação | 1a escolha | Alternativas" in text
    assert "_Pneumocystis_ _jiroveci_ | LT-CD4+ <200 céls/mm3 | SMX-TMP | Dapsona" in text
    assert "normalized_table_rows" in flags


def test_search_strategy_caption_is_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "Texto antes.\n\n"
        "**Quadro O** - Estratégia de busca da questão sobre anestesia geral versus sedação consciente.\n\n"
        "Texto depois.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "Estratégia de busca" not in text
    assert "Texto antes." in text
    assert "Texto depois." in text
    assert "removed_search_strategy_caption" in flags


def test_search_strategy_loose_pipe_table_is_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "Texto antes.\n\n"
        "**Quadro B -** Buscas sobre intervenções terapêuticas - Meta-análises\n"
        "**Base** | **Estratégia** | **Localizados** | **Selecionados**\n"
        'Medline (via PubMed) | "Psoriasis"[Mesh] AND "Therapeutics"[Mesh] | 36 | Motivo das exclusões\n'
        'Data da busca: 18/10/2018 | ("2013/11/09"[PDAT] : "2018/10/18"[PDAT]) | 8 | PICO: 9\n\n'
        "Texto depois.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "PubMed" not in text
    assert "Psoriasis" not in text
    assert "Texto antes." in text
    assert "Texto depois." in text
    assert "removed_search_strategy_caption" in flags or "removed_malformed_table" in flags


def test_form_filling_tail_is_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "Texto clínico antes.\n\n"
        "Eu, __________________________________________________________________ (nome do paciente), declaro ter sido informado claramente.\n"
        "Nome: ______________ CNS: ______________ RG: ______________\n"
        "**2 AVALIAÇÃO FARMACOTERAPÊUTICA**\n"
        "Café da manhã\n"
        "__________________________________________________________________",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert text == "Texto clínico antes."
    assert "declaro" not in text
    assert "AVALIAÇÃO FARMACOTERAPÊUTICA" not in text
    assert "removed_form_block" in flags


def test_signature_form_tail_and_rename_note_are_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "Documento de identificação do responsável legal:\n"
        "___________________________________________ Assinatura do paciente ou do responsável legal\n"
        "Médico Responsável: | CRM: | UF:\n"
        "________________________________________ Assinatura e carimbo do médico Data:____________________\n"
        "**Nota:** Verificar na Relação Nacional de Medicamentos Essenciais (Rename) vigente.\n"
        "METODOLOGIA DE BUSCA E AVALIAÇÃO DA LITERATURA",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert text == ""
    assert "removed_form_block" in flags
    assert "junk_text" in flags


def test_checkbox_medication_form_page_is_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "- ( ) Ibuprofeno ( ) Adalimumabe ( ) Naproxeno ( ) Etanercepte ( ) Sulfassalazina\n"
        "- ( ) Metotrexato ( ) Infliximabe ( ) Certolizumabe Pegol\n"
        "NOTA: Verificar na Relação Nacional de Medicamentos Essenciais (RENAME) vigente.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert text == ""
    assert "removed_form_block" in flags


def test_generic_protocol_header_and_horizontal_rule_are_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "Protocolo Clínico e Diretrizes Terapêuticas\n\n"
        "-------\n\n"
        "ANEXO\nPROTOCOLO CLÍNICO E DIRETRIZES TERAPÊUTICAS DO AVC\n",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "Protocolo Clínico e Diretrizes Terapêuticas\n\n-------" not in text
    assert "PROTOCOLO CLÍNICO E DIRETRIZES TERAPÊUTICAS DO AVC" in text
    assert "removed_generic_protocol_header" in flags
    assert "removed_horizontal_rule" in flags


def test_lone_annex_toc_and_figure_caption_are_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "ANEXO\n"
        "**CONTEXTO ....................................................................................................**ERRO! INDICADOR NÃO DEFINIDO.\n"
        "**1.1 UMA ABORDAGEM CENTRADA NA MULHER..............................................................................................7**\n"
        "**Figura O.** Fluxograma de seleção dos estudos.\n"
        "## **1. INTRODUÇÃO**\n"
        "Texto clínico válido.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "ANEXO" not in text
    assert "INDICADOR" not in text
    assert "ABORDAGEM CENTRADA" not in text
    assert "Figura O" not in text
    assert "## **1. INTRODUÇÃO**" in text
    assert "removed_lone_annex" in flags
    assert "removed_toc_line" in flags
    assert "removed_figure_caption" in flags


def test_index_table_block_is_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "SUMÁRIO\n"
        "| Seção | Página |\n"
        "|---|---|\n"
        "| INTRODUÇÃO | 5 |\n"
        "| DIAGNÓSTICO | 7 |\n"
        "| REFERÊNCIAS | 31 |\n"
        "## **1. INTRODUÇÃO**\n"
        "Texto clínico válido para manter.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "SUMÁRIO" not in text
    assert "Seção | Página" not in text
    assert "REFERÊNCIAS | 31" not in text
    assert "## **1. INTRODUÇÃO**" in text
    assert "Texto clínico válido" in text
    assert "removed_toc_heading" in flags


def test_references_section_is_truncated() -> None:
    text, flags, _stats = clean_page_markdown(
        "## **8. MONITORAMENTO**\n"
        "Texto clínico válido para manter.\n"
        "## **REFERÊNCIAS**\n"
        "1. Autor A. Artigo bibliográfico.\n"
        "2. Autor B. Outro artigo.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "MONITORAMENTO" in text
    assert "Texto clínico válido" in text
    assert "REFERÊNCIAS" not in text
    assert "Autor A" not in text
    assert "removed_trailing_nonclinical_section" in flags


def test_annex_section_does_not_truncate_following_pages() -> None:
    rows = [
        {"page": 1, "markdown": "## **1. INTRODUÇÃO**\nTexto clínico válido para manter."},
        {"page": 2, "markdown": "## **ANEXO I**\nTexto clínico complementar relevante."},
        {"page": 3, "markdown": "Continuação clínica do anexo com orientações relevantes."},
    ]

    results, stats, _doc_class = clean_pages(rows, config=CleanConfig(min_words=3))

    assert results[0].record["markdown"]
    assert "ANEXO I" in results[1].record["markdown"]
    assert results[1].skipped is False
    assert results[2].record["markdown"]
    assert results[2].skipped is False
    assert stats.pages_skipped == 0


def test_references_section_truncates_following_pages() -> None:
    rows = [
        {"page": 1, "markdown": "## **1. INTRODUÇÃO**\nTexto clínico válido para manter."},
        {"page": 2, "markdown": "## **REFERÊNCIAS**\n1. Autor A. Artigo bibliográfico."},
        {"page": 3, "markdown": "2. Autor B. Continuação bibliográfica."},
    ]

    results, stats, _doc_class = clean_pages(rows, config=CleanConfig(min_words=3))

    assert results[0].record["markdown"]
    assert results[1].record["markdown"] == ""
    assert results[1].skipped is True
    assert results[2].record["markdown"] == ""
    assert results[2].skipped is True
    assert results[2].skip_reason == "after_trailing_nonclinical_section"
    assert stats.pages_skipped == 2


def test_broken_repeated_table_header_block_is_removed() -> None:
    text, flags, _stats = clean_page_markdown(
        "Texto clínico antes.\n"
        "**Medicament** **o e dose** **máxima** | **Contraindicações** **para uso** | **Monitorizaçã** **o na** **utilização**\n"
        "-redução da hemoglobina; -sintomas extrapiramidais.\n"
        "**Medicament** **o e dose** **máxima** | **Contraindicações** **para uso** | **Monitorizaçã** **o na** **utilização**\n"
        "Risperidona: Até 6 mg/dia | - hipersensibilidade conhecida | -pressão arterial; -glicemia\n"
        "**Medicament** **o e dose** **máxima** | **Contraindicações** **para uso** | **Monitorizaçã** **o na** **utilização**\n"
        "Texto clínico depois.",
        repeated_keys=set(),
        config=CleanConfig(min_words=3),
    )

    assert "Medicament" not in text
    assert "Risperidona" not in text
    assert "Texto clínico antes." in text
    assert "Texto clínico depois." in text
    assert "removed_malformed_table" in flags


def test_clean_pages_preserves_pcdt_title_after_empty_first_page() -> None:
    rows = [
        {"page": 1, "markdown": ""},
        {
            "page": 2,
            "markdown": (
                "ANEXO\n"
                "PROTOCOLO CLÍNICO E DIRETRIZES TERAPÊUTICAS DO ACIDENTE VASCULAR CEREBRAL ISQUÊMICO AGUDO\n"
                "## **1. INTRODUÇÃO**\n"
                "O acidente vascular cerebral (AVC) é uma das principais causas de incapacidade e morte no mundo. "
                "O AVC isquêmico é o mais prevalente e o atendimento imediato pode prevenir sequelas e morte."
            ),
        },
    ]

    results, stats, doc_class = clean_pages(rows, config=CleanConfig(min_words=6))

    page_2 = results[1]
    assert results[0].record["markdown"] == ""
    assert page_2.skipped is False
    assert page_2.record["markdown"]
    assert "## PROTOCOLO CLÍNICO E DIRETRIZES TERAPÊUTICAS DO ACIDENTE VASCULAR" in page_2.record["markdown"]
    assert "## **1. INTRODUÇÃO**" in page_2.record["markdown"]
    assert "normalized_clinical_headings" in page_2.flags
    assert stats.pages_written == 1
    assert doc_class in {"pcdt_completo", "desconhecido"}


def test_clean_pages_marks_initial_admin_page_skipped() -> None:
    rows = [
        {"page": 1, "markdown": "PORTARIA SECTICS/MS Nº 59\nFERNANDA DE NEGRI"},
        {"page": 2, "markdown": "## ANEXO PROTOCOLO CLÍNICO\n## 1. INTRODUÇÃO\nTexto clínico relevante para análise."},
    ]
    results, stats, _doc_class = clean_pages(rows, config=CleanConfig(min_words=3))

    assert results[0].record["markdown"] == ""
    assert results[0].skipped is True
    assert results[0].skip_reason == "before_clinical_content"
    assert "skipped" not in results[0].record
    assert "cleaned" not in results[1].record
    assert stats.pages_skipped == 1


def test_clean_pages_jsonl_preserves_metadata_and_writes_cleaned_suffix(tmp_path: Path) -> None:
    path = tmp_path / "doc.pages.jsonl"
    path.write_text(
        json.dumps({"page": 1, "markdown": "## INTRODUÇÃO\ninterven-\nção clínica", "source": "x"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    stats, out, _doc_class = clean_pages_jsonl(path, config=CleanConfig(min_words=2))
    row = json.loads(out.read_text(encoding="utf-8").strip())

    assert out.name == "doc.pages.cleaned.jsonl"
    assert row["source"] == "x"
    assert "cleaned" not in row
    assert "cleaning_flags" not in row
    assert "document_class" not in row
    assert "intervenção" in row["markdown"]
    assert stats.pages_written == 1


def test_default_output_path_segregates_processed_pcdt_cleaned(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "llm" / "data"
    source = data / "processed" / "pcdt" / "doc.pages.jsonl"
    monkeypatch.setattr(cleaner_mod, "data_root", lambda: data)

    out = default_output_path(source)

    assert out == data / "processed" / "pcdt_cleaned" / "doc.pages.cleaned.jsonl"


def test_sidecar_stem_supports_cleaned_files() -> None:
    assert sidecar_stem(Path("abc.pages.jsonl")) == "abc"
    assert sidecar_stem(Path("abc.pages.cleaned.jsonl")) == "abc"
