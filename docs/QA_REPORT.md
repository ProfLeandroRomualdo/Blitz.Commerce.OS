# QA — v0.4.1 update

- Local: **40 passed, 2 skipped** (PostgreSQL unavailable).
- Upstream fixture pipeline tests: **6 passed**; SHA mismatch, file tampering, missing source checks included.
- `official-ucp` workflow has **not executed** in this environment due no GitHub network access. **UCP official validity: unverified.**
- GitHub CI now fails if official source cannot be retrieved, pinned release identity fails, official CLI is absent, or any selected response is invalid.
- Reports will be in GitHub Actions artifact `official-ucp-2026-08-25-qa`.

---

# QA REPORT — Blitz Commerce OS v0.4.0

Data: 2026-11-13. Relatório do **ambiente local do assistente**.

## Execução verificada

- Base v0.3.0: 28 testes aprovados antes das alterações.
- Versão v0.4.0: `python -m pytest -q` → **34 passed, 2 skipped**.
- `python -m compileall -q app scripts tests` → PASS.
- Uvicorn real HTTP smoke (`/readyz` + authenticated catalog search) → **PASS**.
- Testes cobertos: endpoints históricos, assinatura Ed25519 subset, perfil
  pinado, replay, catálogo, carrinho, cursor, estoque, idempotência,
  compatibilidade SQLite, readiness, SQL PostgreSQL e allowlist dos schemas.
- `scripts/fetch_ucp_contracts.py --verify` → **BLOQUEADO**: manifest não existe
  (não é falso positivo; processo termina com erro claro).

## Não executados aqui

- PostgreSQL real: faltam servidor Postgres, Docker e dependência psycopg neste
  container. **2 testes pulados**, executáveis por GitHub Actions com serviço
  `postgres:16-alpine`. O sucesso futuro é condição para release, não presumido.
- Container build / Docker Compose: Docker indisponível no runtime.
- Download de schemas UCP: DNS externo bloqueado no container.
- `validate_ucp_contracts.py`: exige schemas pinados e provavelmente revelará
  diferenças de payloads a corrigir.
- Cloud Run / Cloud SQL / DNS `api.blitz.ai`: não provisionados; testes de
  infraestrutura, IAM, TLS e faturamento continuam pendentes.

## Questões de segurança em aberto

1. RFC 9421/8941 completo, múltiplas assinaturas, Web Bot Auth, resolução
   permissionless segura de perfis, extensões/versions UCP.
2. Tenants atuais isolados por aplicação, **sem Row Level Security** no banco.
3. API key SHA-256 e bindings manuais precisam evoluir para gestão com escopos,
   revogação, rotação e provisionamento seguro.
4. Nonces persistidos no Postgres, mas ainda faltam análise de carga/falhas,
   limites, alertas e política de retenção/limpeza.
5. `STRICT_UCP=false` é **somente** para staging privado/demo.
6. Não há pagamento real ou emissão de pedidos, por decisão explícita.

## Gates para operar com clientes

- [ ] PostgreSQL integration job verde no GitHub Actions.
- [ ] Contratos oficiais com hashes fixados e validação de requests/responses.
- [ ] Auditoria de segurança/OWASP + pentest e SAST/DAST.
- [ ] Provisionamento seguro de tenants com RLS e identity provider.
- [ ] GCP staging privado funcionando com secret manager e backups.
- [ ] Proteção anti-abuso, logging, monitoramento e budgets.
