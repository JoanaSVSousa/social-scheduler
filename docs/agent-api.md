# API operacional de agentes — v1

API operacional para leitura e classificação. A publicação do código não activa credenciais técnicas: é necessário configurar os hashes no ambiente privado do servidor. Nenhum lote de produção é executado durante os testes.

## Diagnóstico

Os erros de owner CUA, X11/MIT-SHM e capturas pertencem ao ambiente remoto descrito no relatório; não foram reproduzidos nem corrigidos aqui. A aplicação gera Posts com HTML/Jinja, tabelas, links, inputs e selects reais. O dashboard existente é `/`; foi adicionado o alias `/dashboard`. A diferença entre posts e ocorrências não implica perda de dados: a API agora declara explicitamente ambas as contagens.

Um problema confirmado no código era a reclassificação RSS durante GET `/` e `/posts`. Essas chamadas foram retiradas: consultar páginas não deve sobrescrever classificação manual. A classificação automática durante importação RSS continua existente. Edições explícitas de grupos RSS continuam a afectar os posts do grupo.

## Autenticação

Todas as novas rotas abaixo exigem `Authorization: Bearer <token>`. Cookies, incluindo cookies de admin, não dão acesso a esta API. Não há CORS adicional, token em URL ou herança de permissões para as rotas HTML.

Configurar no ambiente privado do servidor apenas hashes SHA-256 hexadecimais de tokens aleatórios fortes:

- `SUPERNOVA_AGENT_READ_TOKEN_SHA256`: leitura.
- `SUPERNOVA_AGENT_CLASSIFY_TOKEN_SHA256`: leitura e PATCH de classificação.
- `SUPERNOVA_AGENT_MANAGE_TOKEN_SHA256`: leitura, classificação, criação/edição de posts, publicação imediata e eliminação de artigos RSS.

Valores vazios/desconhecidos: 401 JSON. Token de leitura a tentar escrever: 403. O token de classificação só altera classificações. O token de gestão pode criar posts de texto como rascunho/agendados, editar posts ainda não publicados, pedir publicação imediata em plataformas com publisher implementado e eliminar um artigo RSS por chamada. Apagar um artigo RSS remove o artigo e as versões de posts associadas do Supernova, mas não apaga cópias já publicadas nas redes. Não permite apagar posts sem artigo RSS, gerir integrações ou criar utilizadores. As sessões humanas existentes conservam as suas próprias permissões.

Usar tokens distintos e aleatórios com pelo menos 32 bytes de entropia, guardar o token original num secret manager e fornecer ao processo agente por variável de ambiente. Não adicionar tokens ao repositório. Revogação/rotação: remover/substituir o hash no servidor. Existem três níveis de credencial; a auditoria identifica a credencial por uma impressão digital.

## Contrato

OpenAPI: `docs/agent-api.openapi.json`.

| Método/rota | Semântica |
| --- | --- |
| GET `/api/version` | Versão do contrato, revisão Render quando disponível e capacidades do token |
| GET `/api/posts` | Posts individuais, sem agregação de redes; paginação por ID |
| GET `/api/posts/{id}` | Post, artigo RSS, media e ocorrências |
| GET `/api/posts/{id}/verify` | Nova leitura do mesmo post para confirmação posterior |
| PATCH `/api/posts/{id}/classification` | Apenas `source_type` e timestamp do post alvo, com auditoria |
| POST `/api/posts` | Criar post de texto como rascunho ou agendado; requer token de gestão e `client_request_id` |
| PATCH `/api/posts/{id}` | Editar título, copy, hashtags e agendamento de post não publicado; requer versão e `client_request_id` |
| POST `/api/posts/{id}/publish` | Publicação imediata explícita; requer versão, `reason` e `client_request_id` |
| POST `/api/rss/articles/{id}/delete` (ou DELETE `/api/rss/articles/{id}`) | Eliminar um artigo RSS e as versões associadas no Supernova; requer `expected_title`, `expected_url` e `reason` |
| GET `/api/dashboard` | Contagens com unidades explícitas |
| GET `/api/scheduled/posts` | Posts distintos que têm ocorrências pendentes |
| GET `/api/scheduled/occurrences` | Ocorrências pendentes com identificador explícito |

A antiga `/api/scheduled` continua a servir a vista HTML por sessão; os agentes usam as duas novas rotas de scheduled com Bearer.

`/api/posts` aceita `status=draft|scheduled|published|failed`, `classification=all_green|news`, `article_id=<inteiro>`, `page` (>=1) e `per_page` (1–100, default 50). Filtros inválidos/desconhecidos dão 400. Resultado: `{posts: [...], total, page, per_page}`. Lista vazia é sucesso 200 com `posts: []`.

Post: `id`, `title`, `status`, `classification`, `source_type`, `article_id`, `article_url`, `article_title`, `platform`, `content_format`, `copy`, `hashtags`, `media`, `scheduled_at`, `timezone`, `occurrences`, `created_at`, `updated_at`, `version`. Media inclui ID, nome original, tipo e public_url; o URL pode estar vazio para ficheiros locais. Datas são as datas reais guardadas; datas de agendamento sem offset usam APP_TIMEZONE (default Europe/Lisbon). Timestamps created/updated da BD são devolvidos sem conversão inventada.

`article_id` é o ID interno de `rss_items`, NÃO o ID WordPress. Artigos manuais sem relação RSS têm campos de artigo nulos. A classificação operacional usa `source_type`: Regular = all_green, News = news. São etiquetas existentes, não prova de revisão editorial. Não é possível inferir se um Regular já foi revisto por um humano. `ambiguous` e `unclassified` são rejeitados: se a evidência for ambígua, o agente deve registar a dúvida fora do post e não alterar a classificação. A API não decide a regra editorial automaticamente.

O token de gestão pode criar posts sem media (rascunho por omissão ou agendado se `scheduled_at` for dado). Exemplo de criação:

```json
{
  "title": "Título interno",
  "copy": "Texto para publicar",
  "platform": "Bluesky",
  "hashtags": "",
  "source_type": "Regular",
  "client_request_id": "UUID-da-operação"
}
```

Editar só é permitido em posts Draft, Scheduled ou Failed; campos aceites: `title`, `copy`, `hashtags`, `scheduled_at`, mais `expected_version` e `client_request_id`. `scheduled_at` pode ser `null` para remover o agendamento. Publicar é uma operação externa e explícita, apenas para posts em Draft, Scheduled ou Failed e plataformas com publicação implementada. A operação muda temporariamente o estado para `Publishing`, usa o publisher existente e guarda um recibo idempotente; se o processo cair a meio, o mesmo pedido fica bloqueado em `publish_in_progress` para evitar duplicar uma publicação incerta. Posts que precisam de media não podem ser criados com media por esta API; edições de posts publicados nas redes também não são suportadas.

Eliminar um artigo RSS requer o título e URL exactos lidos anteriormente; é uma chamada por artigo, sem eliminação em lote:

```json
{
  "expected_title": "Título exacto do artigo",
  "expected_url": "https://example.test/article",
  "reason": "Motivo editorial da remoção"
}
```

A resposta `deleted_posts` indica quantas versões internas foram removidas. Uma remoção só afecta dados do Supernova e os media associados; não remove publicações externas.

PATCH obrigatório, sem campos adicionais:

```json
{
  "classification": "news",
  "reason": "Justificação editorial fundamentada",
  "expected_version": "<version exacta devolvida pelo GET>",
  "client_request_id": "<UUID único por operação lógica>"
}
```

`version` é uma string opaca SHA-256 do estado da linha, não um contador. Detecta alterações de outros agentes, da UI e dos workers, mesmo que estes não incrementem um contador. Não cobre mudanças apenas no artigo/media/ocorrências: a operação modifica exclusivamente a classificação da linha de post. O cliente deve tratar a string como opaca.

A API bloqueia a linha durante a alteração (Postgres FOR UPDATE; SQLite BEGIN IMMEDIATE). A operação, auditoria e log são confirmados na mesma transacção. Se a auditoria falhar, a classificação é revertida. Adiciona apenas a tabela `agent_operations`, de forma idempotente através de init_db.

Resposta: `ok`, `operation_id`, `post_id`, `previous_classification`, `classification`, `version`, `changed`, `readback`, `post`, `already_applied`. Uma classificação já igual não altera a linha (`changed=false`), mas regista a operação para repetição segura.

Repetir o mesmo client_request_id com corpo e post idênticos devolve o recibo original e `already_applied=true`. Reutilizar a chave com outro conteúdo dá 409 `idempotency_conflict`. A chave é limitada à identidade da credencial; conservar a mesma credencial durante retries. O recibo repetido é histórico: fazer GET `/verify` para saber o estado actual, especialmente se outro escritor tiver entretanto alterado o post. Versão desactualizada dá 409 `version_conflict`, sem escrita. Não renovar a versão e sobrescrever automaticamente: reler e reavaliar a decisão.

A alteração é por post/rede e não altera o artigo ou as restantes redes. Uma edição explícita posterior do grupo na UI pode alterar novamente a classificação de vários posts. Copy, hashtags, media, plataforma, formato, estado e agendamentos ficam intactos no PATCH.

Dashboard: `scheduled_posts` conta linhas cujo estado é Scheduled; `scheduled_occurrences` conta ocorrências pendentes segundo as mesmas regras da vista Scheduled; `posts_with_pending_occurrences` conta os IDs distintos dessas ocorrências. Um post Published pode ter uma ocorrência futura Scheduled, pelo que estas contagens podem legitimamente diferir. `updated_at` é a hora da consulta, não uma promessa de snapshot transaccional entre todas as consultas. Ocorrências sintéticas usam `post:<id>:primary`, ocorrências persistidas `schedule:<id>`; não são inventados external_id/confirmed_at que não existem no modelo.

Erros: 400 validação, 401 autenticação, 403 capacidade insuficiente, 404 post inexistente, 409 conflito, 413 payload excessivo, 503 falha interna genérica. Todas as respostas das rotas da API têm Cache-Control: no-store. Rotas inexistentes fora do blueprint mantêm o comportamento Flask existente.

## Testes e operação local

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/scheduled.test.cjs
```

Os testes usam SQLite temporária, tokens sintéticos e ambiente isolado de DATABASE_URL. Cobrem leitura, filtros/paginação, auth, ausência de herança de sessão, alteração limitada, auditoria, concorrência, retry, versão obsoleta, rollback em falha de auditoria, contagens e ausência de escrita durante consulta da UI.

Para correr o servidor com base descartável, usar o comando de `docs/scheduled.md`, fornecendo apenas os hashes dos tokens de teste no ambiente desse processo. Para o cliente, disponibilizar o token no seu ambiente privado como `SUPERNOVA_AGENT_TOKEN` e usar o CLI abaixo; não colocar tokens na linha de comandos.

```sh
python3 scripts/supernova_agent.py --base-url http://127.0.0.1:5000 list --status draft
python3 scripts/supernova_agent.py --base-url http://127.0.0.1:5000 get 123
python3 scripts/supernova_agent.py --base-url http://127.0.0.1:5000 classify 123 --classification news --reason 'Motivo fundamentado' --expected-version '<version>' --request-id '<UUID>'
python3 scripts/supernova_agent.py --base-url http://127.0.0.1:5000 create --title 'Título interno' --copy 'Texto' --platform Bluesky --request-id '<UUID>'
python3 scripts/supernova_agent.py --base-url http://127.0.0.1:5000 edit 123 --copy 'Texto revisto' --expected-version '<version>' --request-id '<UUID>'
python3 scripts/supernova_agent.py --base-url http://127.0.0.1:5000 publish 123 --expected-version '<version>' --reason 'Aprovado' --request-id '<UUID>'
python3 scripts/supernova_agent.py --base-url http://127.0.0.1:5000 delete-article 123 --expected-title 'Título exacto' --expected-url 'https://example.test/article' --reason 'Duplicado'
```

O CLI envia PATCH e depois GET verify para classificações; gestão usa `client_request_id`, versão esperada e recibos para repetição segura. Não resolve conflitos silenciosamente. A API não disponibiliza upload de media: criar posts de formatos que exigem media é rejeitado. Sem MCP nesta fase: API + CLI são suficientes para integração sem browser.

Validação em 22/09/2026: 21 testes Python (incluindo 4 testes de integração em Postgres 16 descartável) e 9 testes JavaScript passaram. Postgres validou migração idempotente, RLS na nova tabela, leitura, concorrência entre operações distintas, retry simultâneo, conflitos e rollback de classificação quando a auditoria falha. Nenhum dado de produção foi usado. A tabela agent_operations activa RLS e revoga acessos PUBLIC/anon/authenticated quando esses papéis existem, mantendo acesso pelo proprietário da tabela. Antes de executar lotes, configurar credenciais por canal privado e confirmar a regra editorial. Não são necessárias permissões de publicação para classificar.

Para repetir integração: iniciar Postgres local descartável com base chamada `supernova_test` e definir `SUPERNOVA_TEST_POSTGRES_URL` ao correr unittest. Os testes recusam hosts remotos e outros nomes de base; limpam exclusivamente os dados de teste nessa base. Sem essa variável, os 4 testes Postgres ficam explicitamente skipped.

Rollback de código: voltar à revisão `fcbbfb2` se necessário. A tabela adicional pode permanecer sem uso; não a apagar para fazer rollback, pois contém auditoria. Remover hashes dos tokens revoga acesso técnico sem alterar credenciais humanas ou sociais.
