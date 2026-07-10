# Security Review

## Objetivo

Esta aplicacao e um projeto academico com ambicao de uso real. Por isso, foram aplicadas praticas de seguranca comuns em apps Flask com formularios, base de dados, uploads e credenciais externas.

## Protecoes implementadas

### Login

A aplicacao inteira esta protegida por login.

Credenciais reais devem vir de variaveis de ambiente:

```bash
ADMIN_USERNAME
ADMIN_PASSWORD
SECRET_KEY
```

### CSRF

Todos os formularios `POST` usam token CSRF.

Exemplos:

- criar post;
- editar post;
- publicar;
- apagar post;
- apagar media;
- gerir RSS;
- guardar credenciais de API.

### SQL Injection

As queries usam parametros em vez de concatenar input do utilizador.

Frase para explicar:

> O input do utilizador nunca e usado diretamente para construir SQL.

### Validacao de input

A app valida:

- plataformas permitidas;
- estados permitidos;
- formatos permitidos por plataforma;
- limites de titulo, conteudo e hashtags;
- datas de schedule;
- media obrigatoria em formatos como Image Post, Video Post, Reel, Story e Short.

### Uploads

Camadas de protecao:

- extensoes permitidas;
- verificacao basica da assinatura do ficheiro;
- limite de tamanho;
- nomes finais por UUID;
- `secure_filename` para nome original;
- validacao de videos MP4;
- compressao de imagens quando necessario;
- remocao segura com path validation.

Formatos aceites:

- PNG;
- JPG/JPEG;
- GIF;
- WEBP;
- MP4.

### Media publishing guard rails

A app bloqueia publicacoes que nao tenham a media necessaria para o formato escolhido.

Exemplo:

- `Video Post` precisa de video;
- `Image Post` precisa de imagem;
- `Story/Reel` nao deve cair automaticamente para feed post.

Isto evita publicacoes erradas.

### Credenciais de API

Credenciais sociais sao guardadas encriptadas.

Variavel critica:

```bash
CREDENTIALS_ENCRYPTION_KEY
```

Nota importante:

> Se esta chave mudar, credenciais ja guardadas deixam de poder ser desencriptadas.

### Secrets

Secrets ficam em variaveis de ambiente:

- passwords;
- database URLs;
- SMTP;
- Supabase service role key;
- tokens de redes sociais;
- app secrets.

Nunca devem ser commitados no GitHub.

### Headers de seguranca

A app envia:

- `Content-Security-Policy`;
- `X-Content-Type-Options`;
- `X-Frame-Options`;
- `Referrer-Policy`;
- `Permissions-Policy`;
- `Strict-Transport-Security` em HTTPS.

## Pontos ainda a evoluir

- login por utilizador individual;
- roles/permissoes por equipa;
- rate limiting;
- testes automatizados de seguranca;
- auditoria automatica de dependencias;
- rotacao guiada de tokens;
- limpeza periodica de media antiga;
- CSP mais restrita quando todas as fontes externas estiverem fechadas.

## Frase para aula/recrutador

> Para alem das funcionalidades, pensei na seguranca: login, CSRF, queries parametrizadas, validacao de input, upload seguro, compressao de imagens, validacao de videos, headers de seguranca e credenciais de API encriptadas. Isto mostra que tratei o projeto como uma aplicacao real.
