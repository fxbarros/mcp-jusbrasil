"""Testes de regressão do parser sobre fixtures reais (sem subir navegador).

As fixtures em tests/fixtures/ foram capturadas do JusBrasil e sanitizadas
(dados de conta removidos). Estes testes exercitam _parse_decisao e a citação
formatada por tribunal — o parser é independente da camada de fetch, então
roda offline e rápido.
"""
from pathlib import Path

import pytest

from jusbrasil_mcp.jusbrasil_client import JusBrasilClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def parser() -> JusBrasilClient:
    # start()/close() são no-op; instanciar não abre navegador
    return JusBrasilClient()


def _ler(parser, nome: str, url: str):
    html = (FIXTURES / nome).read_text(encoding="utf-8", errors="ignore")
    return parser._parse_decisao(html, url)


# --- TJ-PI: formato genérico ---

def test_tjpi_campos(parser):
    d = _ler(parser, "decisao_tjpi_apelacao.html",
             "https://www.jusbrasil.com.br/jurisprudencia/tj-pi/1629196340")
    assert d.tribunal == "TJ-PI"
    assert d.tipo == "Apelação Cível"
    assert d.numero_cnj == "0809276-22.2017.8.18.0140"
    assert d.relator == "José Francisco Do Nascimento"
    assert d.orgao_julgador == "2ª CÂMARA ESPECIALIZADA CÍVEL"
    assert d.data_julgamento == "05/08/2022"


def test_tjpi_citacao(parser):
    d = _ler(parser, "decisao_tjpi_apelacao.html",
             "https://www.jusbrasil.com.br/jurisprudencia/tj-pi/1629196340")
    assert d.citacao_abnt() == (
        "(TJ-PI - Apelação Cível: 0809276-22.2017.8.18.0140, "
        "Relator: José Francisco Do Nascimento, "
        "Data de Julgamento: 05/08/2022, 2ª CÂMARA ESPECIALIZADA CÍVEL)"
    )


# --- STJ: formato convencional (recurso + registro + DJe) ---

def test_stj_campos(parser):
    d = _ler(parser, "decisao_stj_aginteresp.html",
             "https://www.jusbrasil.com.br/jurisprudencia/stj/919807875")
    assert d.tribunal == "STJ"
    assert d.relator == "LUIS FELIPE SALOMÃO"
    assert d.orgao_julgador == "T4 - QUARTA TURMA"
    assert d.data_julgamento == "10/08/2020"
    assert d.data_publicacao == "DJe 13/08/2020"


def test_stj_citacao(parser):
    d = _ler(parser, "decisao_stj_aginteresp.html",
             "https://www.jusbrasil.com.br/jurisprudencia/stj/919807875")
    assert d.citacao_abnt() == (
        "(STJ - AgInt no REsp 1.846.222/RS (2019/0326486-1), "
        "Rel. Min. Luis Felipe Salomão, Quarta Turma, "
        "julgado em 10/08/2020, DJe 13/08/2020)"
    )


# --- sanidade: nenhuma fixture deve reintroduzir PII ---

@pytest.mark.parametrize("nome", ["decisao_tjpi_apelacao.html", "decisao_stj_aginteresp.html"])
def test_fixtures_sem_pii(nome):
    txt = (FIXTURES / nome).read_text(encoding="utf-8", errors="ignore").lower()
    for proibido in ("fabioxbarros", "ximenes", "fabio ximenes"):
        assert proibido not in txt, f"PII '{proibido}' encontrado em {nome}"
