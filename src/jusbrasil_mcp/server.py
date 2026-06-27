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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


async def get_client() -> JusBrasilClient:
    """Singleton preguicoso: abre o navegador na primeira chamada."""
    global _client
    async with _client_lock:
        if _client is None:
            _client = JusBrasilClient(
                # Scrapling StealthyFetcher passa o CF em headless puro (sem janela)
                headless=_env_bool("JUSBRASIL_HEADLESS", True),
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
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
) -> list[dict]:
    """Pesquisa jurisprudencia no JusBrasil.

    Args:
        query: termos de busca (ex: "dano moral atraso voo").
        limite: numero maximo de resultados (1-50). Padrao: 10.
        tribunal: filtro opcional (ex: "STF", "STJ", "TJSP").
        data_inicio: data inicial AAAA-MM-DD (opcional).
        data_fim: data final AAAA-MM-DD (opcional).

    Returns:
        Lista de dicts com titulo, tribunal, data, ementa, url.
    """
    limite = max(1, min(limite, 50))
    client = await get_client()
    resultados = await client.buscar_jurisprudencia(
        query=query,
        limite=limite,
        tribunal=tribunal,
        data_inicio=data_inicio,
        data_fim=data_fim,
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
