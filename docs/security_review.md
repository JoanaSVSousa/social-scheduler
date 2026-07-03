# Security Review

## Objetivo

Esta aplicacao e um projeto academico, mas foi endurecida com praticas comuns de seguranca para uma app Flask com formularios, SQLite e upload de ficheiros.

## Protecoes implementadas

### Area protegida

A area de RSS intake esta protegida por login de admin.

Agora a aplicacao inteira tambem esta protegida por login, para nao expor posts, RSS, logs ou dados editaveis.

Em desenvolvimento existe uma password local por defeito, mas para uso real deve ser configurada por variavel de ambiente.

O username tambem pode ser configurado por `ADMIN_USERNAME`.

### SQL Injection

As queries usam parametros `?` do SQLite.

Isto evita concatenar diretamente input do utilizador em SQL.

### CSRF

Todos os formularios `POST` usam token CSRF.

Rotas protegidas:

- criar post;
- editar post;
- apagar post;
- apagar media;
- processar queue.

Se um pedido `POST` nao tiver token valido, a app responde com `400 Bad Request`.

### Uploads

Os uploads sao protegidos por varias camadas:

- extensoes permitidas;
- nomes reais limpos com `secure_filename`;
- nome final gerado por UUID;
- limite de tamanho por ficheiro;
- limite global de request;
- verificacao basica da assinatura do ficheiro;
- ficheiros nao suportados sao ignorados e mostram aviso.

Formatos aceites:

- PNG;
- JPG/JPEG;
- GIF;
- WEBP;
- MP4;
- MOV;
- M4V;
- WEBM.

### Path Traversal

Os ficheiros guardados usam nomes gerados pela aplicacao, nao nomes fornecidos pelo utilizador.

Ao apagar media, o caminho e resolvido e verificado para garantir que pertence a pasta de uploads.

### Validacao de dados

A app valida:

- plataforma permitida;
- estado permitido;
- formato valido para a plataforma escolhida;
- titulo obrigatorio e com limite;
- conteudo obrigatorio e com limite;
- hashtags com limite;
- posts `Scheduled` precisam de data/hora.

### Headers de seguranca

A app envia headers de seguranca:

- `Content-Security-Policy`;
- `X-Content-Type-Options`;
- `X-Frame-Options`;
- `Referrer-Policy`;
- `Permissions-Policy`.

## Pontos ainda a evoluir

Para producao real, os proximos passos seriam:

- usar `SECRET_KEY` forte via variavel de ambiente;
- manter `debug` desligado em producao (`FLASK_DEBUG=1` apenas em desenvolvimento local);
- usar HTTPS;
- adicionar autenticacao/login;
- adicionar autorizacao por utilizador;
- guardar uploads fora da pasta publica e servir com controlo de acesso;
- adicionar rate limiting;
- criar testes automatizados de seguranca;
- auditar dependencias.

## Como explicar a um recrutador

> Alem da funcionalidade principal, preocupei-me com a seguranca da aplicacao. A app usa queries parametrizadas, tokens CSRF, validacao de input, verificacao de uploads, nomes de ficheiro gerados por UUID e headers de seguranca. Isto mostra que pensei no projeto como uma aplicacao real, nao apenas como um prototipo academico.
