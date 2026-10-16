# AI Operations Room

> Versão atual: **v0.7.1** — núcleo multi-provider + OpenAI Agents API + Agent Console / Task Runner + hotfix dos hooks Codex no Windows.

Uma sala local para observar sessões e subagentes de diferentes provedores de IA e, pela **Agent Console**, iniciar tarefas explicitamente por um runner provider-neutral.

O projeto separa duas superfícies:

- **Observabilidade global:** eventos operacionais normalizados de Claude Code, Codex e integrações suportadas. Hooks não armazenam prompts, respostas ou transcrições.
- **Agent Console:** conteúdo digitado diretamente pelo usuário pertence à própria task e pode ser persistido localmente junto da resposta final e da timeline.

Os dados locais ficam em SQLite e a interface é servida em `127.0.0.1`.

## Requisitos

- Python 3.12 ou superior
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) disponível no terminal
- opcionalmente Claude Code e/ou Codex para observabilidade real dessas superfícies
- `OPENAI_API_KEY` para executar tasks pela integração OpenAI Agents API

## Início rápido

```powershell
uv sync --extra dev
uv run python -m backend.cli serve
```

Abra:

- Escritório: `http://127.0.0.1:8765/`
- Projetos: `http://127.0.0.1:8765/projetos`
- Agent Console: `http://127.0.0.1:8765/agent-console`

A tela **Projetos** associa diretórios locais aos nomes mostrados no Escritório. O caminho mais específico vence.

## Claude Code

Para registrar/remover os hooks do Claude Code:

```powershell
uv run python -m backend.cli hooks-install
uv run python -m backend.cli hooks-remove
```

Os hooks nativos são traduzidos pelo `ClaudeAdapter` para o contrato provider-neutral antes da persistência.

O hook registra somente metadados operacionais como IDs, tipo de agente, diretório, razão de encerramento e horário. Ele não salva prompt nem resposta.

## Codex

O AI Operations Room também possui integração baseada nos lifecycle hooks oficiais do Codex.

```powershell
uv run python -m backend.cli codex-hooks-install
uv run python -m backend.cli codex-hooks-remove
```

Depois da instalação, abra `/hooks` no Codex e revise/confie nas definições registradas. No Windows, o instalador cria automaticamente um pequeno wrapper `.cmd` em `~/.ai-operations-room` para evitar falhas do parser de hooks com caminhos entre aspas e espaços. O fluxo real foi validado com Codex CLI e sessão `codex` aparecendo no Operations Room.

Consulte [`docs/CODEX_INTEGRATION.md`](docs/CODEX_INTEGRATION.md) para o mapeamento e as limitações atuais.

## OpenAI Agents API

A primeira integração OpenAI escolhida é a **Agents API**, porque ela expõe sessões duráveis, turnos, eventos de streaming e subagentes observáveis sem depender de eventos internos do ChatGPT comum.

Configure a chave no ambiente antes de iniciar o servidor:

```powershell
$env:OPENAI_API_KEY="sua-chave"
uv run python -m backend.cli serve
```

A Agent Console utiliza por padrão um sandbox `openai_hosted` e o modelo configurado por `AI_OPERATIONS_ROOM_OPENAI_MODEL` (padrão atual: `gpt-6-astra`).

O projeto selecionado na Agent Console é apenas metadado local nesta versão. A pasta do seu projeto **não é enviada automaticamente** ao sandbox remoto.

Consulte [`docs/OPENAI_INTEGRATION.md`](docs/OPENAI_INTEGRATION.md) e [`docs/AGENT_CONSOLE.md`](docs/AGENT_CONSOLE.md).

## Agent Console / Task Runner

A Agent Console permite:

- escolher provider, agente e projeto;
- criar uma task provider-neutral;
- acompanhar `queued`, `running`, `waiting`, `completed`, `failed` ou `cancelled`;
- acompanhar uma timeline incremental de eventos;
- solicitar cancelamento;
- ver a resposta final;
- consultar histórico local de tasks.

A primeira versão usa polling de aproximadamente 1 segundo. O contrato de eventos da task é cursor-based, então SSE/WebSocket pode substituir o transporte posteriormente sem mudar a semântica do runner.

## Persistência e identidade

Sessões externas são namespaced por `source`, por exemplo:

```text
claude_code:abc123
codex:abc123
openai_api:abc123
```

Isso evita colisões entre provedores. O SQLite mantém separadamente sessões/eventos/execuções globais e as tabelas `task`/`task_event` da Agent Console.

Por padrão os dados ficam em `~/.ai-operations-room`. Use `AI_OPERATIONS_ROOM_DATA_DIR` para apontar outra pasta.

## Demonstração

O modo demo usa uma fila e um banco separados em `~/.ai-operations-room-demo`:

```powershell
uv run python -m backend.cli demo --serve
```

Ele não depende de uma sessão real de Claude/Codex/OpenAI.

## Abrir automaticamente ao entrar no Windows

Depois de preparar o ambiente, você pode iniciar o servidor em segundo plano com:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-room.ps1
```

O script usa a porta 8765 por padrão. Para outra porta, acrescente `-Port 8898`.

## Desenvolvimento

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp=.test-temp
node --check frontend/app.js
node --check frontend/agent-console.js
node --test tests/js/pixel.test.js
```

A CI do GitHub executa a suíte Python, valida a sintaxe JavaScript e roda os testes do frontend.

Consulte também [`ARCHITECTURE.md`](ARCHITECTURE.md), [`DEVELOPMENT.md`](DEVELOPMENT.md), [`HANDOFF.md`](HANDOFF.md) e os documentos em [`docs/`](docs/).

## Limites atuais

- validações ponta a ponta reais dependem de acesso/autenticação de cada provedor;
- a Agent Console executa primeiro via OpenAI Agents API; Claude/Codex ainda são fontes de observabilidade, não `TaskProvider`s do console;
- seleção de projeto na Agent Console não transfere arquivos locais ao provider;
- o serviço é local e não fornece autenticação nem acesso remoto;
- macOS e Linux ainda não possuem o mesmo nível de validação do fluxo Windows.

## Inspiração visual

A sala pixel foi inspirada pelo [Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents). Os personagens e móveis deste projeto são próprios.

## Licença

Distribuído sob a [licença MIT](LICENSE).
