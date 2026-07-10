# Final Presentation Cheatsheet

Este ficheiro e para memorizar rapidamente antes de apresentar.

## 1. Pitch de 20 segundos

> O meu projeto e uma Content Automation Platform em Python e Flask. Permite gerir posts para varias redes sociais, importar artigos por RSS, adaptar versoes por plataforma, anexar media, agendar, reciclar conteudo, publicar por API e consultar logs.

## 2. Pitch de 1 minuto

> A ideia nasceu de um problema real: gerir conteudo para varias redes sociais e repetitivo e facil de perder controlo. Por isso criei uma plataforma web que centraliza o workflow. A app importa artigos de RSS como drafts, permite adaptar o copy e formato para cada rede, aceita imagens e videos, agenda publicacoes, recicla posts evergreen e regista logs. Localmente corre com SQLite e em producao pode correr em Render com Supabase/Postgres e Supabase Storage.

## 3. Frase chave

> Nao e apenas um scheduler. E uma plataforma de automacao de conteudo.

## 4. Workflow principal

```txt
RSS ou post manual
-> draft
-> escolher redes
-> adaptar copy/formato
-> media
-> schedule
-> queue
-> publish
-> logs
```

## 5. Funcionalidades para mencionar

- Login protegido
- Dashboard
- Biblioteca de posts
- Filtros e ordenacao
- RSS intake
- Editor agrupado por artigo
- General defaults + overrides por rede
- Upload de imagens e videos
- Compressao de imagens e validacao de videos MP4
- Scheduling
- Reciclagem de posts
- Calendario mensal
- Logs
- Email report
- API Accounts
- Publicacao real em Bluesky e Facebook

## 6. Arquitetura em frase simples

> Separei o codigo em rotas, modelos, base de dados e services. Assim, cada parte tem uma responsabilidade clara.

Explicacao rapida:

- `routes.py`: paginas Flask.
- `models.py`: plataformas, formatos e limites.
- `database.py`: SQLite/Postgres.
- `scheduler.py`: CRUD de posts.
- `rss.py`: feeds RSS.
- `media.py`: uploads.
- `media_optimizer.py`: compressao de imagens e base para processamento de video.
- `publisher.py`: fila e estado de publicacao.
- `platform_publishers.py`: APIs reais.
- `security.py`: CSRF e headers.

## 7. Base de dados

Tabelas:

```txt
posts
media_assets
post_schedules
rss_feeds
rss_items
logs
social_accounts
```

Frase:

> Separei posts, media, schedules, RSS, logs e credenciais para evitar duplicacao e permitir evoluir o sistema.

## 8. Seguranca

Pontos:

- Login
- CSRF
- queries parametrizadas
- validacao de input
- validacao de uploads
- UUID nos ficheiros
- headers de seguranca
- credenciais encriptadas
- secrets fora do GitHub

Frase:

> Mesmo sendo MVP, tentei tratar seguranca como trataria numa app real.

## 9. API publishing

Estado:

- Bluesky: funciona.
- Facebook: funciona para feed/link/imagem/video.
- Facebook Stories/Reels: bloqueados ate implementar endpoints especificos.
- Instagram/Threads: estrutura pronta, em fase de credenciais e testes.
- X: roadmap/manual por limitacoes do plano/API.

Frase:

> Cada rede tem regras diferentes. Por isso a app valida formato e media antes de publicar, para evitar publicacoes erradas.

## 10. Demo rapida

1. Dashboard.
2. Posts.
3. Abrir artigo RSS agrupado.
4. Mostrar General tab.
5. Mostrar override numa rede.
6. Mostrar media/preview.
7. Mostrar calendario/schedules.
8. Mostrar API Accounts.
9. Mostrar Logs.

## 11. Se perguntarem "o que aprendeste?"

Resposta:

> Aprendi a transformar um problema real num workflow automatizado. Trabalhei com Flask, base de dados, validacao, seguranca, uploads, APIs externas, deploy e limites reais das plataformas.

## 12. Se perguntarem "o que falta?"

Resposta:

> Falta finalizar Instagram/Threads, adicionar retry/backoff mais robusto, analytics e testes automatizados. Mas a arquitetura ja foi pensada para isso.

## 13. Fecho

> Este projeto mostra backend, automacao, produto e capacidade de evoluir uma ideia academica para uma ferramenta real.
