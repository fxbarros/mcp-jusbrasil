"""Cliente JusBrasil via Scrapling (StealthyFetcher headless, sem login).

Migrado de patchright (login 2-etapas + sessao persistente + Chrome headed off-screen)
para o StealthyFetcher do Scrapling:
  - passa o Cloudflare em HEADLESS puro (validado: 4/4 com perfil limpo);
  - dispensa login — relator real vem do campo `chairman` do Apollo e o CNJ real
    de `enrichedContents...informacoes_gerais.numero_processo` (ver _cnj_real_do_apollo),
    ambos NAO mascarados mesmo anonimo.

O PARSER (_parse_decisao / _parse_next_data / _parse_resultados / Decisao / citacao_abnt)
foi preservado verbatim — a migracao troca apenas como o HTML chega.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from scrapling.fetchers import StealthyFetcher

URL_BASE = "https://www.jusbrasil.com.br"
URL_BUSCA = f"{URL_BASE}/jurisprudencia/busca"
# Perfil persistente proprio (cookies cf_clearance reaproveitados entre chamadas)
USER_DATA_DIR = Path.home() / ".mcp-jusbrasil-scrapling-profile"


@dataclass
class Resultado:
    titulo: str
    tribunal: Optional[str]
    numero_cnj: Optional[str]
    data: Optional[str]
    ementa: Optional[str]
    url: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)



# Mapa de tribunais: usuario pode dizer "TJPI", "TJ-PI", "tj pi",
# "Tribunal de Justiça do Piauí" -> convertemos pro slug "tj_pi"
@dataclass
class Decisao:
    """Metadados completos de uma decisao individual."""
    url: str
    titulo: Optional[str]
    tribunal: Optional[str]
    tipo: Optional[str]
    numero_cnj: Optional[str]
    relator: Optional[str]
    data_julgamento: Optional[str]
    data_publicacao: Optional[str]
    orgao_julgador: Optional[str]
    ementa: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def citacao_abnt(self) -> str:
        """Monta citacao por tribunal. STJ usa formato proprio (recurso + registro)."""
        if (self.tribunal or "").upper() == "STJ":
            return self._citacao_stj()
        return self._citacao_default()

    def _citacao_default(self) -> str:
        """Formato generico para TJs, TRFs, TST."""
        head = ""
        if self.tribunal:
            head = self.tribunal
        if self.tipo:
            head = f"{head} - {self.tipo}" if head else self.tipo
        if self.numero_cnj:
            head = f"{head}: {self.numero_cnj}" if head else self.numero_cnj
        extras = []
        if self.relator:
            extras.append(f"Relator: {self.relator}")
        if self.data_julgamento:
            extras.append(f"Data de Julgamento: {self.data_julgamento}")
        if self.orgao_julgador:
            extras.append(self.orgao_julgador)
        joined = ", ".join([p for p in [head, *extras] if p])
        return f"({joined})" if joined else ""

    def _citacao_stj(self) -> str:
        """Formato STJ convencional: (STJ - AgInt no REsp 1.846.222/RS (2019/0326486-1),
        Rel. Min. Luis Felipe Salomao, Quarta Turma, julgado em DD/MM/YYYY, DJe DD/MM/YYYY)."""
        recurso = None
        if self.titulo:
            m = re.search(r":\s*(.+?)\s+(\d+)\s+([A-Z]{2})\s+(\d{4}/\d{7}-\d)\s*$", self.titulo)
            if m:
                tipo_rec, num, uf, registro = m.group(1).strip(), m.group(2), m.group(3), m.group(4)
                num_fmt = f"{int(num):,}".replace(",", ".")
                recurso = f"{tipo_rec} {num_fmt}/{uf} ({registro})"

        if recurso:
            head = f"STJ - {recurso}"
        elif self.numero_cnj:
            head = f"STJ - {self.numero_cnj}"
        else:
            head = "STJ"

        extras = []
        if self.relator:
            extras.append(f"Rel. Min. {_title_case_pt(self.relator)}")
        if self.orgao_julgador:
            extras.append(_orgao_stj_extenso(self.orgao_julgador))
        if self.data_julgamento:
            extras.append(f"julgado em {self.data_julgamento}")
        if self.data_publicacao:
            dp = self.data_publicacao
            if not dp.lower().startswith("dje"):
                dp = f"DJe {dp}"
            extras.append(dp)

        return f"({', '.join([head] + extras)})"



def formatar_cnj(numero_raw):
    """Converte numero cru em formato CNJ.
    Ex.: '7034194820198180000' -> '0703419-48.2019.8.18.0000'
    """
    if not numero_raw:
        return None
    digitos = re.sub(r"\D", "", str(numero_raw))
    if not digitos:
        return None
    digitos = digitos.zfill(20)
    if len(digitos) != 20:
        return None
    m = re.match(r"(\d{7})(\d{2})(\d{4})(\d{1})(\d{2})(\d{4})", digitos)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}.{m.group(3)}.{m.group(4)}.{m.group(5)}.{m.group(6)}"


_SIGLAS_ESPECIAIS = {
    "STF", "STJ", "TST", "TSE", "STM", "TCU", "TNU", "TRU", "CNJ", "CARF"
}

_NOMES_EXTENSOS = {
    "tribunal de justica do piaui": "tj_pi",
    "tribunal de justica de sao paulo": "tj_sp",
    "tribunal de justica do rio de janeiro": "tj_rj",
    "tribunal de justica de minas gerais": "tj_mg",
    "tribunal de justica do rio grande do sul": "tj_rs",
    "supremo tribunal federal": "stf",
    "superior tribunal de justica": "stj",
    "tribunal superior do trabalho": "tst",
    "tribunal superior eleitoral": "tse",
}


def _normalizar_tribunal(tribunal: str) -> str:
    """Converte qualquer jeito que o usuario escreva num slug do JusBrasil.

    Exemplos:
      "TJPI"  -> "tj_pi"
      "TJ-PI" -> "tj_pi"
      "tj pi" -> "tj_pi"
      "STF"   -> "stf"
      "Tribunal de Justiça do Piauí" -> "tj_pi"
    """
    import unicodedata
    if not tribunal:
        return ""
    # Normaliza acentos e caixa (o mapa acima esta sem acento)
    raw = unicodedata.normalize("NFKD", tribunal).encode("ascii", "ignore").decode().lower().strip()
    # Nome extenso conhecido?
    if raw in _NOMES_EXTENSOS:
        return _NOMES_EXTENSOS[raw]
    # Tira separadores
    t = re.sub(r"[\s\-.]+", "", tribunal.upper())
    # Siglas especiais (STF, STJ, TST, etc.)
    if t in _SIGLAS_ESPECIAIS:
        return t.lower()
    # Padroes TJ-XX, TRF-X, TRT-X, TRE-XX, TJM-XX, TCE-XX
    m = re.match(r"^(TJ|TRF|TRT|TRE|TJM|TCE)([A-Z0-9]+)$", t)
    if m:
        return f"{m.group(1).lower()}_{m.group(2).lower()}"
    # Fallback: retorna lower sem pontuacao
    return re.sub(r"[\s\-.]+", "_", tribunal.lower())


class JusBrasilClient:
    """Fetch via Scrapling StealthyFetcher (headless, sem login); parser preservado.

    Mesma interface da versao patchright (start/close/buscar/ler) para o server.py
    continuar funcionando sem mudancas. start()/close() viraram no-op porque o
    StealthyFetcher gerencia o proprio navegador a cada chamada.
    """

    def __init__(self, headless: bool = True, timeout_ms: int = 60_000):
        self.headless = headless
        self.timeout_ms = max(timeout_ms, 60_000)  # solve_cloudflare precisa de folga
        USER_DATA_DIR.mkdir(exist_ok=True)

    async def start(self) -> None:
        return  # Scrapling lanca o navegador por fetch; nada a iniciar

    async def close(self) -> None:
        return  # nada persistente a fechar

    def _fetch_kwargs(self) -> dict:
        return dict(
            headless=self.headless,
            real_chrome=True,           # usa o Chrome real do sistema (mais furtivo)
            solve_cloudflare=True,      # resolve Turnstile/Interstitial se aparecer
            user_data_dir=str(USER_DATA_DIR),
            network_idle=True,
            google_search=True,         # referer = google (menos anomalo)
            timeout=self.timeout_ms,
        )

    async def _fetch_html(self, url: str) -> str:
        # StealthyFetcher.fetch eh sincrono -> roda em thread pra nao travar o event loop
        page = await asyncio.to_thread(StealthyFetcher.fetch, url, **self._fetch_kwargs())
        return page.html_content

    async def buscar_jurisprudencia(
        self,
        query: str,
        limite: int = 10,
        tribunal: Optional[str] = None,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None,
    ) -> list[Resultado]:
        if not query or not query.strip():
            raise ValueError("query vazia")

        params = [f"q={quote_plus(query)}"]
        if tribunal:
            params.append(f"tribunal={quote_plus(_normalizar_tribunal(tribunal))}")
        if data_inicio:
            params.append(f"data_inicial={quote_plus(data_inicio)}")
        if data_fim:
            params.append(f"data_final={quote_plus(data_fim)}")
        url = f"{URL_BUSCA}?{'&'.join(params)}"

        print(f"[BUSCA] {url}")
        html = await self._fetch_html(url)
        return self._parse_resultados(html, limite)

    def _parse_resultados(self, html: str, limite: int) -> list[Resultado]:
        soup = BeautifulSoup(html, "html.parser")
        candidatos = soup.select("article, li[data-testid*='result'], div.SearchResult")
        if not candidatos:
            candidatos = [a.parent for a in soup.select('a[href*="/jurisprudencia/"]') if a.parent]

        vistos: set[str] = set()
        resultados: list[Resultado] = []
        for node in candidatos:
            if len(resultados) >= limite:
                break
            try:
                link = node.find("a", href=True)
                href = link["href"] if link else None
                if href and href.startswith("/"):
                    href = f"{URL_BASE}{href}"
                if not href or "/jurisprudencia/" not in href or href in vistos:
                    continue
                vistos.add(href)
                titulo = self._first_text(node, ["h2", "h3", "h4", "a"]) or "(sem titulo)"
                # Extrai tribunal do prefixo do titulo: "STF - ...", "TJ-RJ - ...", etc.
                import re as _re
                m = _re.match(r"^([A-Z][A-Z0-9-]{1,8}(?:\s*[A-Z0-9-]+)?)\s*[-–]", titulo)
                tribunal = m.group(1).strip() if m else self._first_text(node, [".tribunal", "span.source"])
                num_raw = None
                m_num = re.search(r"(\d{15,20})", titulo)
                if m_num:
                    num_raw = m_num.group(1)
                numero_cnj = formatar_cnj(num_raw) if num_raw else None
                resultados.append(
                    Resultado(
                        titulo=titulo,
                        tribunal=tribunal,
                        numero_cnj=numero_cnj,
                        data=self._first_text(node, [".data", "[data-testid*='date']", "time"]),
                        ementa=self._first_text(node, [".ementa", "[data-testid*='ementa']", "p"]),
                        url=href,
                    )
                )
            except Exception as e:
                print(f"[PARSE] erro num item: {e}")
                continue
        return resultados

    async def ler_decisao(self, url: str):
        """Abre pagina de decisao e extrai todos os metadados."""
        if not url or "jusbrasil.com.br" not in url:
            raise ValueError(f"URL invalida: {url}")
        print(f"[LER] {url}")
        html = await self._fetch_html(url)
        dec = self._parse_decisao(html, url)
        # Anonimo: se o decisionLabel veio mascarado (XXXXX), recupera o CNJ real do Apollo
        if not dec.numero_cnj:
            real = self._cnj_real_do_apollo(html)
            if real:
                dec.numero_cnj = real
        return dec

    def _parse_next_data(self, html: str) -> Optional[dict]:
        """Extrai o no Document do __NEXT_DATA__ do JusBrasil."""
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
        for key, val in apollo.items():
            if key.startswith("Document:") and isinstance(val, dict) and "decisionDepartament" in val:
                return val
        return None

    def _cnj_real_do_apollo(self, html: str) -> Optional[str]:
        """CNJ real (informacoes_gerais.numero_processo) p/ quando decisionLabel vem mascarado.

        Disponivel mesmo para usuario anonimo — contorna o mascaramento (XXXXX) sem login.
        """
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
        for key, val in apollo.items():
            if not (key.startswith("Document:") and isinstance(val, dict)):
                continue
            for k, v in val.items():
                if "enrichedContents" in k and isinstance(v, list):
                    for item in v:
                        payload = (item or {}).get("payload", {}) if isinstance(item, dict) else {}
                        geral = payload.get("informacoes_gerais", {}) if isinstance(payload, dict) else {}
                        num = geral.get("numero_processo")
                        if num and "X" not in num.upper():
                            return num.strip()
        return None

    def _parse_decisao(self, html: str, url: str):
        """Parser tunado com base no HTML real do JusBrasil."""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        def extrair(pattern, texto=text, flags=re.IGNORECASE):
            m = re.search(pattern, texto, flags)
            if not m:
                return None
            v = m.group(1).strip()
            v = re.sub(r"[\s,;\.·]+$", "", v)
            return v or None

        # Titulo
        titulo = None
        h1 = soup.find(["h1", "h2"])
        if h1:
            titulo = h1.get_text(" ", strip=True)
        if not titulo:
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                titulo = og["content"].strip()

        # Tribunal: extrai do PATH da URL (mais confiavel)
        tribunal = None
        m_trib = re.search(r"/jurisprudencia/([a-z0-9_-]+)/", url)
        if m_trib:
            slug = m_trib.group(1)
            # tj_pi -> TJ-PI ; stf -> STF ; trf_1 -> TRF-1
            tribunal = slug.upper().replace("_", "-")

        # Tipo de julgado (aceita c e c-cedilha, a e a-til, i e i-agudo)
        tipo = extrair(
            r"(Apela(?:c|ç)(?:a|ã)o C(?:i|í)vel|Apela(?:c|ç)(?:a|ã)o"
            r"|Recurso Especial|Recurso Extraordin(?:a|á)rio|Habeas Corpus"
            r"|Agravo(?: de Instrumento| Interno| Regimental)?"
            r"|Embargos (?:de Declara(?:c|ç)(?:a|ã)o|Infringentes)"
            r"|Mandado de Seguran(?:c|ç)a)",
            titulo or text
        )

        # FAST PATH: extrai via __NEXT_DATA__ (JSON estruturado, mais robusto)
        nd = self._parse_next_data(html)
        if nd:
            from datetime import datetime
            cnj = None
            m_cnj = re.search(r"(\d{7}-\d{2}\.\d{4}\.\d{1}\.\d{2}\.\d{4})", nd.get("decisionLabel") or "")
            if m_cnj:
                cnj = m_cnj.group(1)
            data_jul = None
            ts = nd.get("judgementDate")
            if ts:
                data_jul = datetime.fromtimestamp(ts / 1000).strftime("%d/%m/%Y")
            data_pub = None
            pubs = nd.get("decisionPublications") or []
            if pubs:
                desc = pubs[0].get('description({"stripTags":true})') or pubs[0].get("description")
                if desc:
                    data_pub = desc.strip()
            ementa_nd = None
            df = nd.get("decisionFacts") or {}
            if df:
                header = re.sub(r"<[^>]+>", "", df.get("header", "") or "")
                paragraphs = df.get("paragraphs") or []
                joined = (header + "\n" + "\n".join(paragraphs)).strip()
                ementa_nd = joined or None
            relator_nd = nd.get("chairman")
            if relator_nd:
                relator_nd = re.sub(r"^Ministr[oa]\s+", "", relator_nd).strip()
            return Decisao(
                url=url,
                titulo=nd.get("title") or titulo,
                tribunal=tribunal,
                tipo=tipo,
                numero_cnj=cnj,
                relator=relator_nd,
                data_julgamento=data_jul,
                data_publicacao=data_pub,
                orgao_julgador=nd.get("decisionDepartament"),
                ementa=ementa_nd,
            )

        # Numero CNJ: primeiro tenta formatado no texto
        numero_cnj = extrair(r"(\d{7}-\d{2}\.\d{4}\.\d{1}\.\d{2}\.\d{4})")
        if not numero_cnj:
            mraw = re.search(r"(\d{19,20})", text)
            if mraw:
                numero_cnj = formatar_cnj(mraw.group(1))

        # Relator: o JusBrasil usa "Relator · Nome" (ponto central)
        # Aceita tambem ":" e "." tradicionais
        relator = extrair(
            r"Relator(?:a)?[\s·:\.]+([A-Z][A-Za-zÀ-ſ\s\.]{3,80}?)"
            r"(?=\s+(?:Julgado|Data|Órg|Org|C(?:a|â)mara|Ementa)|$)"
        )

        # Data de julgamento: site usa "Julgado em DD/MM/YYYY"
        data_julgamento = extrair(r"Julgado em (\d{1,2}/\d{1,2}/\d{2,4})")
        if not data_julgamento:
            data_julgamento = extrair(r"Data de Julgamento[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})")

        data_publicacao = extrair(r"(?:Publicado em|Data de Publica(?:c|ç)(?:a|ã)o)[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})")

        # Orgao julgador: ate a palavra Relator (parada)
        orgao = extrair(
            r"(\d+(?:ª|a)\s+(?:C(?:a|â)mara|Turma)[^·\n]*?)"
            r"(?=\s+Relator|\s+Julgado|$)"
        )
        if not orgao:
            orgao = extrair(
                r"(?:Órg(?:a|ã)o Julgador|Classe)[:\s]+([^,\n·]{3,120}?)"
                r"(?=\s+Relator|\s+Julgado|\s+Data|Ementa|$)"
            )

        # Ementa: a REAL comeca com palavra de cabecalho (APELACAO, RECURSO, etc.)
        # Isso evita pegar "Ementa para citacao" ou "Ementa Mostrar mais"
        ementa = None
        m_em = re.search(
            r"Ementa[:\s]+"
            r"((?:APELA|RECURSO|A(?:C|Ç)(?:A|Ã)O|HABEAS|AGRAVO|EMBARGOS|"
            r"MANDADO|RECLAMA|CONFLITO|PROCESSO|REMESSA|REEXAME)[^$]+?)"
            r"(?=\s+(?:Marca Jus IA|Documentos anexos|Inteiro Teor|"
            r"Jus IA Pergunt|Compartilhar|Salvar|Perguntas e respostas)|$)",
            text, re.S | re.I
        )
        if m_em:
            ementa = re.sub(r"\s+", " ", m_em.group(1)).strip()[:4000]

        return Decisao(
            url=url, titulo=titulo, tribunal=tribunal, tipo=tipo,
            numero_cnj=numero_cnj, relator=relator,
            data_julgamento=data_julgamento, data_publicacao=data_publicacao,
            orgao_julgador=orgao, ementa=ementa,
        )

    @staticmethod
    def _first_text(node, selectors: list[str]) -> Optional[str]:
        for sel in selectors:
            el = node.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(" ", strip=True)
        return None


def _title_case_pt(name: str) -> str:
    """Title case respeitando preposicoes em portugues (do, da, de, dos, das, e)."""
    out = name.title()
    for word in [" Do ", " Da ", " De ", " Dos ", " Das ", " E "]:
        out = out.replace(word, word.lower())
    return out


def _orgao_stj_extenso(orgao: str) -> str:
    """Mapeia 'T4 - QUARTA TURMA' para 'Quarta Turma'."""
    m = re.match(r"^(T[1-6]|S[1-3]|CE)\s*-\s*(.+)$", orgao or "", re.I)
    if m:
        return m.group(2).title()
    return orgao or ""
