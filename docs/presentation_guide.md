# Supernova - Guia de Apresentacao

Este documento e um guiao para apresentar o projeto em aula ou numa entrevista. A ideia e ajudar-te a explicar o projeto sem depender de memoria perfeita.

## 1. Abertura curta

Frase para dizer:

> O meu projeto chama-se Supernova. E uma aplicacao em Python e Flask para planear, adaptar, agendar e publicar conteudo em varias redes sociais.

Versao mais simples:

> Em vez de ser apenas um scheduler, e uma pequena plataforma de automacao para gerir o ciclo de vida de posts.

## 2. O problema

Explica assim:

> Gerir conteudo em varias redes sociais e repetitivo. Temos artigos, posts, imagens, videos, datas, diferentes formatos por rede e estados como draft, scheduled, published ou failed. Sem uma plataforma central, e facil duplicar trabalho e perder controlo.

Workflow que o projeto resolve:

```txt
Descobrir conteudo
-> criar draft
-> escolher redes
-> adaptar copy
-> escolher formato
-> anexar media
-> agendar
-> publicar
-> registar logs
```

## 3. A solucao

Frase para dizer:

> A solucao foi construir uma app web que centraliza posts, RSS feeds, media, schedules, publicacao e logs.

A app permite:

- criar posts manualmente;
- importar artigos de RSS como drafts;
- agrupar versoes do mesmo artigo;
- adaptar copy por rede social;
- escolher formatos como feed post, image post, video post, story ou reel;
- adicionar media;
- agendar e reciclar conteudo;
- publicar por API quando a rede ja esta implementada;
- consultar logs para perceber o que aconteceu.

## 4. Funcionalidades principais

### Dashboard

Como explicar:

> O dashboard mostra o estado operacional da plataforma: quantos posts estao em draft, scheduled, published ou failed, quais plataformas estao em uso e que posts estao proximos.

Tambem existe uma vista de calendario mensal para visualizar e ajustar schedules.

### Posts

Como explicar:

> A pagina de posts funciona como biblioteca de conteudo. Permite pesquisar, filtrar, ordenar e abrir cada post para edicao.

Nos posts vindos de RSS, a app agrupa as versoes do mesmo artigo numa so linha para evitar lixo visual.

### Editor de artigo RSS

Como explicar:

> Quando um artigo RSS gera posts para varias redes, eu edito tudo numa pagina unica. Existe uma aba General com defaults e depois abas por rede social. Se eu nao alterar nada numa rede, ela herda o default; se alterar, fica com override proprio.

Isto demonstra pensamento de produto, porque evita scroll e repeticao.

### RSS intake

Como explicar:

> A app pode ler feeds RSS periodicamente e transformar artigos novos em posts Draft. Isto automatiza a descoberta de conteudo, mas mantem revisao humana antes da publicacao.

Exemplo:

```txt
Feed jogos
-> artigo novo
-> draft Facebook
-> draft Bluesky
-> draft X
```

### Reciclagem

Como explicar:

> Alguns conteudos sao evergreen. Em vez de duplicar posts, criei uma camada de schedules para o mesmo post poder ser publicado varias vezes em datas diferentes.

### Media

Como explicar:

> A app aceita imagens e videos, valida tipos de ficheiro, usa nomes seguros, comprime imagens quando necessario e aceita videos MP4 para publicacao por API.

Detalhe importante:

> Para manter o Render estavel, a app nao tenta converter videos dentro do pedido web. Conversao pesada de MOV/WEBM para MP4 fica pensada para um job de fundo.

### Publicacao por API

Estado atual:

- Bluesky ja publica posts reais;
- Facebook ja publica Page feed posts, links, imagens e videos;
- Instagram e Threads estao scaffolded e em teste;
- X fica em roadmap/manual porque o free plan deixou de dar acesso geral aos endpoints de publicacao.

Como explicar:

> O sistema esta preparado para publicar por API, mas cada rede tem permissoes e endpoints diferentes. Por isso implementei guard rails: se o formato ainda nao esta suportado, a app bloqueia em vez de publicar errado.

## 5. Arquitetura

Frase para dizer:

> Separei a aplicacao por responsabilidades para o projeto ser facil de evoluir.

Estrutura:

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
    ├── media_optimizer.py
    ├── platform_publishers.py
    ├── publisher.py
    ├── reporting.py
    ├── rss.py
    ├── scheduler.py
    └── schedules.py
```

Como explicar cada ficheiro:

- `routes.py`: paginas e endpoints Flask.
- `models.py`: plataformas, estados, limites e formatos.
- `database.py`: ligacao SQLite/Postgres e criacao das tabelas.
- `scheduler.py`: CRUD de posts.
- `schedules.py`: datas extra para reciclagem.
- `rss.py`: leitura e importacao de feeds.
- `publisher.py`: fila de publicacao e controlo de estados.
- `platform_publishers.py`: integracoes com APIs externas.
- `media.py`: upload, validacao e associacao de ficheiros.
- `media_optimizer.py`: compressao de imagens e base para processamento de video em background.
- `security.py`: CSRF e headers de seguranca.

## 6. Base de dados

Tabelas principais:

```txt
posts
media_assets
post_schedules
rss_feeds
rss_items
logs
social_accounts
```

Frase para dizer:

> Modelei a base de dados separando conteudo, media, schedules, feeds, logs e credenciais. Isto evita misturar responsabilidades e torna a plataforma mais extensivel.

## 7. Seguranca

Frase para dizer:

> Mesmo sendo um projeto academico, tratei seguranca como parte do produto.

Pontos implementados:

- login obrigatorio;
- CSRF em formularios POST;
- queries parametrizadas;
- validacao de plataformas, estados e formatos;
- validacao de uploads por extensao e assinatura;
- limite de tamanho de uploads;
- nomes de ficheiro gerados por UUID;
- protecao contra path traversal ao apagar media;
- headers de seguranca;
- credenciais de API guardadas de forma encriptada;
- secrets apenas por variaveis de ambiente.

## 8. Demo sugerida

Segue esta ordem numa apresentacao:

1. Abrir o dashboard e mostrar contadores.
2. Mostrar a biblioteca de posts com filtros e ordenacao.
3. Abrir um artigo RSS agrupado.
4. Mostrar a aba General e uma aba de rede social.
5. Alterar copy numa rede para explicar overrides.
6. Mostrar schedules e datas de reciclagem.
7. Mostrar upload de media e preview.
8. Mostrar API Accounts e explicar credenciais/verify.
9. Publicar um post Facebook ou Bluesky se estiver em ambiente seguro.
10. Abrir Logs e mostrar o registo da acao.

## 9. Perguntas provaveis

### Porque Flask?

Porque e simples, claro e bom para demonstrar backend, rotas, templates, formularios e arquitetura modular.

### Porque SQLite e Supabase?

SQLite e ideal para desenvolvimento local e projeto academico. Supabase/Postgres permite evoluir para uso real em equipa.

### Porque RSS?

RSS automatiza a descoberta de conteudo. A app transforma artigos novos em drafts, mas ainda permite revisao humana antes de publicar.

### Porque existem formatos por rede?

Porque redes sociais nao funcionam todas da mesma forma. Um Story, um Reel, um Post de texto e um Video Post tem necessidades diferentes.

### O que mostra perfil de Automation Engineer?

Mostra que identifiquei um processo repetitivo, modelei o workflow, criei estados, schedules, logs, jobs recorrentes, integracoes e validacoes.

## 10. Frase final

> Este projeto comecou como um scheduler, mas evoluiu para uma plataforma de content operations. Demonstra backend, base de dados, seguranca, automacao, media processing, APIs e pensamento de produto.
