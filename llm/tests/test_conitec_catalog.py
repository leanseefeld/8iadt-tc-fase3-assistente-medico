from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pcdt_ingest.chunk import chunk_pages_to_documents
from pcdt_ingest.embed import chroma_safe_metadata
from pcdt_ingest.extract import PageRecord
from pcdt_ingest.reference_data.conitec_catalog import (
    build_catalog_by_diretriz,
    expand_query_terms,
    load_conitec_xlsx,
    match_source_to_disease,
    metadata_from_catalog_entry,
    normalize_source_for_match,
    normalize_text_for_match,
    read_catalog_jsonl,
    write_catalog_jsonl,
)


def _fake_conitec_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Formato": "PCDT",
                "Diretriz": "Artrite Reativa",
                "Código da CID-10": "M02.1",
                "Descrição do Código da CID-10": "Artropatia pós-desentérica",
                "Medicamento": "Naproxeno",
                "Portaria da Diretriz": "Portaria Conjunta nº 1",
                "Data da Portaria": "2021-04-28",
                "Descrição das Siglas": "PCDT - Protocolo Clínico e Diretrizes Terapêuticas",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Artrite Reativa",
                "Código da CID-10": "M02.3",
                "Descrição do Código da CID-10": "Doença de Reiter",
                "Medicamento": "Naproxeno",
                "Portaria da Diretriz": "Portaria Conjunta nº 1",
                "Data da Portaria": "2021-04-28",
                "Descrição das Siglas": "PCDT - Protocolo Clínico e Diretrizes Terapêuticas",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Infecção pelo HIV",
                "Código da CID-10": "B24",
                "Descrição do Código da CID-10": "Doença pelo vírus da imunodeficiência humana",
                "Medicamento": "Dolutegravir",
                "Portaria da Diretriz": "Portaria Conjunta nº 2",
                "Data da Portaria": "2022-01-01",
                "Descrição das Siglas": "HIV - vírus da imunodeficiência humana",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Acidente Vascular Cerebral Isquêmico Agudo",
                "Código da CID-10": "I63",
                "Descrição do Código da CID-10": "Infarto cerebral",
                "Medicamento": "Alteplase",
                "Portaria da Diretriz": "Portaria Conjunta SAES-SCTIE/MS nº 06",
                "Data da Portaria": "2021-04-22",
                "Descrição das Siglas": "Protocolos Clínicos e Diretrizes Terapêuticas",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Acromegalia",
                "Código da CID-10": "E22.0",
                "Descrição do Código da CID-10": "Acromegalia e gigantismo hipofisário",
                "Medicamento": "Octreotida",
                "Portaria da Diretriz": "Portaria Conjunta SAES-SCTIE/MS nº 23",
                "Data da Portaria": "2022-01-01",
                "Descrição das Siglas": "Protocolos Clínicos e Diretrizes Terapêuticas",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Angioedema associado à deficiência de C1 esterase",
                "Código da CID-10": "D84.1",
                "Descrição do Código da CID-10": "Defeitos no sistema complemento",
                "Medicamento": "Icatibanto",
                "Portaria da Diretriz": "Portaria Conjunta SAES-SCTIE/MS nº 12",
                "Data da Portaria": "2016-01-01",
                "Descrição das Siglas": "Protocolos Clínicos e Diretrizes Terapêuticas",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Amiloidoses Associadas à Transtirretina",
                "Código da CID-10": "E85.1",
                "Descrição do Código da CID-10": "Amiloidose neuropática heredofamiliar",
                "Medicamento": "Tafamidis",
                "Portaria da Diretriz": "Portaria Conjunta nº 10",
                "Data da Portaria": "2021-01-01",
                "Descrição das Siglas": "TTR - transtirretina",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Artrite Idiopática Juvenil (AIJ)",
                "Código da CID-10": "M08.0",
                "Descrição do Código da CID-10": "Artrite reumatoide juvenil",
                "Medicamento": "Metotrexato",
                "Portaria da Diretriz": "Portaria Conjunta nº 11",
                "Data da Portaria": "2021-01-01",
                "Descrição das Siglas": "AIJ - artrite idiopática juvenil",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Anemia por Deficiência de Ferro",
                "Código da CID-10": "D50.9",
                "Descrição do Código da CID-10": "Anemia por deficiência de ferro não especificada",
                "Medicamento": "Sacarato de hidróxido férrico",
                "Portaria da Diretriz": "Portaria Conjunta nº 12",
                "Data da Portaria": "2014-01-01",
                "Descrição das Siglas": "PCDT",
            },
            {
                "Formato": "PCDT",
                "Diretriz": "Anemia na Doença Renal Crônica - Alfaepoetina",
                "Código da CID-10": "N18.0",
                "Descrição do Código da CID-10": "Doença renal em estádio final",
                "Medicamento": "Alfaepoetina",
                "Portaria da Diretriz": "Portaria Conjunta nº 13",
                "Data da Portaria": "2017-01-01",
                "Descrição das Siglas": "DRC - doença renal crônica",
            },
        ]
    )


def test_normalize_text_for_match() -> None:
    assert normalize_text_for_match("Artrite Reativa") == "artrite reativa"
    assert normalize_source_for_match("20210428_pcdt_artrite_reativa") == "artrite reativa"


def test_load_conitec_xlsx_and_normalize_columns(tmp_path: Path) -> None:
    xlsx = tmp_path / "conitec.xlsx"
    _fake_conitec_df().to_excel(xlsx, index=False)

    got = load_conitec_xlsx(xlsx)

    assert list(got.columns) == [
        "formato",
        "diretriz",
        "cid10_code",
        "cid10_description",
        "medicamento",
        "portaria_diretriz",
        "data_portaria",
        "descricao_siglas",
    ]
    assert got.loc[0, "diretriz"] == "Artrite Reativa"


def test_build_catalog_by_diretriz_deduplicates_and_sorts() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())
    entry = catalog["artrite reativa"]

    assert entry["disease"] == "Artrite Reativa"
    assert entry["cid10_codes"] == ["M02.1", "M02.3"]
    assert entry["medicamentos"] == ["Naproxeno"]
    assert entry["datas_portaria"] == ["2021-04-28"]


def test_catalog_jsonl_roundtrip(tmp_path: Path) -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())
    output = tmp_path / "pcdt_catalog.jsonl"

    write_catalog_jsonl(catalog, output)
    got = read_catalog_jsonl(output)

    assert got == catalog
    assert json.loads(output.read_text(encoding="utf-8").splitlines()[0])


def test_match_source_to_disease_exact_and_safe_partial() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())

    exact = match_source_to_disease("20210428_pcdt_artrite_reativa", catalog)
    partial = match_source_to_disease("portaria-no-2021-protocolo-artrite-reativa-final", catalog)

    assert exact is not None
    assert exact["disease"] == "Artrite Reativa"
    assert partial is not None
    assert partial["disease"] == "Artrite Reativa"


def test_match_source_to_disease_repairs_real_pcdt_stems() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())

    avc = match_source_to_disease("tromb-lise-no-acidente-vascular-cerebral-isqu-mico-agudo", catalog)
    acromegalia = match_source_to_disease("portaria-no-23-pcdt-acromegalia", catalog)
    angioedema = match_source_to_disease("pcdt_angioedema-deficincia-c1esterase_2016", catalog)

    assert avc is not None
    assert avc["disease"] == "Acidente Vascular Cerebral Isquêmico Agudo"
    assert acromegalia is not None
    assert acromegalia["disease"] == "Acromegalia"
    assert angioedema is not None
    assert angioedema["disease"] == "Angioedema associado à deficiência de C1 esterase"


def test_match_source_to_disease_handles_compact_and_inferred_titles() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())

    amiloidose = match_source_to_disease("AmiloidosesAssociadasaTranstirretina", catalog)
    juvenil = match_source_to_disease("pcdt-da-artrite-idiopatica-juvenil", catalog)
    anemia = match_source_to_disease(
        "pcdt_anemia_deficienciaferro_2014",
        catalog,
        candidate_texts=["Anemia por Deficiência de Ferro"],
    )
    anemia_drc = match_source_to_disease(
        "pcdt_anemia_doencarenalcronica",
        catalog,
        candidate_texts=["ANEMIA NA DOENÇA RENAL CRÔNICA - ALFAEPOETINA"],
    )

    assert amiloidose is not None
    assert amiloidose["disease"] == "Amiloidoses Associadas à Transtirretina"
    assert juvenil is not None
    assert juvenil["disease"] == "Artrite Idiopática Juvenil (AIJ)"
    assert anemia is not None
    assert anemia["disease"] == "Anemia por Deficiência de Ferro"
    assert anemia_drc is not None
    assert anemia_drc["disease"] == "Anemia na Doença Renal Crônica - Alfaepoetina"


def test_match_source_to_disease_repairs_catalog_alias_fallbacks() -> None:
    disease_names = [
        "Sobrepesso e Obesidade em Adultos",
        "Insuficiência Adrenal",
        "Prevenção de Tromboembolismo Venoso em Gestantes com Trombofilia",
        "Comportamento Agressivo no Transtorno do Espectro do Autismo",
        "Lúpus Eritematoso Sistêmico",
        "Síndrome de Falência Medular",
        "Degeneração Macular Relacionada à Idade",
        "Dor Crônica",
        "Hiperplasia Adrenal Congênita",
        "Imunodeficiência Primária com predominância de defeitos de anticorpos",
        "Leiomioma de Útero",
        "Doença de Paget",
        "Hemoglobinúria Paroxística Noturna",
        "Carcinoma Diferenciado da Tireoide",
        "Deficiência do Hormônio de Crescimento - Hipopituitarismo",
        "Hemangioma Infantil",
        "Homocistinúria Clássica",
        "Imunossupressão no Transplante Hepático em Adulto",
        "Imunossupressão no Transplante Hepático em Pediatria",
        "Insuficiência Pancreática Exócrina",
        "Mucopolissacaridose tipo VI",
        "Síndrome Nefrótica Primária em Crianças e Adolescentes",
        "Transtorno Afetivo Bipolar do tipo I",
        "Púrpura Trombocitopênica Idiopática",
        "Diabete Melito Tipo 1",
        "Diabete Melito Tipo 2",
        "Doença de Pompe",
        "Uveítes não Infecciosas",
        "Transtorno do Déficit de Atenção com Hiperatividade",
        "Lipofuscinose Ceroide Neuronal tipo 2",
        (
            "Manejo da Infecção pelo HIV em Crianças e Adolescentes - Módulo 1 - Diagnóstico, "
            "Manejo e Acompanhamento de Crianças Expostas ao HIV"
        ),
        "Hidradenite Supurativa",
        "Glaucoma",
    ]
    catalog = {
        normalize_text_for_match(disease): {
            "disease": disease,
            "disease_normalized": normalize_text_for_match(disease),
            "diretriz": disease,
            "diretriz_normalized": normalize_text_for_match(disease),
        }
        for disease in disease_names
    }

    expected_by_source = {
        "20201113_pcdt_sobrepeso_e_obesidade_em_adultos_29_10_2020_final": "Sobrepesso e Obesidade em Adultos",
        "20210701_portaria_conjunta_pcdt_insuficencia_adrenal": "Insuficiência Adrenal",
        "20211230_portal-portaria-conjunta_pcdt_trombofilia_gestantes": (
            "Prevenção de Tromboembolismo Venoso em Gestantes com Trombofilia"
        ),
        "20220419_portal-portaria_conjunta_7_comportamento_agressivo_tea": (
            "Comportamento Agressivo no Transtorno do Espectro do Autismo"
        ),
        "20221109_pcdt_lupus": "Lúpus Eritematoso Sistêmico",
        "20221109_pcdt_sindrome_falencias_medulares": "Síndrome de Falência Medular",
        "20221216_pcdt-dmri": "Degeneração Macular Relacionada à Idade",
        "dorcronica-1": "Dor Crônica",
        "pcdt-hiperplasia-adrenal-congenita-livro-2010": "Hiperplasia Adrenal Congênita",
        "pcdt-imunodeficienciaprimaria": "Imunodeficiência Primária com predominância de defeitos de anticorpos",
        "pcdt-leiomioma_31_10_2017": "Leiomioma de Útero",
        "pcdt-paget": "Doença de Paget",
        "pcdt__hpn": "Hemoglobinúria Paroxística Noturna",
        "pcdt_carcinomatireoide": "Carcinoma Diferenciado da Tireoide",
        "pcdt_deficienciadohormoniodecrescimento_2018": "Deficiência do Hormônio de Crescimento - Hipopituitarismo",
        "pcdt_hemangiomainfantil": "Hemangioma Infantil",
        "pcdt_homocistinriaclassica": "Homocistinúria Clássica",
        "pcdt_imunossupressao-pos-transplante-hepatico": "Imunossupressão no Transplante Hepático em Adulto",
        "pcdt_imunossupressonotransplantehepaticoempediatria": "Imunossupressão no Transplante Hepático em Pediatria",
        "pcdt_insuficienciapancreaticaexocrina-fev2016": "Insuficiência Pancreática Exócrina",
        "pcdt_mucopolissacaridosetipovi": "Mucopolissacaridose tipo VI",
        "pcdt_sindromenefroticaprimaria_criancasadolescentes-1": (
            "Síndrome Nefrótica Primária em Crianças e Adolescentes"
        ),
        "pcdt_transtornoafetivobipolar_tipoi": "Transtorno Afetivo Bipolar do tipo I",
        "portaria-conjunta-no-41-pcdt-trombocitopenia": "Púrpura Trombocitopênica Idiopática",
        "portaria-conjunta-pcdt-diabete-melito-1": "Diabete Melito Tipo 1",
        "portaria-conjunta-pcdt-doena-de-pompe10-08-2020": "Doença de Pompe",
        "portaria-conjunta-pcdt-uveites_saes": "Uveítes não Infecciosas",
        "portariaconjuntan14pcdttranstornododeficitdeatencaocomhiperatividadetdah": (
            "Transtorno do Déficit de Atenção com Hiperatividade"
        ),
        "portariaconjuntano8pcdtlipofuscinoseceroideneuronaltipo2": "Lipofuscinose Ceroide Neuronal tipo 2",
        (
            "protocolo-clinico-e-diretrizes-terapeuticas-para-manejo-da-infeccao-pelo-hiv-em-criancas-e-"
            "adolescentes-modulo-2-diagnostico-manejo-e-tratamento-de-criancas-e-adolescentes-vivendo-"
        ): (
            "Manejo da Infecção pelo HIV em Crianças e Adolescentes - Módulo 1 - Diagnóstico, "
            "Manejo e Acompanhamento de Crianças Expostas ao HIV"
        ),
        "site-de-portaria-conjunta-14_pcdthidradernite-supurativa": "Hidradenite Supurativa",
        "site_portaria-conjunta-n-11_pcdt_glaucoma_02_04_2018": "Glaucoma",
    }

    for source, expected in expected_by_source.items():
        match = match_source_to_disease(source, catalog)
        assert match is not None, source
        assert match["disease"] == expected


def test_match_source_to_disease_rejects_weak_match() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())

    assert match_source_to_disease("pcdt_artrite", catalog) is None
    assert match_source_to_disease("pcdt_doenca_desconhecida", catalog) is None


def test_chunk_metadata_prefers_conitec_catalog() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())
    docs = chunk_pages_to_documents(
        [PageRecord(page=1, markdown="1 INTRODUÇÃO\nTexto clínico suficiente para chunk.")],
        source_stem="20210428_pcdt_artrite_reativa",
        source_pdf_rel="raw/pcdt/20210428_pcdt_artrite_reativa.pdf",
        chunk_tokens=200,
        overlap_tokens=0,
        conitec_catalog=catalog,
    )

    meta = docs[0].metadata
    assert meta["disease"] == "Artrite Reativa"
    assert meta["disease_normalized"] == "artrite reativa"
    assert meta["metadata_source"] == "conitec_xlsx"
    assert meta["cid10_codes"] == ["M02.1", "M02.3"]
    assert "cid10_codes_text" not in meta
    assert "cid10_descriptions_text" not in meta
    assert "medicamentos_text" not in meta
    assert "portarias_text" not in meta
    assert "datas_portaria_text" not in meta
    assert "descricao_siglas_text" not in meta


def test_chunk_metadata_falls_back_to_heuristic_when_no_match() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())
    docs = chunk_pages_to_documents(
        [PageRecord(page=1, markdown="1 INTRODUÇÃO\nTexto clínico suficiente para chunk.")],
        source_stem="pcdt_doenca_teste",
        source_pdf_rel="raw/pcdt/pcdt_doenca_teste.pdf",
        chunk_tokens=200,
        overlap_tokens=0,
        conitec_catalog=catalog,
    )

    meta = docs[0].metadata
    assert meta["disease"] == "Doenca Teste"
    assert meta["metadata_source"] == "heuristic"
    assert meta["cid10_codes"] == []
    assert "cid10_codes_text" not in meta
    assert "cid10_descriptions_text" not in meta
    assert "medicamentos_text" not in meta
    assert "portarias_text" not in meta
    assert "datas_portaria_text" not in meta
    assert "descricao_siglas_text" not in meta


def test_metadata_serialization_for_chroma() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())
    meta = metadata_from_catalog_entry(catalog["artrite reativa"])

    safe = chroma_safe_metadata(meta)

    assert safe["cid10_codes"] == '["M02.1", "M02.3"]'
    assert "cid10_codes_text" not in safe
    assert "cid10_descriptions_text" not in safe
    assert "medicamentos_text" not in safe
    assert "portarias_text" not in safe
    assert "datas_portaria_text" not in safe
    assert "descricao_siglas_text" not in safe


def test_expand_query_terms_for_hiv() -> None:
    catalog = build_catalog_by_diretriz(_fake_conitec_df())

    terms = expand_query_terms("conduta para HIV", catalog)

    assert "Infecção pelo HIV" in terms
    assert "B24" in terms
    assert "Dolutegravir" in terms
