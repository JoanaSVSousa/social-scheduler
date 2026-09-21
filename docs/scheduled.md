# Scheduled: auditoria e verificação

## Diagnóstico antes da implementação

O checkout não tinha `/scheduled`, causando 404 do Flask. Isto confirma a causa no código local; não foi consultado o serviço em Render nem verificada a revisão que está publicada.

Framework: Flask 3/Jinja, factory `content_platform.create_app`, entrada `app.py`, Gunicorn `app:app` (Procfile/render.yaml). Rotas no blueprint `main` em `content_platform/routes.py`: dashboard `/`; biblioteca `/posts`; criação/edição `/posts/new`, `/posts/<id>/edit`; operações de publicação, eliminação e biblioteca sob `/posts`; edição/reagendamento sob `/calendar`; `/queue/process`; RSS sob `/rss`; integrações/OAuth sob `/settings/social-accounts`; `/logs`, `/login`, `/logout`; políticas `/privacy`, `/terms`, callbacks `/meta`; relatório `/internal/reports/daily`. `/healthz` está na factory.

A biblioteca `templates/posts.html` utiliza GET `/posts?status=Scheduled&sort=scheduled_asc`, sem tab específica nem API JSON. O controller chama `get_all_posts`, `get_media_for_posts` e `get_schedules_for_posts`; agrega versões RSS e permite escrita. Também chama `refresh_rss_content_types` durante GET, pelo que não é adequada para reutilização directa numa vista estritamente de leitura.

Schema SQLite/Postgres em `content_platform/database.py`; dataclass Post e estados em `models.py`: Draft, Scheduled, Published, Failed. Drafts são linhas de `posts`, sem tabela separada. Datas principais: `posts.scheduled_at`; ocorrências: `post_schedules.scheduled_at`, `status`, `published_at`. Existem `created_at`/`updated_at` em posts e `created_at` nas ocorrências. Media em `media_assets`, URL RSS em `rss_items.url`; posts manuais não têm coluna de URL. Erros são logs ERROR associados ao post, sem associação fiável a uma ocorrência específica.

Datas agendadas são texto local, normalmente `YYYY-MM-DDTHH:MM`, sem fuso por post. `services/clock.py` usa APP_TIMEZONE, por omissão Europe/Lisbon, com fallback para esse fuso. Horas ambíguas na mudança de hora não têm informação suficiente para reconstruir a intenção original; a vista usa fold=0 do ZoneInfo. Não altera as datas guardadas nem a interpretação do publicador.

Autenticação por sessão (`admin_authenticated`, `user_role`); papéis existentes admin/editor. Não existe papel Designer. Os novos GET usam a protecção global existente e estão disponíveis a utilizadores autenticados, incluindo editor. Não foram alteradas permissões nem as operações de escrita já disponíveis noutras páginas.

Não existiam testes de rotas/posts neste checkout; os workflows existentes executam RSS, publicação e relatórios.

## Implementação

- GET `/scheduled`: template Jinja com loading inicial e navegação existente, sem acções de edição/publicação.
- GET `/api/scheduled`: adaptador JSON de leitura sobre serviços/modelos existentes; resposta `{"posts": [...]}`, no-store; falha de leitura devolve 503 com erro genérico.
- Serviço `scheduled_view.py`: reutiliza os serviços de posts, schedules e media. Consulta somente RSS/logs adicionais. Não chama rotinas de actualização ou publicação.
- Ocorrências Scheduled são a fonte autoritativa quando existem linhas em post_schedules, tal como no publicador. A data principal só é usada quando não existem ocorrências e o post é Scheduled. Cada ocorrência/rede ocupa uma entrada; drafts/publicados sem ocorrência pendente não aparecem. Um post Published/Draft com ocorrência Scheduled aparece com ambos os estados explícitos, reflectindo os dados que o publicador consulta.
- Ordenação por instante; exibição de fuso IANA e offset UTC por data. Datas ausentes/inválidas aparecem no fim, com aviso.
- Media apresentados como nomes/tipos, seguindo o padrão textual da biblioteca; origem/URL quando guardada. Último erro identificado como histórico do post.
- JavaScript usa apenas GET e textContent; loading, timeout/offline (15 segundos), HTTP 404, outros erros, sessão expirada e resposta vazia são distintos. Só uma resposta HTTP bem sucedida com posts=[] mostra “Não existem posts agendados”. Uma rota de página desconhecida mantém o 404 normal do Flask.

Ficheiros: routes.py, base.html; novos scheduled_view.py, scheduled.html, scheduled.js, testes Python/Node e este documento. Sem migrações, dependências adicionais, alterações ao Render ou credenciais.

## Executar localmente

Na raiz do projecto, com Python 3.12 e Node instalado:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
node --test tests/scheduled.test.cjs
```

Os testes substituem DATABASE_URL por uma string vazia e ambos os caminhos SQLite por uma base temporária. Dados inteiramente sintéticos; não fazem chamadas de publicação, RSS ou serviços externos. Verificam login/editor, GET exclusivo, inexistência de alterações na BD, duplicação/estados, datas de inverno/verão, origem/media/erros e falhas. Os testes Node verificam o controlador com DOM/fetch simulados, incluindo loading enquanto a resposta está pendente.

Para iniciar uma instância local isolada, sem abrir a base existente nem carregar credenciais de produção:

```sh
env -u DATABASE_URL SESSION_COOKIE_SECURE=0 .venv/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import content_platform
import content_platform.database as database
with TemporaryDirectory() as directory:
    path = Path(directory) / 'local.db'
    database.DEFAULT_DB_PATH = path
    content_platform.DEFAULT_DB_PATH = path
    content_platform.create_app().run(port=5000, debug=False)
PY
```

Abrir http://127.0.0.1:5000/login, usar a conta local configurada (defaults documentados em auth.py), depois `/scheduled`. A base temporária começa vazia e é removida ao parar. Os testes criam os exemplos com posts; não é necessário publicar para verificar listagem.

## Verificar no Render depois de revisão humana e deploy autorizado

Não foi feito deploy. A instalação actualmente publicada só passará a servir a rota depois de receber esta alteração.

1. Confirmar a revisão publicada e iniciar sessão com conta existente de editor.
2. Abrir `/scheduled`: HTTP 200, loading, seguido de dados ou vazio confirmado. Em Network, confirmar GET `/api/scheduled`, HTTP 200 e JSON `posts`.
3. Comparar ocorrências e fusos com dados já existentes. Não criar, apagar, publicar ou reagendar dados de produção para testar. Confirmar que não há duplicação da data principal e que ambos os estados são visíveis.
4. Para loading/timeout/404/503 usar testes locais ou interceptação de rede no navegador de desenvolvimento; não alterar Render ou a BD para provocar falhas. Confirmar que nenhuma falha mostra a mensagem de vazio.
5. Sem sessão, confirmar redireccionamento para login. Uma página desconhecida continua a devolver 404.

Limites: validação automatizada realizada em SQLite e DOM simulado; não cobre integração real Postgres/Render nem teste visual completo de navegador. Consultas de leitura carregam a biblioteca e logs de erro completos, à semelhança da biblioteca existente; volumes grandes podem justificar paginação numa fase futura.
