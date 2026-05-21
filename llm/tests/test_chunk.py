from __future__ import annotations

from pcdt_ingest.chunk import (
    chunk_pages_to_documents,
    infer_disease_name,
    normalize_pcdt_markdown_headers,
)
from pcdt_ingest.extract import PageRecord


def test_normalize_pcdt_markdown_headers_main_sections() -> None:
    got = normalize_pcdt_markdown_headers(
        "1 INTRODUÇÃO\n"
        "Texto introdutório.\n\n"
        "3 DIAGNÓSTICO\n"
        "Texto diagnóstico."
    )

    assert "## INTRODUÇÃO\nTexto introdutório." in got
    assert "## DIAGNÓSTICO\nTexto diagnóstico." in got


def test_normalize_pcdt_markdown_headers_subsection() -> None:
    got = normalize_pcdt_markdown_headers("1.1 Critérios laboratoriais\nTexto.")

    assert got == "### Critérios laboratoriais\nTexto."


def test_normalize_pcdt_markdown_headers_uppercase_clinical_title() -> None:
    got = normalize_pcdt_markdown_headers(
        "ANGIOEDEMA HEREDITÁRIO ASSOCIADO À DEFICIÊNCIA DE C1 ESTERASE (C1-INH)\n"
        "Texto introdutório."
    )

    assert got.startswith("## ANGIOEDEMA HEREDITÁRIO ASSOCIADO À DEFICIÊNCIA DE C1 ESTERASE (C1-INH)")


def test_infer_disease_name_from_title_regex() -> None:
    disease = infer_disease_name(
        source_stem="arquivo_generico",
        source_pdf_rel="raw/pcdt/arquivo_generico.pdf",
        full_text="Protocolo Clínico e Diretrizes Terapêuticas de Esclerose Múltipla\n## INTRODUÇÃO",
        first_pages_text=None,
    )

    assert disease == "Esclerose Múltipla"


def test_infer_disease_name_from_title_without_preposition() -> None:
    disease = infer_disease_name(
        source_stem="pcdt_anemia_doencarenalcronica",
        source_pdf_rel="raw/pcdt/pcdt_anemia_doencarenalcronica.pdf",
        full_text=(
            "PROTOCOLO CLÍNICO E DIRETRIZES TERAPÊUTICAS "
            "ANEMIA NA DOENÇA RENAL CRÔNICA - ALFAEPOETINA\n"
            "1. INTRODUÇÃO"
        ),
        first_pages_text=None,
    )

    assert disease == "ANEMIA NA DOENÇA RENAL CRÔNICA - ALFAEPOETINA"


def test_infer_disease_name_from_source_stem() -> None:
    disease = infer_disease_name(
        source_stem="pcdt_artrite_reumatoide_2024",
        source_pdf_rel="raw/pcdt/pcdt_artrite_reumatoide_2024.pdf",
        full_text="Texto sem título claro.",
        first_pages_text=None,
    )

    assert disease == "Artrite Reumatoide"


def test_chunk_metadata_uses_uppercase_clinical_title_as_section() -> None:
    pages = [
        PageRecord(
            page=2,
            markdown=(
                "ANGIOEDEMA HEREDITÁRIO ASSOCIADO À DEFICIÊNCIA DE C1 ESTERASE (C1-INH)\n"
                "Texto introdutório sobre a condição clínica e seu manejo."
            ),
        ),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="pcdt_angioedema-deficincia-c1esterase_2016",
        source_pdf_rel="raw/pcdt/pcdt_angioedema-deficincia-c1esterase_2016.pdf",
        chunk_tokens=200,
        overlap_tokens=0,
        chunk_strategy="recursive",
    )

    assert len(docs) == 1
    meta = docs[0].metadata
    assert meta["section"] == "ANGIOEDEMA HEREDITÁRIO ASSOCIADO À DEFICIÊNCIA DE C1 ESTERASE (C1-INH)"
    assert meta["header_1"] == "ANGIOEDEMA HEREDITÁRIO ASSOCIADO À DEFICIÊNCIA DE C1 ESTERASE (C1-INH)"
    assert meta["disease"] == "Angioedema Deficiencia C1 Esterase"
    assert "disease_inference_method" not in meta
    assert "disease_confidence" not in meta


def test_infer_disease_name_does_not_use_methodology_section_as_disease() -> None:
    disease = infer_disease_name(
        source_stem="pcdt_anemia_deficienciaferro_2014",
        source_pdf_rel="raw/pcdt/pcdt_anemia_deficienciaferro_2014.pdf",
        full_text=(
            "1 METODOLOGIA DE BUSCA E AVALIAÇÃO DA LITERATURA\n"
            "Na base de dados Cochrane foram encontradas revisões sistemáticas."
        ),
        first_pages_text=None,
    )

    assert disease == "Anemia por Deficiência de Ferro"


def test_recursive_chunk_can_cross_page_boundary_and_has_metadata() -> None:
    pages = [
        PageRecord(page=1, markdown="1 INTRODUÇÃO\nPaciente com doença crônica em acompanhamento contínuo"),
        PageRecord(page=2, markdown="e necessidade de monitoramento clínico regular para ajuste de conduta."),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="pcdt_doenca_teste",
        source_pdf_rel="raw/pcdt/pcdt_doenca_teste.pdf",
        chunk_tokens=200,
        overlap_tokens=0,
        chunk_strategy="recursive",
    )

    assert len(docs) == 1
    meta = docs[0].metadata
    assert meta["page_range"] == [1, 2]
    assert meta["chunk_strategy"] == "recursive"
    assert meta["disease"] == "Doenca Teste"
    assert meta["section"] == "INTRODUÇÃO"
    assert meta["header_1"] == "INTRODUÇÃO"


def test_recursive_sentence_chunking_honors_overlap() -> None:
    pages = [
        PageRecord(
            page=1,
            markdown=(
                "1 INTRODUÇÃO\n"
                "Primeira sentença clínica com dados relevantes para o caso. "
                "Segunda sentença clínica com monitoramento e tratamento descritos. "
                "Terceira sentença clínica com critérios e acompanhamento detalhados."
            ),
        ),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="pcdt_doenca_teste",
        source_pdf_rel="raw/pcdt/pcdt_doenca_teste.pdf",
        chunk_tokens=75,
        overlap_tokens=25,
        chars_per_token=1,
        chunk_strategy="recursive",
    )

    assert len(docs) >= 2
    assert "relevantes para o caso." in docs[1].page_content


def test_semantic_strategy_uses_single_splitter_and_metadata(monkeypatch) -> None:
    class FakeSemanticSplitter:
        def __init__(self) -> None:
            self.calls = 0

        def split_text(self, text: str) -> list[str]:
            self.calls += 1
            return [text]

    splitter = FakeSemanticSplitter()

    def fake_build_semantic_splitter(**_kwargs):
        return splitter

    monkeypatch.setattr("pcdt_ingest.chunk.build_semantic_splitter", fake_build_semantic_splitter)
    pages = [
        PageRecord(
            page=1,
            markdown=(
                "Protocolo Clínico e Diretrizes Terapêuticas de Doença Semântica\n"
                "3 DIAGNÓSTICO\n"
                "Texto diagnóstico que continua"
            ),
        ),
        PageRecord(page=2, markdown="na página seguinte sem nova seção."),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="generico",
        source_pdf_rel="raw/pcdt/generico.pdf",
        chunk_tokens=200,
        overlap_tokens=0,
        chunk_strategy="semantic",
    )

    assert docs
    assert splitter.calls >= 1
    doc = next(doc for doc in docs if doc.metadata["section"] == "DIAGNÓSTICO")
    meta = doc.metadata
    assert meta["chunk_strategy"] == "semantic"
    assert meta["page_range"] == [1, 2]
    assert meta["disease"] == "Doença Semântica"
    assert meta["section"] == "DIAGNÓSTICO"


def test_semantic_chunks_do_not_overlap_across_sections(monkeypatch) -> None:
    class FakeSemanticSplitter:
        def split_text(self, text: str) -> list[str]:
            return [text]

    monkeypatch.setattr("pcdt_ingest.chunk.build_semantic_splitter", lambda **_kwargs: FakeSemanticSplitter())
    pages = [
        PageRecord(
            page=1,
            markdown=(
                "## METODOLOGIA DE BUSCA E AVALIAÇÃO DA LITERATURA\n"
                "Foram consultadas bases bibliográficas e diretrizes clínicas relevantes.\n\n"
                "## INTRODUÇÃO\n"
                "A anemia é uma complicação frequente da doença renal crônica."
            ),
        ),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="pcdt_irc_ferro",
        source_pdf_rel="raw/pcdt/pcdt_irc_ferro.pdf",
        chunk_tokens=200,
        overlap_tokens=12,
        chars_per_token=1,
        chunk_strategy="semantic",
    )

    intro = next(doc for doc in docs if doc.metadata["section"] == "INTRODUÇÃO")
    assert intro.page_content.startswith("A anemia é uma complicação")
    assert "relevantes." not in intro.page_content


def test_semantic_chunks_get_final_overlap_inside_same_section(monkeypatch) -> None:
    class FakeSemanticSplitter:
        def split_text(self, text: str) -> list[str]:
            return [
                (
                    "Primeiro bloco clínico com histórico, achados laboratoriais, avaliação inicial, "
                    "sintomas relevantes e necessidade de acompanhamento longitudinal."
                ),
                (
                    "Segundo bloco clínico com conduta, seguimento, doses, exames, monitoramento "
                    "e reavaliação periódica."
                ),
            ]

    monkeypatch.setattr("pcdt_ingest.chunk.build_semantic_splitter", lambda **_kwargs: FakeSemanticSplitter())
    pages = [
        PageRecord(
            page=1,
            markdown=(
                "## INTRODUÇÃO\n"
                "Primeiro bloco clínico com histórico, achados laboratoriais, avaliação inicial, "
                "sintomas relevantes e necessidade de acompanhamento longitudinal. "
                "Segundo bloco clínico com conduta, seguimento, doses, exames, monitoramento "
                "e reavaliação periódica."
            ),
        ),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="pcdt_irc_ferro",
        source_pdf_rel="raw/pcdt/pcdt_irc_ferro.pdf",
        chunk_tokens=200,
        overlap_tokens=12,
        chars_per_token=1,
        chunk_strategy="semantic",
    )

    assert len(docs) == 2
    assert docs[1].page_content.startswith("ongitudinal.")
    assert docs[1].metadata["section"] == "INTRODUÇÃO"


def test_semantic_strategy_merges_tiny_biomedical_fragments(monkeypatch) -> None:
    class FragmentingSemanticSplitter:
        def split_text(self, _text: str) -> list[str]:
            return [
                "A artrite reativa é associada a patógenos como _Y.",
                "enterocolítica_ e _Y.",
                "pseudotuberculosis_, além de _Salmonella_ sp. O quadro clínico costuma ser oligoarticular.",
            ]

    monkeypatch.setattr("pcdt_ingest.chunk.build_semantic_splitter", lambda **_kwargs: FragmentingSemanticSplitter())
    pages = [
        PageRecord(
            page=1,
            markdown=(
                "1 INTRODUÇÃO\n"
                "A artrite reativa é associada a patógenos como _Y. enterocolítica_ e _Y. "
                "pseudotuberculosis_, além de _Salmonella_ sp. O quadro clínico costuma ser oligoarticular."
            ),
        ),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="pcdt_artrite_reativa",
        source_pdf_rel="raw/pcdt/pcdt_artrite_reativa.pdf",
        chunk_tokens=400,
        overlap_tokens=0,
        chunk_strategy="semantic",
    )

    assert len(docs) == 1
    assert "_Y. enterocolítica_ e _Y. pseudotuberculosis_" in docs[0].page_content


def test_semantic_chunks_are_strictly_capped_after_merges(monkeypatch) -> None:
    class OversizedSemanticSplitter:
        def split_text(self, _text: str) -> list[str]:
            return [
                "A" * 90,
                "continua " + ("B" * 90),
                "continua " + ("C" * 90),
            ]

    monkeypatch.setattr("pcdt_ingest.chunk.build_semantic_splitter", lambda **_kwargs: OversizedSemanticSplitter())
    pages = [
        PageRecord(
            page=1,
            markdown=(
                "## TRATAMENTO\n"
                + "A" * 90
                + " continua "
                + "B" * 90
                + " continua "
                + "C" * 90
            ),
        ),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="pcdt_teste_limite",
        source_pdf_rel="raw/pcdt/pcdt_teste_limite.pdf",
        chunk_tokens=100,
        overlap_tokens=0,
        chars_per_token=1,
        chunk_strategy="semantic",
    )

    assert len(docs) > 1
    assert all(len(doc.page_content) <= 100 for doc in docs)


def test_final_overlap_never_exceeds_chunk_token_limit(monkeypatch) -> None:
    class TwoChunkSemanticSplitter:
        def split_text(self, _text: str) -> list[str]:
            return [
                "Primeiro bloco com conteúdo clínico suficiente para formar uma cauda longa.",
                "Segundo bloco com conteúdo clínico que já está próximo do limite permitido.",
            ]

    monkeypatch.setattr("pcdt_ingest.chunk.build_semantic_splitter", lambda **_kwargs: TwoChunkSemanticSplitter())
    pages = [
        PageRecord(
            page=1,
            markdown=(
                "## TRATAMENTO\n"
                "Primeiro bloco com conteúdo clínico suficiente para formar uma cauda longa. "
                "Segundo bloco com conteúdo clínico que já está próximo do limite permitido."
            ),
        ),
    ]

    docs = chunk_pages_to_documents(
        pages,
        source_stem="pcdt_teste_overlap_limite",
        source_pdf_rel="raw/pcdt/pcdt_teste_overlap_limite.pdf",
        chunk_tokens=80,
        overlap_tokens=40,
        chars_per_token=1,
        chunk_strategy="semantic",
    )

    assert docs
    assert all(len(doc.page_content) <= 80 for doc in docs)
