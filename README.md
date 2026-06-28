# jusbrasil-mcp

Servidor [MCP](https://modelcontextprotocol.io) para pesquisar **jurisprudência no [JusBrasil](https://www.jusbrasil.com.br)** em linguagem natural, ler o **inteiro teor** das decisões e gerar **citações e dossiês** prontos para uso em peças jurídicas. Pensado para o Claude Desktop.

## Tools

- **`buscar_jurisprudencia(query, limite, tribunal, tipo, periodo, ordenacao)`** — busca com filtros: tribunal (`STJ`, `STF`, `TJs`, `TRFs`…), tipo (`acordao`, `sumula`, `decisao`, `sentenca`, `despacho`), período (`7dias`/`30dias`/`365dias`) e ordenação (`data`/`relevancia`).
- **`buscar_sumulas(query, limite, tribunal)`** — busca de súmulas.
- **`ler_decisao(url)`** — metadados + **ementa** + `citacao_abnt` + `link_verificacao`.
- **`ler_inteiro_teor(url)`** — **texto integral** do acórdão (relatório + voto + acórdão). Exige login.
- **`compilar_dossie(urls, incluir_inteiro_teor, titulo, caminho)`** — reúne várias decisões/súmulas num único **`.docx`** (citação + ementa + link; inteiro teor opcional).

## Como funciona

- Coleta via [**Scrapling**](https://github.com/D4Vinci/Scrapling) `StealthyFetcher` — passa o Cloudflare em **headless puro** (sem janela).
- **Login automático** com as suas credenciais (guardadas no cofre do sistema — Keychain no macOS, Gerenciador de Credenciais no Windows), com sessão persistente. O login só é necessário para o inteiro teor e para desmascarar números/metadados; sem credenciais, opera anônimo (com dados parciais).
- Parsing a partir do JSON estruturado (`__NEXT_DATA__` / Apollo) embutido nas páginas.
- Citação por tribunal: formato convencional do STJ e genérico para TJs/TRFs/TST.

## Instalação

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12+, com o Google Chrome instalado.

```bash
git clone https://github.com/fxbarros/mcp-jusbrasil.git
cd mcp-jusbrasil
uv sync
uv run scrapling install        # navegador usado pelo Scrapling
uv run python setup_credenciais.py   # grava e-mail/senha do JusBrasil no Keychain
```

As credenciais ficam **apenas no cofre de credenciais do sistema** (serviço `mcp-jusbrasil`) — nunca em arquivo. O `keyring` é multiplataforma e escolhe o cofre certo automaticamente: **Keychain** no macOS e **Gerenciador de Credenciais** no Windows (a dependência do backend do Windows é instalada pelo `uv sync`). O mesmo `setup_credenciais.py` serve para os dois.

## Uso no Claude Desktop

```json
{
  "mcpServers": {
    "jusbrasil": {
      "command": "uv",
      "args": ["run", "--directory", "/caminho/para/mcp-jusbrasil", "jusbrasil-mcp"]
    }
  }
}
```

| Variável | Padrão | Descrição |
|---|---|---|
| `JUSBRASIL_TIMEOUT_MS` | `60000` | Timeout por navegação (ms). |

Roda **sempre headless** (sem janela).

## Limitações

- O filtro de **tribunal** é por sistema (`STJ`, `TJs`…), não por corte específica isolada (ex.: TJ-PI sozinho).
- O filtro de **data** é por período relativo (últimos N dias), não por intervalo exato.
- O **inteiro teor** nem sempre existe para toda decisão.
- Os filtros dependem dos parâmetros atuais do site e podem quebrar se o JusBrasil mudar.

## Aviso

O JusBrasil é um **agregador privado**, não é fonte oficial. Para citação formal, confira sempre o texto no site oficial do tribunal. As tools incluem avisos anti-alucinação: campos não extraídos voltam nulos e **não devem ser preenchidos por inferência**. Respeite os termos de uso do site.

## Licença

[MIT](LICENSE).
