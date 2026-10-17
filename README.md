# AI Operations Room

> Versão atual: **v0.8.0** — Agent Console multi-provider com Codex Local e Ollama Local, seleção de modelo, cancelamento responsivo, persistência e projeto/CWD.

Uma sala local para observar sessões e subagentes de diferentes provedores de IA e, pela **Agent Console**, iniciar tarefas explicitamente por um runner provider-neutral.

O projeto separa duas superfícies:

- **Observabilidade global:** eventos operacionais normalizados de Claude Code, Codex e integrações suportadas. Hooks não armazenam prompts, respostas ou transcrições.
- **Agent Console:** conteúdo digitado diretamente pelo usuário pertence à própria task e pode ser persistido localmente junto da resposta final e da timeline.

Os dados locais ficam em SQLite e a interface é servida em `127.0.0.1`.

## Requisitos

- Python 3.12 ou superior
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) disponível no terminal
- Codex CLI autenticado, para tasks locais via Codex e/ou observabilidade por hooks
- Ollama local com ao menos um modelo instalado, para tasks locais via Ollama
- `OPENAI_API_KEY`, opcionalmente, para executar tasks pela integração OpenAI Agents API

## Início rápido

```powershell
uv sync --extra dev
uv run python -m backend.cli serve
```

Abra:

- Escritório: `http://127.0.0.1:8765/`
- Projetos: `http://127.0.0.1:8765/projetos`
- Agent Console: `http://127.0.0.1:8765/agent-console`

A tela **Projetos** associa diretórios locais aos nomes mostrados no Escritório e também pode fornecer contexto explícito para tasks da Agent Console.

## Claude Code

Para registrar/remover os hooks do Claude Code:

```powershell
uv run python -m backend.cli hooks-install
uv run python -m backend.cli hooks-remove
```

Os hooks nativos são traduzidos pelo `ClaudeAdapter` para o contrato provider-neutral antes da persistência.

O hook registra somente metadados operacionais como IDs, tipo de agente, diretório, razão de encerramento e horário. Ele não salva prompt nem resposta.

## Codex

O AI Operations Room possui integração baseada nos lifecycle hooks oficiais do Codex e também um `CodexTaskProvider` para a Agent Console.

```powershell
uv run python -m backend.cli codex-hooks-install
uv run python -m backend.cli codex-hooks-remove
```

Depois da instalação, abra `/hooks` no Codex e revise/confie nas definições registradas. No Windows, o instalador cria automaticamente um pequeno wrapper `.cmd` em `~/.ai-operations-room` para evitar falhas do parser de hooks com caminhos entre aspas e espaços.

Na Agent Console, o Codex pode executar uma task local no diretório do projeto selecionado. O provider detecta os flags de automação suportados pela versão instalada do CLI e mantém cancelamento cooperativo do processo.

Consulte [`docs/CODEX_INTEGRATION.md`](docs/CODEX_INTEGRATION.md) para o mapeamento e as limitações atuais.

## Ollama Local

O `OllamaTaskProvider` detecta o serviço local, lista os modelos instalados e expõe seleção de modelo diretamente na Agent Console.

Por padrão o projeto usa `http://127.0.0.1:11434`. É possível sobrescrever com `AI_OPERATIONS_ROOM_OLLAMA_URL` ou `OLLAMA_HOST`.

O modelo pode ser escolhido pela interface. Como fallback, `AI_OPERATIONS_ROOM_OLLAMA_MODEL` pode definir o modelo preferido.

Quando um projeto é selecionado, Ollama recebe apenas nome e CWD como **metadado/contexto**. Isso não concede acesso implícito ao filesystem e o provider instrui o modelo a não alegar leitura de arquivos que não tenham sido fornecidos explicitamente.

## OpenAI Agents API

A integração OpenAI usa a **Agents API**, com sessões duráveis, turnos, streaming e subagentes observáveis.

Configure a chave no ambiente antes de iniciar o servidor:

```powershell
$env:OPENAI_API_KEY="sua-chave"
uv run python -m backend.cli serve
```

A Agent Console utiliza por padrão um sandbox `openai_hosted` e o modelo configurado por `AI_OPERATIONS_ROOM_OPENAI_MODEL`.

O projeto selecionado na Agent Console é apenas metadado local para essa integração. A pasta do seu projeto **não é enviada automaticamente** ao sandbox remoto.

Consulte [`docs/OPENAI_INTEGRATION.md`](docs/OPENAI_INTEGRATION.md) e [`docs/AGENT_CONSOLE.md`](docs/AGENT_CONSOLE.md).

## Agent Console / Task Runner

A Agent Console permite:

- detectar dinamicamente providers disponíveis e suas capacidades;
- escolher provider, agente, projeto e, quando suportado, modelo;
- executar tasks via Codex Local, Ollama Local ou OpenAI Agents API;
- acompanhar `queued`, `running`, `waiting`, `completed`, `failed` ou `cancelled`;
- acompanhar uma timeline incremental de eventos;
- solicitar cancelamento sem acoplamento específico na UI;
- persistir histórico, timeline, resposta final e modelo selecionado em SQLite;
- recuperar tasks interrompidas por restart para um estado final coerente;
- excluir tasks finalizadas com remoção em cascata da timeline.

A interface usa polling de aproximadamente 1 segundo. O contrato de eventos da task é cursor-based, então SSE/WebSocket pode substituir o transporte posteriormente sem mudar a semântica do runner.

## Persistência e identidade

Sessões externas são namespaced por `source`, por exemplo:

```text
claude_code:abc123
codex:abc123
openai_api:abc123
```

Tasks locais usam seus próprios IDs e mantêm `source`, `provider_session_id`, modelo e timeline separados. O SQLite mantém separadamente sessões/eventos/execuções globais e as tabelas `task`/`task_event` da Agent Console.

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

- validações ponta a ponta reais dependem da instalação/autenticação de cada provider;
- OpenAI Agents API depende de quota/billing da API, separada da assinatura do ChatGPT;
- Ollama recebe contexto de projeto, mas não ganha acesso automático aos arquivos locais;
- Codex Local depende do CLI instalado e autenticado na máquina;
- o serviço é local e não fornece autenticação nem acesso remoto;
- macOS e Linux ainda não possuem o mesmo nível de validação do fluxo Windows.

## Inspiração visual

A sala pixel foi inspirada pelo [Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents). Os personagens e móveis deste projeto são próprios.

## Licença

Distribuído sob a [licença MIT](LICENSE).
