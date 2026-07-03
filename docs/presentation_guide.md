# Content Automation Platform - Guia de Apresentacao

## Pitch curto

Este projeto e uma plataforma de automacao para planear, agendar e acompanhar publicacoes em varias redes sociais.

Em vez de ser apenas um calendario de posts, o objetivo e representar um workflow real:

```txt
Criar conteudo
Escolher rede social
Escolher formato
Anexar media
Agendar
Processar fila
Registar resultado
```

Isto aproxima o projeto de uma ferramenta real de trabalho para criadores, pequenas equipas de marketing ou projetos como Squared Potato e Mais Algarve.

## Problema que resolve

Gerir conteudo em varias plataformas e repetitivo e facil de perder controlo:

- cada rede social tem formatos diferentes;
- alguns posts usam imagem, outros video, outros so texto;
- e preciso saber o que esta em rascunho, agendado, publicado ou falhado;
- sem logs, nao ha forma clara de perceber o que aconteceu;
- sem uma fila, a publicacao depende de verificacoes manuais.

Este projeto organiza esse processo numa unica plataforma.

## Solucao

A aplicacao permite criar posts com:

- titulo;
- conteudo;
- hashtags;
- plataforma;
- formato de conteudo;
- data e hora de agendamento;
- estado;
- anexos de media.

Tambem inclui:

- dashboard com metricas;
- listagem com filtros;
- queue de publicacao;
- logs de eventos;
- upload de imagens e videos;
- formatos especificos por plataforma.

## Redes e formatos suportados

### Instagram

Formatos:

- Feed Post;
- Carousel;
- Reel;
- Story;
- Video Post.

Isto e importante porque Instagram nao e um unico tipo de conteudo. Um Story e diferente de um Reel, e ambos precisam de media vertical 9:16.

### Bluesky

Formatos:

- Text Post;
- Thread;
- Image Post;
- Video Post.

Bluesky e mais texto-first, por isso a plataforma suporta posts simples, threads e media leve.

### X

Formatos:

- Text Post;
- Thread;
- Image Post;
- Video Post;
- Link Commentary.

X continua relevante quando ainda existe uma comunidade ativa nessa rede. Por isso, a app suporta posts curtos, threads, media e comentario sobre links/artigos.

### Outras plataformas

Tambem existem formatos para:

- Facebook;
- LinkedIn;
- X;
- Threads;
- YouTube Shorts;
- TikTok.

## Arquitetura

O projeto esta separado por responsabilidades:

```txt
content_platform/
├── database.py
├── models.py
├── routes.py
└── services/
    ├── analytics.py
    ├── media.py
    ├── publisher.py
    └── scheduler.py
```

### database.py

Responsavel pela ligacao a SQLite e pela criacao das tabelas.

Tabelas principais:

- `posts`;
- `media_assets`;
- `logs`.

### models.py

Define os estados, plataformas e formatos disponiveis.

Aqui esta a parte que torna a app mais realista, porque cada rede social pode ter formatos proprios.

### routes.py

Controla as paginas da aplicacao:

- dashboard;
- lista de posts;
- criacao;
- edicao;
- remocao;
- logs;
- processamento da fila.

### services/scheduler.py

Contem a logica de gestao dos posts:

- criar;
- editar;
- apagar;
- listar;
- procurar posts vencidos;
- mudar estados.

### services/publisher.py

Simula o processo de publicacao.

Nesta fase MVP, quando um post esta `Scheduled` e a data ja passou, o sistema muda o estado para `Published` e cria um log.

No futuro, este modulo seria o ponto de integracao com APIs reais.

### services/media.py

Gere uploads de imagens e videos.

Aceita:

- PNG;
- JPG;
- WEBP;
- GIF;
- MP4;
- MOV;
- M4V;
- WEBM.

Tambem ignora ficheiros nao suportados e mostra aviso ao utilizador.

## Estados do sistema

O projeto usa quatro estados:

- `Draft`: conteudo ainda em preparacao;
- `Scheduled`: conteudo agendado para publicacao;
- `Published`: conteudo publicado;
- `Failed`: conteudo que falhou.

Esta gestao de estado e essencial em automacao, porque permite acompanhar o ciclo de vida de cada tarefa.

## Como demonstrar

### 1. Abrir o dashboard

Explicar que o dashboard da uma visao geral:

- quantos posts estao em rascunho;
- quantos estao agendados;
- quantos foram publicados;
- quantos falharam.

### 2. Criar um post de Instagram

Exemplo:

- plataforma: Instagram;
- formato: Reel ou Story;
- media: video;
- estado: Scheduled.

Explicar que o sistema adapta o guia de media ao formato escolhido.

### 3. Criar um post de Bluesky

Exemplo:

- plataforma: Bluesky;
- formato: Thread;
- sem media ou com imagem.

Explicar que nem todas as redes sociais devem ser tratadas da mesma forma.

### 4. Mostrar filtros

Filtrar por:

- plataforma;
- estado;
- pesquisa.

Isto mostra que a aplicacao ja funciona como uma pequena ferramenta de gestao.

### 5. Processar queue

Criar ou usar um post agendado para uma hora passada.

Carregar em `Process Queue`.

Mostrar que o estado passa de `Scheduled` para `Published`.

### 6. Mostrar logs

Abrir a pagina de logs e explicar que cada acao importante fica registada.

Isto e uma pratica comum em sistemas de automacao.

## Como explicar a um recrutador

Uma boa forma de apresentar:

> Desenvolvi uma Content Automation Platform em Python e Flask para gerir o ciclo de vida de publicacoes em multiplas redes sociais. O projeto inclui CRUD, SQLite, upload de media, estados de publicacao, fila de processamento, logs e formatos especificos por plataforma. A arquitetura esta separada por services para permitir evoluir facilmente para integracoes com APIs reais, retry logic, analytics e deploy no PythonAnywhere.

## Competencias demonstradas

- Python;
- Flask;
- SQLite;
- CRUD;
- arquitetura modular;
- gestao de estado;
- upload de ficheiros;
- validacao de formatos;
- logs;
- queue processing;
- pensamento de produto;
- workflow automation;
- design de interface.

## Proximos passos tecnicos

### Prioridade 1

Melhorar a experiencia de utilizador:

- formatar datas como `23/06/2026 18:00`;
- adicionar mensagens de sucesso para criar, editar e apagar posts;
- validar que posts `Scheduled` precisam de data e hora;
- melhorar layout mobile.

### Prioridade 2

Adicionar calendario:

- vista mensal;
- posts por dia;
- filtros por plataforma.

### Prioridade 3

Adicionar analytics:

- posts por plataforma;
- posts por estado;
- formatos mais usados;
- dias com mais conteudo agendado.

### Prioridade 4

Preparar deploy:

- configurar PythonAnywhere;
- garantir paths absolutos para SQLite e uploads;
- criar script de scheduled task para processar a queue.

### Prioridade 5

Evolucao real:

- APIs de redes sociais;
- retry automatico;
- templates de conteudo;
- geracao de hashtags com IA;
- sugestoes de horario.

## Frase final para apresentacao

Este projeto comecou como um sistema de agendamento, mas foi desenhado como uma plataforma de automacao. A parte mais importante nao e apenas guardar posts, e modelar um workflow real com estados, formatos, media, fila de processamento e logs.

## Nova funcionalidade: RSS intake

Esta funcionalidade e mais privada e operacional, por isso esta protegida por login.

A ideia e permitir adicionar fontes RSS que sao verificadas periodicamente. Quando aparecem itens novos, a aplicacao transforma esses itens em posts `Draft` para as redes sociais escolhidas.

Exemplo:

```txt
RSS feed de noticias
↓
Item novo encontrado
↓
Criar draft para Instagram
Criar draft para Bluesky
Criar draft para X
Criar draft para LinkedIn
```

Isto e util porque separa duas fases:

- descoberta automatica de conteudo;
- edicao humana antes de publicar.

Para correr de hora a hora no PythonAnywhere:

```bash
python3 scripts/check_rss_feeds.py
```

Como explicar:

> Tambem adicionei uma area privada de RSS intake. O sistema pode ler feeds de hora a hora e transformar novos artigos em drafts para as plataformas em que quero trabalhar. Assim, automatizo a captura de oportunidades de conteudo, mas mantenho controlo editorial antes de publicar.

## Nova funcionalidade: reciclagem de posts

Alguns conteudos podem ser reutilizados em varias datas.

Por isso, alem da data principal, um post pode ter varias datas de reciclagem:

```txt
Post original
├── 25/06/2026 09:00
├── 27/06/2026 09:00
└── 30/06/2026 18:30
```

Isto evita duplicar manualmente o mesmo conteudo.

Como explicar:

> Em vez de criar copias iguais do mesmo post, criei uma camada de schedules. O mesmo conteudo pode voltar a entrar na fila varias vezes, o que aproxima a aplicacao de uma ferramenta real de content operations.

## Nova funcionalidade: editor agrupado por artigo RSS

Quando um artigo RSS gera posts para varias redes, esses posts ficam ligados ao mesmo artigo original.

Isto evita uma lista visualmente confusa com muitos posts quase iguais.

Fluxo:

```txt
Artigo RSS
├── versao Facebook
├── versao Bluesky
└── versao X
```

Na pagina `RSS Articles`, e possivel abrir um artigo e editar todas as versoes numa unica pagina.

Como explicar:

> Em vez de editar tres posts separados e perder contexto, agrupei os drafts por artigo de origem. Assim consigo adaptar o mesmo conteudo para Facebook, Bluesky e X numa unica vista.
