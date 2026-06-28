"""Servidor MCP para busca de jurisprudencia no JusBrasil.

Uso:
    uv run python -m jusbrasil_mcp.server
    uv run jusbrasil-mcp

Conectado ao Claude Desktop, expoe a tool `buscar_jurisprudencia`.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .jusbrasil_client import JusBrasilClient


_client: Optional[JusBrasilClient] = None
_client_lock = asyncio.Lock()


async def get_client() -> JusBrasilClient:
    """Singleton preguicoso: abre o navegador na primeira chamada."""
    global _client
    async with _client_lock:
        if _client is None:
            _client = JusBrasilClient(
                # SEMPRE headless: nenhuma janela, 100% automatizado, sem
                # visualizacao para o usuario. Travado de proposito (nao usa env).
                headless=True,
                timeout_ms=int(os.getenv("JUSBRASIL_TIMEOUT_MS", "60000")),
            )
            await _client.start()
        return _client


@asynccontextmanager
async def lifespan(_app: FastMCP):
    try:
        yield
    finally:
        global _client
        if _client is not None:
            print("[LIFESPAN] Encerrando cliente...")
            await _client.close()
            _client = None


mcp = FastMCP(
    "jusbrasil",
    instructions=(
        "Servidor MCP para buscar jurisprudencia brasileira no JusBrasil. "
        "Use a tool `buscar_jurisprudencia` com termos livres em portugues."
    ),
    lifespan=lifespan,
)


@mcp.tool()
async def buscar_jurisprudencia(
    query: str,
    limite: int = 10,
    tribunal: Optional[str] = None,
    tipo: Optional[str] = None,
    periodo: Optional[str] = None,
    ordenacao: Optional[str] = None,
) -> list[dict]:
    """Pesquisa jurisprudencia no JusBrasil, com filtros reais do site.

    Args:
        query: termos de busca (ex: "dano moral atraso voo").
        limite: numero maximo de resultados (1-50). Padrao: 10.
        tribunal: filtra por sistema de tribunal. Valores: "STF", "STJ", "TST",
            "TJs" (todos os TJs), "TRFs", "TRTs", "TSE", "STM", "TCU". Aceita varios
            separados por virgula (ex: "STJ,STF"). (Filtro de tribunal especifico,
            tipo TJ-PI isolado, nao e suportado por este filtro de topo.)
        tipo: tipo de julgado. Valores: "acordao", "sumula", "decisao"
            (monocratica), "sentenca", "despacho", "orientacao".
        periodo: recorte de data por periodo recente. Valores: "7dias", "30dias",
            "365dias" (ou apelidos "ultima semana"/"ultimo mes"/"ultimo ano", ou um
            numero de dias). Obs.: o JusBrasil filtra por periodo relativo, nao por
            data inicial/final exata.
        ordenacao: "data" (mais recentes) ou "relevancia" (padrao).

    Returns:
        Lista de dicts com titulo, tribunal, numero_cnj, data, ementa, url.
    """
    limite = max(1, min(limite, 50))
    client = await get_client()
    resultados = await client.buscar_jurisprudencia(
        query=query, limite=limite, tribunal=tribunal,
        tipo=tipo, periodo=periodo, ordenacao=ordenacao,
    )
    return [r.to_dict() for r in resultados]


@mcp.tool()
async def ler_decisao(url: str) -> dict:
    """Le uma decisao individual do JusBrasil e extrai todos os metadados.

    Use APOS `buscar_jurisprudencia` para montar citacoes completas em peticoes.
    A busca da ementa curta; use esta tool para pegar os dados formais
    (relator, orgao julgador, data de julgamento) da decisao que voce quer citar.

    IMPORTANTE - ANTI-ALUCINACAO:
    - Se qualquer campo retornar None/vazio (especialmente `ementa`), NUNCA invente
      nem reconstrua o conteudo com base em memoria ou conhecimento geral.
    - Campos nulos indicam FALHA DE EXTRACAO ou AUSENCIA REAL no JusBrasil,
      nao sao convite para preencher com texto plausivel.
    - Verifique sempre o campo `_parse_warnings` no retorno. Se ele existir, siga
      estritamente suas instrucoes e comunique ao usuario.
    - Para uso em peticao, oriente o usuario a conferir o texto oficial
      diretamente no site do tribunal (scon.stj.jus.br, sites dos TJs, etc.).
    - JusBrasil eh agregador privado, NAO eh fonte oficial para citacao formal.

    Args:
        url: URL da decisao (ex: "https://www.jusbrasil.com.br/jurisprudencia/tj-pi/1629196340").
             Pegue a URL do campo `url` retornado por `buscar_jurisprudencia`.

    Returns:
        Dict com:
        - titulo, tribunal, tipo (Apelacao Civel, etc.)
        - numero_cnj (formato 0000000-00.0000.0.00.0000 pronto pra citacao)
        - relator, orgao_julgador, data_julgamento, data_publicacao
        - ementa (texto completo)
        - citacao_abnt: string ja formatada estilo "(TJ-PI - Apelacao Civel: NNN, Relator: ..., ...)"
    """
    client = await get_client()
    try:
        d = await client.ler_decisao(url)
    except Exception as e:
        raise RuntimeError(f"Falha ao ler decisao: {e}") from e
    out = d.to_dict()
    out["citacao_abnt"] = d.citacao_abnt()
    # Link de verificacao: pagina canonica no JusBrasil (confere ementa e inteiro teor)
    out["link_verificacao"] = d.url

    # Warnings defensivos: alertam o LLM consumidor quando campos criticos
    # nao foram extraidos, para impedir alucinacao de conteudo.
    warnings = []
    if not d.ementa:
        warnings.append(
            "ementa_nao_extraida: o parser nao conseguiu capturar a ementa desta decisao. "
            "NUNCA invente ou reconstrua o texto da ementa. Informe ao usuario que a ementa "
            "precisa ser consultada diretamente no site do tribunal antes de uso em peticao."
        )
    if not d.numero_cnj:
        warnings.append(
            "numero_cnj_nao_extraido: pode ser processo antigo sem CNJ ou falha de parser. "
            "Nao fabrique numeros de processo."
        )
    if not d.relator:
        warnings.append("relator_nao_extraido: nao fabrique nome de relator.")
    if not d.data_julgamento:
        warnings.append("data_julgamento_nao_extraida: nao fabrique datas.")
    if warnings:
        out["_parse_warnings"] = warnings
    return out


@mcp.tool()
async def buscar_sumulas(query: str, limite: int = 10, tribunal: Optional[str] = None) -> list[dict]:
    """Pesquisa sumulas no JusBrasil (usa o filtro real jurisType=sumula).

    Args:
        query: termos de busca (ex.: "negativacao indevida", "dano moral").
        limite: numero maximo de resultados (1-50). Padrao: 10.
        tribunal: opcional — filtra por sistema de tribunal ("STJ", "STF", "TST", ...).

    Returns:
        Lista de dicts com titulo, tribunal, numero_cnj, data, ementa, url.
    """
    limite = max(1, min(limite, 50))
    client = await get_client()
    resultados = await client.buscar_sumulas(query=query, limite=limite, tribunal=tribunal)
    return [r.to_dict() for r in resultados]


@mcp.tool()
async def ler_inteiro_teor(url: str) -> dict:
    """Extrai o TEXTO INTEGRAL de uma decisao (relatorio + voto + acordao completos).

    Diferente de `ler_decisao` (que traz so metadados + ementa), esta tool retorna
    o inteiro teor do julgado. EXIGE login (credenciais configuradas no Keychain);
    sem sessao autenticada o conteudo nao vem.

    IMPORTANTE - ANTI-ALUCINACAO:
    - Se `texto` voltar nulo/vazio, NUNCA invente o conteudo do acordao. Significa
      que o inteiro teor nao esta disponivel no JusBrasil para esta decisao, ou que
      a sessao nao esta autenticada. Informe o usuario e oriente a consultar o
      inteiro teor no site oficial do tribunal.
    - Verifique `_parse_warnings` no retorno e siga suas instrucoes.
    - JusBrasil eh agregador privado, NAO eh fonte oficial para citacao formal.

    Args:
        url: URL da decisao (ex.: ".../jurisprudencia/tj-pi/1629196340") OU a URL
             direta de inteiro teor (".../inteiro-teor-NNN").

    Returns:
        Dict com url, url_inteiro_teor, texto (texto integral), n_caracteres,
        autenticado (bool).
    """
    client = await get_client()
    try:
        it = await client.ler_inteiro_teor(url)
    except Exception as e:
        raise RuntimeError(f"Falha ao ler inteiro teor: {e}") from e
    out = it.to_dict()

    warnings = []
    if not it.autenticado:
        warnings.append(
            "sessao_nao_autenticada: nao ha credenciais no Keychain (servico "
            "'mcp-jusbrasil') ou o login falhou. O inteiro teor exige login. "
            "Configure as credenciais e tente de novo."
        )
    if not it.texto:
        warnings.append(
            "inteiro_teor_indisponivel: o JusBrasil nao forneceu o texto integral "
            "desta decisao. NUNCA invente ou reconstrua o acordao. Oriente o usuario "
            "a consultar o inteiro teor no site oficial do tribunal."
        )
    if warnings:
        out["_parse_warnings"] = warnings
    return out


@mcp.tool()
async def compilar_dossie(
    urls: list[str],
    incluir_inteiro_teor: bool = False,
    titulo: Optional[str] = None,
    caminho: Optional[str] = None,
) -> dict:
    """Compila varias decisoes/sumulas num UNICO documento Word (.docx).

    Para cada URL, monta uma secao com a citacao formatada, a ementa, o link de
    verificacao (JusBrasil) e, se pedido, o inteiro teor. Use depois de escolher,
    com `buscar_jurisprudencia`/`buscar_sumulas`, quais decisoes quer reunir.

    Args:
        urls: lista de URLs de decisoes/sumulas (campo `url` das buscas).
        incluir_inteiro_teor: se True, inclui o texto integral de cada decisao
            (mais lento; exige login e nem toda decisao tem inteiro teor).
        titulo: titulo do dossie (padrao: "Dossiê de Jurisprudência").
        caminho: caminho .docx de saida (padrao: ~/Downloads/<titulo>-<data>.docx).

    Returns:
        Dict com arquivo (caminho salvo), n_itens, n_falhas, com_inteiro_teor.
    """
    if not urls:
        raise ValueError("Informe ao menos uma URL.")
    client = await get_client()
    try:
        return await client.compilar_dossie(
            urls=urls, incluir_inteiro_teor=incluir_inteiro_teor,
            titulo=titulo, caminho=caminho,
        )
    except Exception as e:
        raise RuntimeError(f"Falha ao compilar dossie: {e}") from e


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
