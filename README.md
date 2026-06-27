# jusbrasil-mcp

Servidor [MCP](https://modelcontextprotocol.io) para pesquisar **jurisprudência no [JusBrasil](https://www.jusbrasil.com.br)** em linguagem natural e devolver **citações já formatadas** para uso em peças jurídicas. Pensado para uso no Claude Desktop.

## O que faz

Expõe duas tools:

- **`buscar_jurisprudencia(query, limite, tribunal, data_inicio, data_fim)`** — busca por termos livres; retorna título, tribunal, número CNJ, ementa curta e URL de cada acórdão.
- **`ler_decisao(url)`** — abre uma decisão e extrai os metadados formais (relator, órgão julgador, datas, número CNJ) + monta a `citacao_abnt` pronta para citar.

Fluxo típico: buscar → escolher a ementa relevante → `ler_decisao` → colar a citação na peça.

## Como funciona

- Coleta via [**Scrapling**](https://github.com/D4Vinci/Scrapling) `StealthyFetcher` (headless, contorna o Cloudflare do site sem necessidade de login).
- Parsing dos metadados a partir do JSON estruturado (`__NEXT_DATA__` / Apollo) embutido nas páginas — mais robusto que regex em HTML.
- Citação por tribunal: formato convencional do STJ (recurso + registro + DJe) e formato genérico para TJs/TRFs/TST.

## Instalação

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12+.

```bash
git clone https://github.com/<seu-usuario>/mcp-jusbrasil.git
cd mcp-jusbrasil
uv sync
uv run scrapling install   # baixa o navegador usado pelo Scrapling
```

> O `StealthyFetcher` usa o Google Chrome instalado no sistema (`real_chrome=True`).

## Uso no Claude Desktop

Adicione ao `claude_desktop_config.json`:

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

### Variáveis de ambiente (opcionais)

| Variável | Padrão | Descrição |
|---|---|---|
| `JUSBRASIL_HEADLESS` | `true` | Roda sem janela. |
| `JUSBRASIL_TIMEOUT_MS` | `60000` | Timeout por navegação (ms). |

## Aviso

O JusBrasil é um **agregador privado**, não é fonte oficial. Para citação formal em peça, confira sempre o texto no site oficial do tribunal (scon.stj.jus.br, sites dos TJs etc.). As tools incluem avisos anti-alucinação: campos não extraídos voltam nulos e **não devem ser preenchidos por inferência**. Respeite os termos de uso do site.

## Licença

Uso pessoal/educacional.
