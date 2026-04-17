"""In-memory CID catalog used by /api/cids."""

from assistente_medico_api.schemas.cids import Cid

CID_LIST: list[Cid] = [
    Cid(code="L40.5", label="Artrite Psoriásica"),
    Cid(code="A41.9", label="Sepse não especificada"),
    Cid(code="T81.4", label="Infecção pós-procedimento cirúrgico"),
    Cid(code="E11.9", label="Diabetes Mellitus tipo 2 sem complicações"),
    Cid(code="I10", label="Hipertensão Essencial"),
    Cid(code="J18.9", label="Pneumonia não especificada"),
    Cid(code="N17.9", label="Insuficiência Renal Aguda"),
    Cid(code="K92.1", label="Melena"),
    Cid(code="I63.9", label="AVC Isquêmico"),
    Cid(code="M05.3", label="Artrite Reumatoide"),
    Cid(code="I50.0", label="Insuficiência Cardíaca Congestiva"),
    Cid(code="B34.9", label="Infecção viral não especificada"),
    Cid(code="R50.9", label="Febre não especificada"),
    Cid(code="R06.02", label="Dispneia de repouso"),
    Cid(code="D64.9", label="Anemia não especificada"),
    Cid(code="E87.1", label="Hiponatremia"),
    Cid(code="R57.0", label="Choque cardiogênico"),
    Cid(code="T78.4", label="Alergia não especificada"),
    Cid(code="Z87.891", label="História pessoal de alergia a medicamentos"),
    Cid(code="K85.9", label="Pancreatite aguda"),
    Cid(code="C50.9", label="Neoplasia maligna da mama"),
    Cid(code="G43.9", label="Enxaqueca"),
]


def list_cids() -> list[Cid]:
    return CID_LIST
