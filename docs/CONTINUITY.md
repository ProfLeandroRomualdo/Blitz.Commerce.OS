# State — v0.4.1 (2026-11-13)

Read `docs/OFFICIAL_UCP_GITHUB_QA.md` FIRST. The official GitHub release tag v2026-08-25 and commit cd78fb38e819de77d9b527d110476eccb876f1bd are pinned in `scripts/github_ucp_contracts.py` and Actions. Forty local tests passed; two PostgreSQL tests skipped. **Official CLI has not run; compliance remains unverified.** Next: push to private GitHub, run `official-ucp`, download failing report if any, fix response shapes, expand contracts; require check before merge. Keep real payments disabled.

---

# CONTINUITY — Blitz Commerce OS v0.4.0

**Data:** 2026-11-13. **Base:** ZIP v0.3.0 da mesma conversa. **Estado:**
34 passed, 2 skipped e smoke HTTP PASS (PostgreSQL real indisponível localmente). Código entregue
como `blitz-commerce-mvp-v0.4.0.zip`.

## Decisões imutáveis até revisão de produto

- Provedor cloud: Google Cloud (Cloud Run + Cloud SQL PostgreSQL 16).
- Domínio desejado: `api.blitz.ai` (titularidade e DNS não verificados).
- Repo: GitHub **privado** (arquivos/workflows criados, repo NÃO publicado).
- Pagamentos: **ADIADOS**. Não conectar PSP, não aceitar cartão ou efetuar venda.
- UCP congelado na versão `2026-08-25`; **não declarar conformidade integral**.

## Entrega técnica implementada

- `app/storage.py` fornece conexão SQLite ou PostgreSQL via `DATABASE_URL`,
  conversão de placeholders para psycopg e autocommit/BEGIN/COMMIT explícito.
- `migrations/postgres/001_initial.sql` é o esquema bootstrap idempotente.
- `app/main.py` preserva endpoints v0.3.0, atualiza versão para 0.4.0,
  readiness e advisory lock por `(tenant,idempotency_key)` no Postgres.
- `Dockerfile`, `requirements-postgres.txt`, `docker-compose.yml` preparam
  runtime Postgres/Cloud Run; localhost ports apenas, ambiente demo privado.
- `deploy/gcp/*` runbook de Cloud Run privado / Cloud SQL / secrets.
- `.github/workflows/{qa.yml,contracts-sync.yml}`: Python tests, PostgreSQL
  integration em GitHub Actions e fetch manual de schemas oficiais.
- `scripts/fetch_ucp_contracts.py`: lock SHA-256 com árvore `$ref`, domínio e
  versão aprovados. `scripts/validate_ucp_contracts.py`: diagnóstico fail-closed
  das respostas selecionadas.
- `docs/QA_REPORT.md` e README completam a documentação operacional.

## Como retomar

1. Extraia ZIP v0.4.0. Leia README, este arquivo e QA_REPORT.
2. `pip install -r requirements-dev.txt` e `python -m pytest -q`.
3. Em máquina com Docker: crie `.env` da amostra, rode `docker compose up --build -d`
   e valide `/healthz`, `/readyz`, `/docs` e carrinho.
4. Publique em GitHub **privado** seguindo README. Verifique o job
   `postgres-integration` com PostgreSQL real; corrija incompatibilidades.
5. Em GitHub Actions (workflow manual) ou máquina confiável: rode
   `python scripts/fetch_ucp_contracts.py --sync` e `--verify`.
6. Revise os artefatos oficiais e comite o lock + schemas, depois rode
   `python scripts/validate_ucp_contracts.py`; corrigir os payloads e
   negociar extensões corretas até passar testes de contrato.
7. Só após testes de contrato/segurança, criar provisioning de tenants e RLS.
8. Operador GCP poderá provisionar staging PRIVADO seguindo
   `deploy/gcp/README.md` com Cloud SQL e segredos, não acessar público.

## Lacunas / riscos técnicos

- Contratos oficiais ausentes do ZIP: DNS bloqueado neste ambiente. O script
  sync está pronto, mas **nunca foi executado com rede**.
- PostgreSQL não foi executado aqui: 2 testes reais pulados. Job CI existe,
  não há resultado do GitHub real ainda.
- O projeto anterior possui payloads UCP parciais. A versão 0.4.0 prepara
  validação, mas não corrige isso automaticamente.
- `DEMO_MODE=true` não pode ser público. `DEMO_MODE=false` ainda não possui
  onboarding/provisionamento de tenants e exige DATABASE_URL HTTPS BASE_URL.
- Isolamento multi-tenant apenas via filtros SQL e chaves; falta RLS.
- `STRICT_UCP` tem parsers limitados (RFC 8941/9421 parciais), allowlist
  manual e não cobre todas as capabilities, extensões e erros.
- Evitar confiar nas afirmações de testes e deploy sem executá-los no ambiente real.

**Prompt para próxima sessão:** “Continue Blitz Commerce OS v0.4.0 a partir
`docs/CONTINUITY.md`. Execute integração PostgreSQL, baixe/fixe contratos oficiais
2026-08-25, corrija payloads que falham validação e implemente provisioning/RLS.
Preserve testes anteriores, QA e changelog. Não anuncie conformidade integral
sem testes externos e revisões.”
