const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

const statusLabels = {
  queued: 'Na fila',
  running: 'Executando',
  waiting: 'Aguardando',
  completed: 'Concluída',
  failed: 'Falhou',
  cancelled: 'Cancelada',
};
const sourceLabels = {
  openai_api: 'OpenAI Agents API',
  codex: 'Codex',
  claude_code: 'Claude Code',
};
const finalStatuses = new Set(['completed', 'failed', 'cancelled']);

let providers = [];
let agents = [];
let projects = [];
let tasks = [];
let selectedTask = null;
let timeline = [];
let cursor = 0;
let pollHandle = null;

async function request(method, path, body) {
  const response = await fetch('/api' + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Não foi possível concluir a ação.');
  return data;
}

function showNotice(message, error = false) {
  const target = $('#notice');
  target.textContent = message;
  target.classList.toggle('error', error);
  target.hidden = false;
}

function sourceName(source) {
  return sourceLabels[source] || source || 'Provider';
}

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString('pt-BR');
}

function renderProviderCatalog() {
  const source = $('#task-source');
  source.innerHTML = providers.map((provider) => (
    `<option value="${esc(provider.source)}" ${provider.available ? '' : 'disabled'}>` +
    `${esc(sourceName(provider.source))}${provider.available ? '' : ' — indisponível'}</option>`
  )).join('');

  const available = providers.filter((provider) => provider.available);
  $('#provider-state').textContent = available.length
    ? `${available.length} provider(s) disponível(is)`
    : 'Nenhum provider disponível';

  const openai = providers.find((provider) => provider.source === 'openai_api' && provider.available);
  if (openai) source.value = 'openai_api';

  $('#task-agent').innerHTML = agents.map((agent) => (
    `<option value="${esc(agent)}">${esc(agent)}</option>`
  )).join('');

  $('#task-project').innerHTML = '<option value="">Sem projeto</option>' + projects
    .filter((project) => !project.arquivado)
    .map((project) => `<option value="${project.id}">${esc(project.nome)}</option>`)
    .join('');
}

function renderTasks() {
  const root = $('#task-list');
  if (!tasks.length) {
    root.innerHTML = '<p class="empty">Nenhuma task criada.</p>';
    return;
  }
  root.innerHTML = tasks.map((task) => {
    const selected = selectedTask?.id === task.id ? ' selected' : '';
    const preview = task.prompt.length > 70 ? `${task.prompt.slice(0, 70)}…` : task.prompt;
    return `<button class="console-task-card${selected}" type="button" data-task-id="${esc(task.id)}">
      <span class="console-task-card-top"><strong>${esc(task.agent)}</strong><span class="console-status status-${esc(task.status)}">${esc(statusLabels[task.status] || task.status)}</span></span>
      <span class="console-task-preview">${esc(preview)}</span>
      <small>${esc(sourceName(task.source))} · ${esc(formatTime(task.updated_at))}</small>
    </button>`;
  }).join('');
}

function renderSelectedTask() {
  const detail = $('#task-detail');
  if (!selectedTask) {
    detail.hidden = true;
    return;
  }
  detail.hidden = false;

  $('#task-title').textContent = `${selectedTask.agent} · ${selectedTask.id.slice(0, 8)}`;
  const status = $('#task-status');
  status.textContent = statusLabels[selectedTask.status] || selectedTask.status;
  status.className = `console-status status-${selectedTask.status}`;

  const project = projects.find((item) => item.id === selectedTask.project_id);
  $('#task-meta').innerHTML = [
    `<span><b>Provider:</b> ${esc(sourceName(selectedTask.source))}</span>`,
    `<span><b>Projeto:</b> ${esc(project?.nome || 'Sem projeto')}</span>`,
    `<span><b>Sessão:</b> ${esc(selectedTask.provider_session_id || '—')}</span>`,
    `<span><b>Criada:</b> ${esc(formatTime(selectedTask.created_at))}</span>`,
  ].join('');

  $('#task-timeline').innerHTML = timeline.length
    ? timeline.map((event) => `<li>
        <div><strong>${esc(event.kind)}</strong>${event.source_event ? `<small>${esc(event.source_event)}</small>` : ''}</div>
        ${event.message ? `<p>${esc(event.message)}</p>` : ''}
        <time>${esc(formatTime(event.t))}</time>
      </li>`).join('')
    : '<li class="empty">Sem eventos ainda.</li>';

  $('#task-output').textContent = selectedTask.final_output || (
    selectedTask.status === 'running' ? 'Executando…' :
    selectedTask.status === 'queued' ? 'Aguardando início…' :
    selectedTask.status === 'cancelled' ? 'Task cancelada.' :
    'Aguardando execução…'
  );

  const error = $('#task-error');
  error.hidden = !selectedTask.error;
  error.textContent = selectedTask.error || '';

  $('#cancel-task').hidden = finalStatuses.has(selectedTask.status);
  renderTasks();
}

async function refreshTaskList() {
  const payload = await request('GET', '/tasks?limit=50');
  tasks = payload.tasks;
  renderTasks();
}

async function loadEvents(after = 0) {
  if (!selectedTask) return;
  const payload = await request('GET', `/tasks/${encodeURIComponent(selectedTask.id)}/events?after=${after}`);
  if (after === 0) timeline = [];
  if (payload.events.length) {
    timeline.push(...payload.events);
    cursor = payload.events[payload.events.length - 1].id;
  }
}

async function selectTask(taskId) {
  selectedTask = await request('GET', `/tasks/${encodeURIComponent(taskId)}`);
  cursor = 0;
  await loadEvents(0);
  renderSelectedTask();
  restartPolling();
}

async function pollSelected() {
  if (!selectedTask) return;
  try {
    const [task] = await Promise.all([
      request('GET', `/tasks/${encodeURIComponent(selectedTask.id)}`),
      loadEvents(cursor),
    ]);
    selectedTask = task;
    const index = tasks.findIndex((item) => item.id === task.id);
    if (index >= 0) tasks[index] = task;
    else tasks.unshift(task);
    renderSelectedTask();
    if (finalStatuses.has(task.status)) {
      stopPolling();
      await refreshTaskList();
    }
  } catch (error) {
    showNotice(error.message, true);
    stopPolling();
  }
}

function stopPolling() {
  if (pollHandle) clearInterval(pollHandle);
  pollHandle = null;
}

function restartPolling() {
  stopPolling();
  if (selectedTask && !finalStatuses.has(selectedTask.status)) {
    pollHandle = setInterval(pollSelected, 1000);
  }
}

function resetComposer() {
  selectedTask = null;
  timeline = [];
  cursor = 0;
  stopPolling();
  $('#task-detail').hidden = true;
  $('#task-prompt').value = '';
  $('#task-prompt').focus();
  renderTasks();
}

async function submitTask() {
  const source = $('#task-source').value;
  const agent = $('#task-agent').value;
  const prompt = $('#task-prompt').value.trim();
  const projectValue = $('#task-project').value;

  if (!source) return showNotice('Nenhum provider disponível.', true);
  if (!prompt) return showNotice('Descreva a tarefa antes de executar.', true);

  $('#send-task').disabled = true;
  try {
    const task = await request('POST', '/tasks', {
      source,
      agent,
      prompt,
      project_id: projectValue ? Number(projectValue) : null,
    });
    tasks.unshift(task);
    $('#task-prompt').value = '';
    await selectTask(task.id);
    showNotice('Task criada e enviada ao runner.');
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    $('#send-task').disabled = false;
  }
}

async function cancelSelected() {
  if (!selectedTask) return;
  try {
    selectedTask = await request('POST', `/tasks/${encodeURIComponent(selectedTask.id)}/cancel`);
    renderSelectedTask();
    showNotice('Cancelamento solicitado.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function bootstrap() {
  try {
    const [catalog, projectList, taskPayload] = await Promise.all([
      request('GET', '/task-providers'),
      request('GET', '/projetos'),
      request('GET', '/tasks?limit=50'),
    ]);
    providers = catalog.providers;
    agents = catalog.agents;
    projects = projectList;
    tasks = taskPayload.tasks;
    renderProviderCatalog();
    renderTasks();

    if (tasks.length) await selectTask(tasks[0].id);
  } catch (error) {
    showNotice(error.message, true);
  }
}

$('#send-task').addEventListener('click', submitTask);
$('#cancel-task').addEventListener('click', cancelSelected);
$('#new-task').addEventListener('click', resetComposer);
$('#task-list').addEventListener('click', (event) => {
  const card = event.target.closest('[data-task-id]');
  if (!card) return;
  selectTask(card.dataset.taskId).catch((error) => showNotice(error.message, true));
});
$('#task-prompt').addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault();
    submitTask();
  }
});

bootstrap();
