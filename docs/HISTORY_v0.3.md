# Blitz Commerce OS — MVP v0.3.0

**Status: protótipo demonstrável e testado; NÃO pronto para produção ou para integração UCP certificada.**

Referência de contrato: [UCP 2026-08-25](https://ucp.dev/2026-08-25/specification/overview/), especialmente [Authority Binding](https://ucp.dev/2026-08-25/specification/overview/#authority-binding), [Catalog REST](https://ucp.dev/2026-08-25/specification/shopping/catalog/rest/) e [Cart REST](https://ucp.dev/2026-08-25/specification/shopping/cart/rest/).

## Incremento v0.3.0 — segurança e negociação experimental

Este incremento entrega um **caminho estrito opt-in**, que valida perfis de plataforma
previamente aprovados, escolhe a interseção exata de capacidades de raiz, valida
assinaturas RFC 9421 **em um subconjunto Ed25519** e gera resposta assinada. Inclui
Content-Digest (SHA-256), janelas de validade de até 5 minutos, nonces com proteção
anti-replay persistida no SQLite, JWK público no discovery e testes de adulteração.

**Não equivale a conformidade integral nem autenticação universal.** O modo estrito
não baixa perfis pela rede: utiliza snapshots revisados em `PINNED_PROFILES_FILE`.
Rejeita assinaturas fora do subconjunto; não suporta Web Bot Auth, extensões,
multisignature nem todos os formatos RFC 8941. Além disso, o modo padrão permanece
um demo de API key sem assinaturas: não disponibilize esse modo publicamente.

### Executar os novos testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

### Testar com assinaturas sem expor chaves

O teste `tests/test_security_v03.py` gera chaves Ed25519 aleatórias na memória,
monta um perfil de plataforma pinado, assina a chamada, verifica a resposta
assinada, testa alteração de payload e repetição de nonce. Execute somente essa
parte com `python -m pytest -q tests/test_security_v03.py`.

Para ativação manual, além da configuração básica, exporte:

```bash
export STRICT_UCP=true
export PINNED_PROFILES_FILE=/caminho/absoluto/plataformas-aprovadas.json
export UCP_SIGNING_KEY_B64='BASE64URL_DOS_32_BYTES_DA_CHAVE_ED25519_PRIVADA'
```

Formato do JSON de perfis revisados:

```json
{
  "https://agent.example/profiles/demo.json": {
    "ucp": {
      "version": "2026-08-25",
      "services": {},
      "payment_handlers": {},
      "capabilities": {
        "dev.ucp.shopping.catalog.search": [{"version": "2026-08-25"}]
      }
    },
    "keys": [
      {"kty":"OKP","crv":"Ed25519","alg":"EdDSA","kid":"KID_REAL","x":"CHAVE_PUBLICA_BASE64URL","use":"sig","key_ops":["verify"]}
    ]
  }
}
```

**Atenção:** esse JSON é um exemplo estrutural, não possui uma chave real.
A assinatura não substitui o controle existente de `X-API-Key`/vínculo do
perfil no banco. Em laboratório, é possível criar as chaves de teste via
`cryptography` e consultar `jwk_from_private` em `app/ucp_security.py`.
O endpoint público `/.well-known/ucp` publica `keys[]` quando uma chave
real está configurada. Guarde a chave privada apenas em secret manager, nunca
no arquivo JSON, repositório ou `.env` versionado.

### Contratos oficiais fixados por versão

O script `scripts/fetch_ucp_contracts.py` aponta exclusivamente para artefatos
sob `https://ucp.dev/2026-08-25/`:

```bash
# Execute em ambiente com acesso à internet, após revisar a lista de URLs:
python scripts/fetch_ucp_contracts.py --sync
# Gere contracts/2026-08-25/manifest.json com hashes SHA-256
python scripts/fetch_ucp_contracts.py --verify
```

O **download não foi possível neste ambiente**, portanto arquivos e hashes
oficiais não são incluídos artificialmente. O script de verificação falha
explicitamente até que o download aconteça. Após sincronizar, revise os schemas,
verifique Authority Binding e introduza testes de contrato de cada endpoint.
Apenas ter JSON válido e hashes não comprova aderência das respostas.

## 1. Escopo que funciona hoje

- API REST com documentação automática OpenAPI (`/docs` e `/openapi.json`).
- Discovery UCP em `/.well-known/ucp` com `Cache-Control: public, max-age=300`, REST e capacidades de catálogo **e carrinho** declaradas; checkout experimental **não é anunciado**.
- Busca de catálogo UCP-shaped (`POST /ucp/v1/catalog/search`) com paginação via cursor assinado e lookup por identificadores (`POST /ucp/v1/catalog/lookup`), além de consulta individual (`POST /ucp/v1/catalog/product`).
- Carrinho: criar, consultar, atualizar e cancelar (`/ucp/v1/carts`). Preço sempre recalculado no servidor com estoque validado; somatório em centavos de BRL.
- Auth de laboratório via `X-API-Key`, hashes SHA-256 das chaves no banco, separação lógica por tenant, acesso negado entre tenants e vínculo explícito de `UCP-Agent` ao tenant; o perfil de agente é **obrigatório fora do modo demo**. A sintaxe aceita apenas a forma simples `profile="https://..."` e não implementa um parser RFC 8941 completo.
- Idempotência no `POST /carts` via header `Idempotency-Key` (8–128 caracteres `[A-Za-z0-9_-]`). Replays retornam o mesmo ID e não duplicam a contagem `cart_created`.
- Ledger simples de eventos de uso em `/api/usage`; não emite faturas.
- Página de handoff **fictícia** (`/demo/handoff/{cart_id}`) sem pagamentos; demonstra o fluxo até o momento anterior ao checkout real.
- Checkout REST **experimental**, não divulgado em discovery, acessível exclusivamente em `DEMO_MODE=true`: criar/consultar/atualizar/cancelar (`/ucp/v1/checkout-sessions`) com estado `requires_escalation`. `complete` retorna `501` deliberadamente — não cria pedido nem pagamento. Dados pessoais de comprador são rejeitados.
- Carga offline de catálogo por CSV e três produtos artificiais de demonstração.
- Testes automatizados com pytest + script HTTP smoke test.

**IMPORTANTE:** a API utiliza algumas formas e caminhos REST da especificação, mas seus payloads e mecanismos de negociação NÃO passaram por conformance suite oficial. A versão 0.3.0 NÃO alcança conformidade integral UCP. A matriz abaixo detalha o que falta. O perfil não é prova de certificação. Não implementar dinheiro real, entrega real ou repassar dados de clientes neste estágio. Nem o ChatGPT nem agentes públicos estão automaticamente conectados a essa API.

## 2. Matriz de conformidade UCP 2026-08-25

Esta matriz é um resultado técnico da implementação atual, **não** uma certificação. Referência: [overview](https://ucp.dev/2026-08-25/specification/overview/), [catalog REST](https://ucp.dev/2026-08-25/specification/shopping/catalog/rest/), [cart REST](https://ucp.dev/2026-08-25/specification/shopping/cart/rest/), [checkout REST](https://ucp.dev/2026-08-25/specification/shopping/checkout/rest/).

| Requisito / capacidade | Estado | Lacuna |
|---|---|---|
| Versão e REST base URL | Implementado no demo | URL pública HTTPS real necessária |
| Discovery / `Cache-Control` | Implementado parcialmente | Perfil por domínio/merchant, ETag, catálogo oficial de capabilities e schemas |
| Authority Binding | Usa somente namespaces `dev.ucp` apontados a `ucp.dev` | Validação formal do resolvedor externo / extensões próprias |
| Catalog search | Parcial | Filters/context/signals/attribution, payload completo, semântica de paginação oficial e testes de schema |
| Catalog lookup / product | Parcial | Opções/variantes múltiplas, filtros, mensagens padronizadas e testes de contrato |
| Cart REST CRUD | Parcial | Negociação e campos opcionais; comportamento completo de erro e context |
| Checkout REST CRUD | Sandbox apenas | Falta PSP, fulfillment, políticas, proteção antifraude e complete real |
| Payment handlers | Não implementado | Homologação com PSP e fluxos de tokenização |
| Identity / `UCP-Agent` | Parcial | Vínculo por API key e Ed25519 com perfis pinados; falta parser RFC 8941 completo e fetch SSRF-safe com cache |
| HTTP Message Signatures (RFC 9421) | Parcial, modo estrito opt-in | Ed25519 e assinatura de resposta, digest e replay SQLite; falta suporte completo a RFC 8941/9421, outros algoritmos, múltiplas assinaturas e Web Bot Auth |
| Negotiation de capacidades | Parcial, modo estrito opt-in | Interseção de versão exata e capacidades de raiz; precisa fetch seguro, extensão multi-parent, cache/ETag e resolução de schemas |
| Transports MCP / A2A / Embedded | Não implementado | Adaptadores próprios, caso sejam anunciados |
| Orders, fulfillment, webhooks | Não implementado | Integração ERP e assinaturas obrigatórias de webhooks |
| Conformance suite oficial | Não executada | Script para obter e fixar SHA-256 pronto; baixar artefatos em ambiente com rede e executar validação de payloads |

**Gate de produção:** não ativar checkout real nem anunciar certificação até que a suíte oficial, threat model, revisão de segurança, integrações PSP/ERP, LGPD e os testes de interoperabilidade estejam aprovados. Nenhuma operação de pagamento acontece no código atual.

## 3. Stack e decisões técnicas

| Camada | Escolha no MVP | Evolução para SaaS |
|---|---|---|
| Linguagem | Python 3.12 (imagem Docker); 3.13 validado localmente | Python 3.12+ |
| Web/API | FastAPI + Pydantic v2 | FastAPI / serviços especializados |
| Banco | SQLite com WAL | PostgreSQL gerenciado, políticas RLS |
| Servidor | Uvicorn | GCP Cloud Run |
| Empacotamento | Docker / Docker Compose | Artifact Registry + Cloud Run |
| HTTPS público de demo | Caddy em uma VM | Cloud Load Balancing/Cloud Run TLS gerenciado |
| Nuvem escolhida | **Google Cloud Platform (GCP)** | Cloud Run + Cloud SQL PostgreSQL + Secret Manager |
| QA | pytest, HTTP TestClient, smoke | CI, SAST/DAST, conformance e testes de carga |
| Billing | Contagem de eventos no SQLite | Ledger transacional + precificação + pagamentos SaaS |

**Por que VM no demo?** O SQLite usa arquivos persistentes e não deve ser montado ingenuamente em múltiplas réplicas do Cloud Run. A VM única permite demonstrar o MVP sem falsa promessa de escala. Para SaaS real, migrar para PostgreSQL antes de Cloud Run e múltiplas réplicas. Não tratar VM única como alta disponibilidade.

## 4. Requisitos locais

- Linux, macOS ou Windows com WSL2.
- Python 3.12+ e `pip` **ou** Docker + Docker Compose v2.
- Portas 8000 (local) e, para teste externo HTTPS, domínio e portas 80/443.
- Nenhuma credencial de Google Cloud, PSP ou ERP é necessária para o teste local.

## 5. Rodar localmente com Python

```bash
cd blitz-commerce-mvp
python3 -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
cp .env.example .env
# Para o demo local, defina uma chave aleatória na sessão atual:
export DEMO_MODE=true
export DEMO_API_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
export PUBLIC_BASE_URL=http://localhost:8000
export DATABASE_PATH=./blitz.db
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

O arquivo `.env` **não é lido automaticamente pelo código Python**: para o servidor Python direto, exporte as variáveis como acima. Não publique a chave. Em outro terminal, reutilize o valor de `DEMO_API_KEY` ou rode `source .venv/bin/activate` e configure a chave antes dos testes.

Abrir `http://localhost:8000/docs`. A API inicia o banco e três SKUs automaticamente em `DEMO_MODE=true`.

### Alternativa Docker

```bash
cd blitz-commerce-mvp
cp .env.example .env
# Edite .env e substitua DEMO_API_KEY por uma chave aleatória longa.
docker compose up --build -d
docker compose logs -f api
# Abrir http://localhost:8000/docs
```

A configuração Docker local lê `DEMO_API_KEY` do `.env` via Compose. O banco fica no volume persistente `blitz-data`.

## 6. Testar todos os endpoints

**Atenção:** use a mesma chave configurada para iniciar o servidor.

```bash
export API=http://localhost:8000
export KEY="$DEMO_API_KEY"

# Health e perfil (sem autenticação)
curl -s "$API/healthz"
curl -s "$API/.well-known/ucp"

# Pesquisa / catálogo
curl -s -X POST "$API/ucp/v1/catalog/search" \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"query":"lavanda", "pagination":{"limit":20}}'

# Paginação: envie {"pagination":{"limit":1}} e use o cursor retornado na página seguinte.
# Lookup por SKU
curl -s -X POST "$API/ucp/v1/catalog/lookup" \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"ids":["CAMBIO-001","OLEO-001"]}'

# Detalhe de produto
curl -s -X POST "$API/ucp/v1/catalog/product" \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"id":"OLEO-001"}'

# Cabeçalho de agente opcional em demo, obrigatório e pré-cadastrado fora dele:
# -H 'UCP-Agent: profile="https://agent.example/profiles/demo.json"'
# Em produção, perfis devem ser pré-cadastrados na tabela platform_bindings.

# Criar carrinho; preço total esperado = 2 × 4590 = 9180 centavos (R$91,80)
curl -s -X POST "$API/ucp/v1/carts" \
  -H "X-API-Key: $KEY" -H 'Idempotency-Key: teste_123456789' \
  -H 'Content-Type: application/json' \
  -d '{"line_items":[{"item":{"id":"OLEO-001"},"quantity":2}]}'

# Copiar o campo id retornado (por exemplo: cart_xxx)
export CART_ID=cart_SUBSTITUIR
curl -s -H "X-API-Key: $KEY" "$API/ucp/v1/carts/$CART_ID"

# Atualizar valor no carrinho
curl -s -X PUT "$API/ucp/v1/carts/$CART_ID" \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"line_items":[{"item":{"id":"OLEO-001"},"quantity":3}]}'

# Cancelamento e auditoria
curl -s -X POST -H "X-API-Key: $KEY" "$API/ucp/v1/carts/$CART_ID/cancel"
curl -s -H "X-API-Key: $KEY" "$API/api/usage"
```

**Smoke test HTTP (servidor precisa estar em execução):**

```bash
export SMOKE_BASE_URL=http://localhost:8000
python scripts/smoke_test.py
```

**QA automatizado isolado (não precisa de servidor):**

```bash
python -m pytest -q
```

Obs.: prefira `python -m pytest` em vez de `pytest`, especialmente em ambientes com múltiplos interpretadores Python.

## 7. Importar dados próprios de teste (CSV)

O CSV usa cabeçalhos `sku,title,description,price_cents,stock`; o preço é **inteiro em centavos**.

```bash
export DATABASE_PATH=./blitz.db
export DEMO_MODE=true
python -m scripts.import_catalog scripts/sample_catalog.csv demo
```

Depois faça uma busca por `Kit transmissão`. O importador executa upsert em transação única e rejeita dados negativos. **Não execute sobre dados reais sem governança e sem políticas de privacidade**. O CSV não configura URLs de produtos, fotos, categorias, múltiplos estoques ou impostos; isso exige evolução do modelo.

## 8. Fazer funcionar na cloud (GCP Compute Engine, DEMONSTRAÇÃO APENAS)

Este caminho usa uma VM pequena e Caddy, com HTTPS automático. Não há pagamentos reais. Passos na interface web GCP:

1. Criar um projeto GCP, habilitar faturamento e criar orçamento/alertas no Cloud Billing.
2. Habilitar **Compute Engine API**. Criar uma VM Ubuntu LTS (`e2-small` ou equivalente como ponto de partida; ajustar por testes). Usar disco persistente >= 20 GB, backups/snapshots e região próxima dos testes. Habilitar OS Login e acesso SSH restrito.
3. Reservar um IP externo estático, configurar DNS tipo `A` de `demo.seudominio.com` apontando para esse IP. O domínio precisa estar sob seu controle.
4. Criar regra de firewall apenas para TCP 80/443 (HTTPS público) e SSH restrito a seus IPs, ou SSH via IAP. Não abrir 8000 nem 8080 publicamente.
5. Instalar Docker Engine e Docker Compose plugin a partir dos repositórios oficiais, conforme [instruções Docker para Ubuntu](https://docs.docker.com/engine/install/ubuntu/). Validar `docker compose version`.
6. Transferir o repositório para a VM (Git privado ou `scp`; **não** subir `.env` real a Git). Executar:

```bash
cd blitz-commerce-mvp
cp .env.example .env
# Edite .env, por exemplo: nano .env
# Deve conter:
# DOMAIN=demo.seudominio.com
# DEMO_API_KEY=<chave aleatoria longa gerada localmente>
# As demais variáveis em .env são opcionais nesse Compose.
docker compose -f docker-compose.cloud-demo.yml up --build -d
docker compose -f docker-compose.cloud-demo.yml logs -f proxy api
```

7. Esperar certificado HTTPS do Caddy (depende de DNS correto e portas 80/443 abertas). Testar `https://demo.seudominio.com/healthz`, `.../.well-known/ucp`, `.../docs` e rodar o smoke com `SMOKE_BASE_URL=https://demo.seudominio.com`.
8. Configurar alertas no GCP Monitoring e backups periódicos testados do volume. **SQLite exige backup consistente** (`sqlite3 .backup` ou snapshot com aplicação pausada), não simples cópia de arquivo sob carga. Aplicar atualizações de segurança na VM, Docker e imagens.

**Segurança de nuvem:** mesmo com HTTPS, este protótipo não possui rate limiting, WAF, IAM de produção, secrets management, governança LGPD, assinaturas HTTP UCP nem controle financeiro. Usar apenas dados sintéticos e exposição temporária; preferir limitar a VPN/IP até concluir endurecimento. **Não disponibilizar como serviço comercial.**

### Destino de produção planejado

- Migrar SQLite para **Cloud SQL for PostgreSQL**; adicionar migrations Alembic, pool, testes de concorrência e RLS por tenant.
- Subir imagens no **Artifact Registry** e implantar API no **Cloud Run** com ingress controlado, HTTPS, autenticação real e ambientes separados.
- Guardar segredos no **Secret Manager** e contas de serviço mínimas; auditoria em Cloud Logging.
- Adicionar Cloud Armor (conforme topologia), budgets, backups, restore testado, CI/CD com security scans e monitoramento.
- Antes de tráfego de agentes públicos: validar UCP, registro e descoberta por domínio real do comerciante, assinaturas, negociação de capabilities e política de platform identity.

## 8. Testar no ChatGPT

**O ChatGPT não executa automaticamente um servidor local ou zip enviado e não faz chamadas HTTP arbitrárias só por conversar com o modelo.** Existem dois caminhos:

1. **Aqui na conversa:** anexe este ZIP, peça para inspecionar arquivos, rodar `python -m pytest -q`, executar o aplicativo em ambiente isolado e simular as operações com o `TestClient`. Isso valida o backend sem deploy externo (foi o método utilizado para QA deste pacote).
2. **API pública para ferramentas e integrações:** primeiro suba o servidor HTTPS na GCP, forneça a documentação OpenAPI e implemente um conector/ação compatível com a configuração de sua plataforma ChatGPT. O endpoint `/docs` por si só **não faz o ChatGPT consumir UCP**. O acesso pelo agente dependerá dos recursos de ferramenta/conector disponíveis no ambiente, suas políticas de segurança e autenticação. Nunca cole chaves reais no chat.

É possível pedir ao ChatGPT para analisar logs, resultados de testes e contratos JSON, e gerar novos testes; isso não equivale a possuir uma integração oficial UCP homologada com o ChatGPT.

## 9. Limitações conhecidas e riscos bloqueadores

- **Não certificado UCP:** capability negotiation, validação dos schemas oficiais, conformance end-to-end e platform advertisement pendentes; perfil publicado é experimental.
- **Authority Binding:** os schemas `dev.ucp.*` apontam corretamente para o host controlado pelo UCP (`ucp.dev`) e não para `blitz.ai`; **nenhuma extensão própria Blitz** foi reivindicada. Validação ativa de schemas remotos e proteção SSRF serão necessárias ao implementar um cliente UCP.
- **Checkout:** não é implementado. A URL de handoff exibe página fictícia sem cobrar, vincular pagamento ou transferir carrinho para lojista. Nenhum endpoint `/checkout-sessions` é anunciado.
- **Pagamento/PSP:** ausente. `payment_handlers` permanece vazio. Nunca coletar cartão.
- **Sem controle de agentes:** apenas chave estática para o laboratório, sem HTTP Message Signatures, política granular, rotação de chave, OAuth, autorização por escopo ou defesa contra abuso em escala.
- **API key:** hash SHA-256 sem sal protegido apenas por entropia da chave; aceitável para chaves aleatórias fortes em demo, mas exige gestão de credenciais e rotação em produção. `require_tenant` varre todos os tenants (O(n)); precisa de auth service indexado.
- **SQLite multi-tenant:** isolamento na cláusula SQL testado, mas **não** equivalente a PostgreSQL RLS nem a garantia formal multi-tenant.
- **Estoque:** validado no momento da criação/atualização do carrinho; NÃO reserva unidades nem garante preço/estoque ao checkout posterior.
- **Metering:** contagens técnicas, não medição financeiramente auditada; não existe franquia, deduplicação de eventos por todos os métodos, quotas, faturamento ou ledger imutável.
- **Busca:** `LIKE` com escaping de metacaracteres, sem paginação por cursor e sem enriquecimento semântico; metadados de produto simplificados.
- **`/demo/handoff` e `/demo/products`:** são endpoints sintéticos de demonstração, não páginas reais de um comerciante. A URL opaca do carrinho atua como identificador de acesso a esta página e não deve conter dados pessoais.
- **Sem ERP:** importação offline CSV é a única alimentação de catálogo.
- **Sem frontend lojista:** a UI funcional hoje é Swagger em `/docs`.

## 10. Estrutura do repositório

```text
blitz-commerce-mvp/
├── app/
│   ├── __init__.py
│   └── main.py                 # API, modelos, SQLite, auth, ledger, UCP-shaped endpoints
├── tests/
│   ├── conftest.py            # Test DB e autenticação de demo
│   └── test_api.py            # Casos de QA
├── scripts/
│   ├── import_catalog.py      # Importação privada de CSV
│   ├── sample_catalog.csv
│   └── smoke_test.py          # Testes HTTP fim a fim
├── docs/
│   ├── QA_REPORT.md
│   └── CONTINUITY.md
├── Dockerfile
├── docker-compose.yml
├── docker-compose.cloud-demo.yml
├── Caddyfile
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md
```

## 11. Critérios para vender o MVP como SaaS

**Não vender esta versão como produto de produção.** Antes disso cumprir, no mínimo: banco PostgreSQL e migrations, auth real e autorização por tenant/escopo, WAF/rate limit, isolamento auditado, TLS 1.3, gestão e rotação de segredos, LGPD, backups/restauração, assinatura e validação de chamadas conforme UCP, validação formal de schemas, fluxo checkout/PSP auditado, controle de concorrência de estoque, CI/CD, políticas de faturamento, telemetria e tratamento de falhas. O roadmap detalhado está em `docs/CONTINUITY.md`.

## 9. Checkout experimental (sem pagamentos)

Somente quando `DEMO_MODE=true`. O endpoint **não está anunciado** no perfil e foi excluído do Swagger; seu uso é interno para QA. O retorno `requires_escalation` é um fluxo de laboratório, não uma autorização de compra. Exemplo:

```bash
curl -s -X POST "$API/ucp/v1/checkout-sessions" \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"line_items":[{"item":{"id":"OLEO-001"},"quantity":2}]}'
# Copie id retornado: chk_...
# POST /ucp/v1/checkout-sessions/{id}/complete -> HTTP 501, propositalmente.
```

Não envie email, nome, endereço, dados de cartão ou credenciais reais. O serviço rejeita campo `buyer` no sandbox. Em `DEMO_MODE=false`, criação de checkout retorna 501.

## 10. Testar com ChatGPT e QA

Neste chat é possível rodar a suíte em ambiente de execução de código e inspecionar os resultados, mas **não é possível manter a aplicação hospedada dentro da conversa**, nem homologar fluxos externos sem credenciais/PSP. Para retomar, envie o ZIP atualizado e peça para rodar `python -m pytest -q`, depois o smoke HTTP usando processo local. Não exponha uma chave de API nesta conversa.

```bash
python -m pytest -q
# 22 testes unitários/integrados na v0.2.0
python -m compileall -q app scripts tests
```

Em uma nova sessão, `docs/CONTINUITY.md` é a fonte de verdade para tarefas pendentes, versões e decisões. O projeto **não guarda memória de execução futura**: preserve o ZIP ou versionamento Git.

## 11. Ordem necessária para conformidade integral (próximas entregas)

1. Congelar artefatos oficiais da especificação UCP 2026-08-25 (JSON Schema/OpenAPI), validar entradas e saídas e implementar negotiation completa.
2. Resolver perfis de agentes com política SSRF segura, cache/budget de discovery, controle de redirects e verificação de autoridade e identidade.
3. Implementar assinaturas HTTP RFC 9421, digest, JWK, replay e webhooks assinados com testes de interoperabilidade.
4. Projetar identidade por merchant e substituir SQLite por PostgreSQL com migrações, isolamento e credenciais rotativas.
5. Integrar PSP homologado, fulfillment, order lifecycle, compra confirmada e refund conforme capacidades anunciadas.
6. Executar conformance e auditoria externa; só então ativar os recursos no perfil público e comercializar.
