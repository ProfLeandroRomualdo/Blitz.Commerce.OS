# Blitz Commerce OS — v0.4.1

**Status: protótipo funcional de comércio agêntico. Não homologado UCP, não pronto
para pagamentos ou varejistas reais.** Este repositório evolui diretamente da
v0.3.0 e preserva seus endpoints e testes.

**Decisões aprovadas:** Google Cloud (Cloud Run + Cloud SQL PostgreSQL), domínio
pretendido `api.blitz.ai`, repositório **GitHub privado**, pagamentos **adiados**.

Referência congelada: [UCP 2026-08-25](https://ucp.dev/2026-08-25/specification/overview/)
e [Authority Binding](https://ucp.dev/2026-08-25/specification/overview/#authority-binding).
Não existe certificação ou conexão automática do ChatGPT com este servidor.

## v0.4.1 — GitHub oficial + `ucp-schema`

- O repositório oficial UCP **possui a tag** `v2026-08-25`. O commit integral
  está fixado em `cd78fb38e819de77d9b527d110476eccb876f1bd`.
- `.github/workflows/ucp-official.yml` clona **esse commit exato**, verifica
  a tag, cria um manifesto de hashes, instala o CLI oficial `ucp-schema` e
  valida quatro respostas reais de API. **Falhas e ausência de contratos
  bloqueiam o job**; não há skip silencioso.
- `scripts/github_ucp_contracts.py` registra e verifica a procedência GitHub
  de todo o diretório `source/`. `scripts/ucp_official_qa.py` salva as
  evidências do validador em `reports/ucp/official-qa.json`.
- Em `docs/OFFICIAL_UCP_GITHUB_QA.md` está o passo a passo para executar e
  marcar o check como obrigatório no GitHub privado.
- **Não confundir:** 40 testes Python passaram localmente; o CLI oficial,
  com os schemas vindos do GitHub, ainda **não rodou** aqui (DNS indisponível).
  Os contratos podem falhar quando o GitHub Actions executar; os erros
  aparecerão no artifact, para correção na próxima versão.

### Testar a integração localmente

```bash
python -m pytest -q
python -m scripts.ucp_official_qa  # exige GitHub snapshot e CLI; falha sem eles
```

Fluxo completo com GitHub e Rust CLI: `docs/OFFICIAL_UCP_GITHUB_QA.md`.

## 1. O que mudou na v0.4.0

- `app/storage.py`: novo adaptador de persistência SQLite (demo/testes) e
  PostgreSQL (Cloud SQL / Docker), com prepared statements e transações explícitas.
- `migrations/postgres/001_initial.sql`: esquema inicial idempotente com
  tenants, credenciais, catálogo, carrinhos, checkouts, eventos, idempotência e
  nonces de assinatura; índice por tenant. **Não é RLS de produção.**
- Serialização transacional de `Idempotency-Key` em PostgreSQL via advisory lock,
  evitando criação duplicada de carrinhos entre instâncias do Cloud Run.
- `/readyz`: health/readiness que consulta o banco de dados.
- Docker Compose com PostgreSQL 16 e API, ambos publicados **somente em 127.0.0.1**.
- Dockerfile compatível com Cloud Run; script de publicação **privada** GCP,
  Secret Manager, Cloud SQL e orientações para domínio futuro `api.blitz.ai`.
- GitHub Actions para testes gerais, integração com PostgreSQL real e download
  **manual** dos documentos oficiais UCP (com hashes SHA-256 e artefatos para revisão).
- `scripts/validate_ucp_contracts.py`: diagnóstico offline de três respostas de
  demo com JSON Schema oficial, **somente após baixar e fixar os contratos**.
- Testes adicionais de tradução SQL, URLs UCP permitidas, integridade de migração,
  readiness, e fluxo PostgreSQL (em runner de CI ou Docker).

### Não foi feito

**Não** fizemos deployment GCP, mapeamento DNS ou criação de GitHub privado.
**Não** baixamos os schemas oficiais neste ambiente (sem DNS de saída): portanto
**não** há evidência de aprovação pelo validador oficial UCP. A implementação
atual ainda apresenta diferenças de payloads/capacidades e não foi corrigida
para a conformidade integral. Assinaturas RFC 9421 são um subconjunto Ed25519,
com perfis pinados. Não há checkout/PSP real, RLS, permissões de usuário,
rate limiting, CI de segurança completo, WBA ou multi-agent federado.

## 2. Stack adotada

| Camada | Tecnologia |
|---|---|
| API | Python 3.12+, FastAPI, Pydantic v2, Uvicorn |
| Criptografia | `cryptography` Ed25519, RFC 9421 parcial |
| Banco | PostgreSQL 16 (`psycopg` 3); SQLite apenas testes/demo |
| Infra local | Docker Engine + Docker Compose V2 |
| Infra cloud | Google Cloud Run + Cloud SQL PostgreSQL + Secret Manager + Artifact Registry |
| Repositório/CI | GitHub privado + GitHub Actions |
| Contratos | UCP 2026-08-25, JSON Schema Draft 2020-12, OpenAPI 3.1 |
| Pagamentos | Nenhum (propositadamente bloqueado) |

## 3. Início rápido: Docker Compose (recomendado)

Requisitos: Docker Desktop ou Docker Engine com Compose V2, portas locais
`8000` e `5432` livres, e 2+ GB livres de memória.

```bash
unzip blitz-commerce-mvp-v0.4.0.zip
cd blitz-commerce-mvp
cp .env.example .env
python3 - <<'PY'
import secrets
from pathlib import Path
p = Path('.env')
s = p.read_text()
s = s.replace('REPLACE_WITH_RANDOM_SECRET', secrets.token_hex(32))
s = s.replace('REPLACE_WITH_RANDOM_POSTGRES_PASSWORD', secrets.token_hex(24))
p.write_text(s)
PY
docker compose up --build -d
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

Swagger: `http://127.0.0.1:8000/docs`.

Para consultar o catálogo com autenticação (executar no diretório do projeto):

```bash
set -a; source .env; set +a
curl -sS -X POST http://127.0.0.1:8000/ucp/v1/catalog/search \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{"query":"oleo","pagination":{"limit":10}}'
```

Um teste de carrinho (sem pagamento):

```bash
curl -sS -X POST http://127.0.0.1:8000/ucp/v1/carts \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $DEMO_API_KEY" \
  -H 'Idempotency-Key: teste-carrinho-001' \
  -d '{"line_items":[{"item":{"id":"OLEO-001"},"quantity":2}]}'
```

Resultado esperado: um carrinho de demonstração em **BRL 9.180 centavos**.
O link de `continue_url` é uma página fictícia que **não recebe pagamento**.

Para parar: `docker compose down`. Para apagar todo o catálogo e dados do banco
local: `docker compose down -v` (**irreversível; somente em demo**).

> Se estiver usando um shell que expanda caracteres especiais em URL, utilize
> senha PostgreSQL gerada por `secrets.token_hex`, como no exemplo acima.

## 4. Executar só com Python/SQLite para desenvolvimento

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export DEMO_MODE=true
export DEMO_API_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')
export DATABASE_PATH=./blitz.db
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

SQLite é **somente** demo/teste, não alternativa de produção.

## 5. Testes e QA

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q app scripts tests
```

A suíte de testes unitários/HTTP usa SQLite isolado por teste. Para executar
PostgreSQL **real**, suba Docker Compose, instale `requirements-postgres.txt`,
crie um banco de testes SEPARADO e execute:

```bash
# Banco exclusivo criado pelo operador em localhost; nunca use banco de cliente.
export TEST_DATABASE_URL=postgresql://blitz:SENHA@127.0.0.1:5432/blitz_test
python -m pytest -q tests/test_postgres.py
```

No GitHub Actions, `postgres-integration` cria automaticamente um serviço
Postgres descartável e um banco `blitz_test`; localmente essa suíte é pulada
sem `TEST_DATABASE_URL`. Veja `docs/QA_REPORT.md` para testes realizados e
limitações do ambiente de entrega.

## 6. Contratos oficiais UCP e diagnóstico

Os esquemas reais **não estão no ZIP**. Execute no seu computador ou um job
GitHub Actions com acesso à internet, revise os downloads e comite os documentos
versionados após aprovação:

```bash
python -m pip install -r requirements-contracts.txt
python scripts/fetch_ucp_contracts.py --sync
python scripts/fetch_ucp_contracts.py --verify
python scripts/validate_ucp_contracts.py
```

O primeiro script permite somente URLs HTTPS do domínio `ucp.dev` e versão
`2026-08-25`, rejeita redirecionamentos, limita tamanho/quantidade e percorre
`$ref` para fixar também as dependências. O manifesto SHA-256 é escrito depois
que toda a árvore é coletada. `--verify` funciona offline.

O validador testa **respostas selecionadas** de catálogo e carrinho contra
esquemas oficiais; não pretende provar conformidade global. Retorna status 1
para divergências e 2 para falha de infraestrutura/contratos ausentes. É
esperado encontrar diferenças do MVP que ainda exigem correção. Assim que o
lock estiver no repositório, o CI roda o diagnóstico e bloqueia regressões.

No GitHub Actions, use **Review upstream UCP contracts (manual)** para criar
um artifact revisável, sem commit/merge automático. Cada atualização exige
review humano e nova rodada de testes.

## 7. Preparar o GitHub privado

No GitHub, crie um **repositório privado** `blitz-commerce-os`. No terminal:

```bash
cd blitz-commerce-mvp
git init
git branch -M main
git add .
git commit -m 'feat: Blitz Commerce OS v0.4.0 PostgreSQL/GCP baseline'
git remote add origin git@github.com:SEU_ORG/blitz-commerce-os.git
git push -u origin main
```

Confirme antes que `.env`, chaves e credenciais estão ausentes de `git status`
e `git ls-files`. Proteja `main` com pull requests e status checks obrigatórios
(`test`, `postgres-integration`), e habilite secret scanning/Dependabot onde
estiver disponível. Não publique o repositório por engano.

## 8. Deploy privado na GCP

Leia **`deploy/gcp/README.md`**. O deploy é apenas *staging privado*: usa Cloud
Run com `--no-allow-unauthenticated`, Cloud SQL, segredos no Secret Manager e
runtime service account de menor privilégio. Sem chaves ou domínio presumidos.

Cloud Run público com `DEMO_MODE=true` está **proibido**. O domínio
`api.blitz.ai` é uma intenção; verificar sua titularidade e configurar DNS,
certificado e load balancer são etapas **externas pendentes**.

## 9. Endpoints disponíveis

| Requisição | Uso | Auth |
|---|---|---|
| `GET /healthz` | Processo ativo | Pública |
| `GET /readyz` | Conexão com o banco | Pública (não contém segredos) |
| `GET /.well-known/ucp` | Discovery UCP parcial | Pública |
| `POST /ucp/v1/catalog/search` | Busca com cursor assinado | API key |
| `POST /ucp/v1/catalog/lookup` | Consulta de SKUs | API key |
| `POST /ucp/v1/catalog/product` | Detalhe individual | API key |
| `POST /ucp/v1/carts` | Criar carrinho / idempotência | API key |
| `GET /ucp/v1/carts/{id}` | Consultar carrinho | API key |
| `PUT /ucp/v1/carts/{id}` | Alterar itens | API key |
| `POST /ucp/v1/carts/{id}/cancel` | Cancelar carrinho | API key |
| `GET /api/usage` | Eventos de uso, sem billing | API key |
| `/ucp/v1/checkout-sessions...` | **Demo apenas; sem cobranças** | API key |

No modo `STRICT_UCP=true`, a camada de assinatura exige perfil pinado e chave
Ed25519. Veja `docs/HISTORY_v0.3.md` para configuração e detalhes de testes.

## 10. Arquitetura e isolamento

```text
UCP-Agent -> HTTPS/API Gateway (futuro) -> FastAPI Cloud Run
                                           |-- identidade API key + perfil pinado
                                           |-- catálogo/carrinho/metering
                                           |-- Ed25519 (opcional, experimental)
                                           +-- PostgreSQL / Cloud SQL
                                               tenants, products, carts,
                                               events, idempotency, nonces
```

Em produção, a aplicação ainda precisa de: RLS com papéis e escopos,
provisionamento explícito de tenants, rate limits, migrações com ferramenta
formal, pool/connection budget, backups/restores testados, retenção LGPD,
observabilidade, auditoria independente e HTTPS na borda. O aplicativo não
implementa PSP nem captura dados de cartão.

## 11. Como testar a partir do ChatGPT

Você pode **anexar o ZIP e pedir análise, geração de testes, revisão ou evolução
código a código** nesta conversa. Para executar APIs locais daqui, normalmente
é preciso executar o servidor no seu computador ou publicar um ambiente de
staging e disponibilizar acesso apropriado. A interface de chat não cria, por
si só, um conector para `localhost` do seu computador nem acessa uma API
privada Cloud Run autenticada. Não exponha chaves ou tokens no chat.

Para reproduzir o ambiente e enviar o resultado ao ChatGPT, rode
`python -m pytest -q` e compartilhe o relatório sem segredos.

## 12. Continuidade

- `docs/QA_REPORT.md`: testes aprovados, pulados, bloqueios e próximos gates.
- `docs/CONTINUITY.md`: decisões, comandos e próximos tickets, suficientes
  para retomar o desenvolvimento a partir do ZIP sem contexto da conversa.
- `docs/HISTORY_v0.3.md`: documentação detalhada da versão anterior.

**Próximo incremento recomendado: v0.5.0** — fixar artefatos oficiais, corrigir
payloads segundo o relatório de schemas, validar contratos CI offline, adicionar
provisionamento de tenants e RLS/PostgreSQL antes de tornar API pública.
