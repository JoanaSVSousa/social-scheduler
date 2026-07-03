# Final Presentation Cheatsheet

## 1. Frase de abertura

Este projeto e uma Content Automation Platform em Python e Flask.

O objetivo nao e apenas agendar posts. O objetivo e automatizar parte do workflow de conteudo:

```txt
descobrir conteudo
criar drafts
escolher plataforma
escolher formato
anexar media
agendar
reciclar
processar queue
registar logs
enviar report
```

Se te perguntarem em linguagem simples:

> E uma ferramenta para gerir publicacoes em varias redes sociais, com automacao de RSS, agendamento, reciclagem de posts e reporting.

## 2. Problema que o projeto resolve

Gerir conteudo em muitas plataformas e repetitivo.

Cada rede social tem formatos diferentes:

- Instagram tem Story, Reel, Carousel;
- X tem posts, threads e link commentary;
- Bluesky e mais texto-first;
- TikTok e YouTube Shorts sao video-first.

Sem uma plataforma central, e facil perder:

- o que esta em draft;
- o que esta agendado;
- o que ja foi publicado;
- quais posts podem ser reutilizados;
- que conteudo novo veio de RSS.

## 3. Funcionalidades principais

### Posts

Permite criar, editar, apagar e listar posts.

Cada post tem:

- titulo;
- conteudo;
- hashtags;
- plataforma;
- formato;
- estado;
- media;
- data principal;
- datas de reciclagem.

### Plataformas

Suporta:

- Instagram;
- Facebook;
- LinkedIn;
- X;
- Threads;
- Bluesky;
- YouTube Shorts;
- TikTok.

### Formatos

Cada plataforma tem formatos proprios.

Exemplo:

```txt
Instagram -> Feed Post, Carousel, Reel, Story, Video Post
X -> Text Post, Thread, Image Post, Video Post, Link Commentary
Bluesky -> Text Post, Thread, Image Post, Video Post
```

Isto mostra que o projeto nao trata todas as redes como iguais.

### Media

Aceita imagens e videos.

Formatos aceites:

- PNG;
- JPG/JPEG;
- GIF;
- WEBP;
- MP4;
- MOV;
- M4V;
- WEBM.

### RSS intake

A area RSS e privada.

O sistema le feeds RSS e transforma itens novos em posts `Draft`.

Isto e util porque permite automatizar a descoberta de conteudo, mas manter revisao humana antes da publicacao.

### Reciclagem de posts

Um post pode ter varias datas de agendamento.

Assim, nao e preciso duplicar manualmente o mesmo conteudo.

### Reports por email

Existe um script que gera um report com:

- contadores do dashboard;
- proximos posts;
- schedules reciclados;
- plataformas;
- logs recentes.

## 4. Arquitetura

O projeto esta organizado por responsabilidades.

```txt
content_platform/
├── auth.py
├── database.py
├── models.py
├── routes.py
├── security.py
└── services/
    ├── analytics.py
    ├── media.py
    ├── publisher.py
    ├── reporting.py
    ├── rss.py
    ├── scheduler.py
    └── schedules.py
```

### Como explicar cada parte

`routes.py`

> Define as paginas e endpoints da aplicacao.

`models.py`

> Define plataformas, estados e formatos permitidos.

`database.py`

> Cria e inicializa a base de dados SQLite.

`scheduler.py`

> Gere posts: criar, editar, listar, apagar e procurar posts vencidos.

`schedules.py`

> Gere multiplas datas para reciclagem de posts.

`publisher.py`

> Simula o processamento da queue. No futuro, seria aqui que entram APIs reais.

`rss.py`

> Le feeds RSS e transforma itens novos em drafts.

`media.py`

> Gere uploads e validacao de imagens/videos.

`reporting.py`

> Gera e envia reports por email.

`security.py`

> Centraliza CSRF e headers de seguranca.

`auth.py`

> Protege a area RSS com login de admin.

## 5. Base de dados

Tabelas principais:

```txt
posts
media_assets
post_schedules
rss_feeds
rss_items
logs
```

Como explicar:

> Separei posts, media, schedules, feeds RSS e logs em tabelas diferentes para evitar misturar responsabilidades e para conseguir evoluir o sistema.

## 6. Segurança

Pontos implementados:

- queries parametrizadas contra SQL injection;
- CSRF em formularios POST;
- headers de seguranca;
- login na area RSS;
- validacao de plataforma/estado/formato;
- limites de tamanho em campos;
- validacao de uploads por extensao e assinatura;
- nomes de ficheiro gerados por UUID;
- protecao contra path traversal ao apagar media.

Frase para usar:

> Mesmo sendo um MVP academico, tentei aplicar praticas de seguranca reais: CSRF, validacao de input, queries parametrizadas e controlo de uploads.

## 7. O que ainda nao e producao completa

Ser honesta aqui conta pontos.

Ainda faltaria:

- login por utilizador individual;
- permissoes por equipa;
- HTTPS no deploy;
- storage externo para uploads;
- migrar para Postgres se for para equipa;
- testes automatizados permanentes;
- APIs reais das redes sociais.

Frase boa:

> Esta versao esta pronta como MVP funcional. Para producao real, eu evoluiria autenticacao, base de dados, storage e integracoes externas.

## 8. Demo sugerida

1. Abrir dashboard.
2. Mostrar contadores.
3. Criar post Instagram Story ou Reel.
4. Adicionar media.
5. Criar post X Thread.
6. Mostrar filtros.
7. Mostrar datas recicladas.
8. Entrar na area RSS.
9. Explicar que RSS cria drafts.
10. Mostrar logs.
11. Mostrar report dry-run:

```bash
python3 scripts/send_dashboard_report.py --dry-run
```

## 9. Perguntas provaveis

### Porque Flask?

Porque e simples, direto e bom para aprender backend, rotas, templates, formularios e arquitetura web.

### Porque SQLite?

Porque e leve e suficiente para MVP/local/PythonAnywhere. Para equipa, migraria para Postgres.

### Porque RSS?

Porque automatiza a descoberta de conteudo. Em vez de procurar manualmente noticias, a app transforma novos artigos em drafts.

### Porque nao publica diretamente nas redes?

Porque esta fase foca o workflow e a automacao interna. Publicacao real exigiria APIs, tokens, permisssoes e politicas de cada plataforma.

### O que mostra perfil de Automation Engineer?

Mostra que identifiquei um processo repetitivo, modelei estados, criei uma queue, logs, RSS intake, reciclagem e reporting.

## 10. Frase final

Este projeto demonstra backend, base de dados, seguranca, automacao e pensamento de produto. Comecou como um scheduler, mas evoluiu para uma plataforma de content operations com RSS intake, queue, reciclagem e reports.
