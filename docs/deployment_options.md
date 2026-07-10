# Deployment Options

## Objetivo

O projeto foi desenhado para correr em dois modos:

- localmente, para desenvolvimento e testes;
- online, para uso real por uma equipa pequena.

## Opcao A: Local + SQLite

Melhor para:

- desenvolvimento;
- testes de funcionalidades;
- apresentacao em aula;
- demo sem custos.

Como corre:

```bash
python3 app.py
```

Base de dados:

```txt
data/scheduler.db
```

## Opcao B: Render + Supabase

Melhor para:

- equipa pequena;
- uso real online;
- RSS checks recorrentes;
- API publishing;
- storage publico para media;
- Postgres em producao.

Componentes:

```txt
Render Web Service
-> Flask + Gunicorn

Supabase Postgres
-> dados da aplicacao

Supabase Storage
-> imagens/videos publicos usados pelas APIs

Render Cron Job
-> RSS check de 2 em 2 horas
```

## Variaveis de ambiente

Nunca guardar valores reais no GitHub.

Essenciais:

```bash
SECRET_KEY="long-random-secret"
CREDENTIALS_ENCRYPTION_KEY="generated-fernet-key"
ADMIN_USERNAME="SquaredRedes"
ADMIN_PASSWORD="strong-password"
DATABASE_URL="postgresql://USER:PASSWORD@POOLER_HOST:6543/postgres?sslmode=require"
```

Supabase Storage:

```bash
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="server-only-service-role-key"
SUPABASE_MEDIA_BUCKET="social-media"
```

Opcional para video:

```bash
FFMPEG_BINARY="/usr/bin/ffmpeg"
```

## Supabase/Postgres

Em desenvolvimento, a app usa SQLite.

Em producao, se `DATABASE_URL` existir, usa Supabase/Postgres.

No Render, usar preferencialmente o pooler do Supabase:

```txt
postgresql://USER:PASSWORD@POOLER_HOST:6543/postgres?sslmode=require
```

Isto evita problemas de IPv6 que podem acontecer com o host direto.

## Supabase Storage

Meta APIs precisam de URLs publicos para publicar imagens e videos.

Por isso:

1. criar bucket no Supabase;
2. usar nome configurado em `SUPABASE_MEDIA_BUCKET`;
3. tornar o bucket publico ou garantir public URLs;
4. configurar `SUPABASE_SERVICE_ROLE_KEY` apenas no Render.

Nunca expor `SUPABASE_SERVICE_ROLE_KEY` no frontend.

## Render Cron Jobs

RSS automation:

```bash
python3 scripts/check_rss_feeds.py
```

Schedule recomendado:

```txt
0 */2 * * *
```

O Cron Job deve usar as mesmas variaveis de ambiente do Web Service.

## Checklist antes de mostrar a recrutador

- GitHub publico sem secrets reais.
- `.env` fora do repo.
- `.env.example` com placeholders.
- `data/scheduler.db` fora do repo.
- uploads reais fora do repo.
- README atualizado.
- app com login ativo.
- Render deploy funcional.
- Supabase conectado.
- pelo menos um exemplo real de publicacao/log.

## Roadmap de producao

- retry/backoff para publicacoes falhadas;
- testes automatizados;
- verificacao de API em todas as redes;
- storage lifecycle/cleanup;
- roles por utilizador;
- monitorizacao de jobs recorrentes.
