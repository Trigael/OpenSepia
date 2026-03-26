// Board Server — Web UI

const API = '/api';
let schema = {};
let currentAgent = 'human';

// ----- Init -----

async function init() {
    schema = await api('GET', '/schema');
    const agents = await api('GET', '/agents');

    // Populate agent selectors
    const selects = ['agent-select', 'inbox-agent'];
    for (const id of selects) {
        const el = document.getElementById(id);
        if (!el) continue;
        el.innerHTML = '';
        for (const a of agents) {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = `${a.name} (${a.id})`;
            el.appendChild(opt);
        }
    }

    // Set default to human
    const agentSel = document.getElementById('agent-select');
    agentSel.value = 'human';
    agentSel.addEventListener('change', () => { currentAgent = agentSel.value; });

    // Populate type filter
    const typeFilter = document.getElementById('filter-type');
    for (const type of Object.keys(schema)) {
        const opt = document.createElement('option');
        opt.value = type;
        opt.textContent = type;
        typeFilter.appendChild(opt);
    }

    // Populate status filter
    const statusFilter = document.getElementById('filter-status');
    const statuses = new Set();
    for (const type of Object.values(schema)) {
        const sf = type.fields?.status;
        if (sf?.values) sf.values.forEach(v => statuses.add(v));
    }
    for (const s of statuses) {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        statusFilter.appendChild(opt);
    }

    // Tab navigation
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`view-${tab.dataset.view}`).classList.add('active');

            if (tab.dataset.view === 'board') loadBoard();
            else if (tab.dataset.view === 'items') loadItems();
            else if (tab.dataset.view === 'inbox') loadInbox();
            else if (tab.dataset.view === 'events') loadEvents();
        });
    });

    loadBoard();
}

// ----- API helper -----

async function api(method, path, body) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json', 'X-Agent-Id': currentAgent },
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(API + path, opts);
    return resp.json();
}

// ----- Board (Kanban) -----

const STATUS_ORDER = ['todo', 'in_progress', 'review', 'testing', 'done', 'blocked'];
const STATUS_LABELS = {
    todo: 'To Do', in_progress: 'In Progress', review: 'Review',
    testing: 'Testing', done: 'Done', blocked: 'Blocked'
};

async function loadBoard() {
    const board = await api('GET', '/board');
    const kanban = document.getElementById('kanban');
    kanban.innerHTML = '';

    for (const status of STATUS_ORDER) {
        const items = board[status] || [];
        const col = document.createElement('div');
        col.className = 'kanban-column';
        col.innerHTML = `
            <h3>${STATUS_LABELS[status] || status}
                <span class="count">${items.length}</span>
            </h3>
        `;
        for (const item of items) {
            col.appendChild(renderCard(item));
        }
        kanban.appendChild(col);
    }
}

function renderCard(item) {
    const card = document.createElement('div');
    card.className = 'card';
    card.onclick = () => showItem(item.id);
    const priority = item.priority || item.severity || '';
    card.innerHTML = `
        <div class="card-id">${item.id}</div>
        <div class="card-title">${esc(item.title || '')}</div>
        <div class="card-meta">
            ${priority ? `<span class="priority-${priority}">${priority}</span>` : ''}
            ${item.assigned ? `<span>${item.assigned}</span>` : ''}
        </div>
    `;
    return card;
}

// ----- Items list -----

async function loadItems() {
    let path = '/items?';
    const type = document.getElementById('filter-type').value;
    const status = document.getElementById('filter-status').value;
    if (type) path += `type=${type}&`;
    if (status) path += `status=${status}&`;

    const items = await api('GET', path);
    const list = document.getElementById('items-list');
    list.innerHTML = '';

    for (const item of items) {
        const row = document.createElement('div');
        row.className = 'item-row';
        row.onclick = () => showItem(item.id);
        const statusClass = `status-${(item.status || '').replace(' ', '_')}`;
        row.innerHTML = `
            <span class="item-id">${item.id}</span>
            <span class="item-title">${esc(item.title || '')}</span>
            <span class="item-status ${statusClass}">${item.status || ''}</span>
            <span style="font-size:12px;color:#999">${item.assigned || ''}</span>
        `;
        list.appendChild(row);
    }
}

// ----- Item detail -----

async function showItem(itemId) {
    const item = await api('GET', `/items/${itemId}`);
    if (item.error) return;

    const typeDef = schema[item.type] || {};
    const fields = typeDef.fields || {};
    const modal = document.getElementById('modal');
    const body = document.getElementById('modal-body');

    let fieldsHtml = '';
    for (const [fname, fdef] of Object.entries(fields)) {
        const val = item[fname] ?? '';
        let input;
        if (fdef.type === 'enum' && fdef.values) {
            const opts = fdef.values.map(v =>
                `<option value="${v}" ${v === val ? 'selected' : ''}>${v}</option>`
            ).join('');
            input = `<select onchange="updateField('${itemId}','${fname}',this.value)">${opts}</select>`;
        } else if (fdef.type === 'text') {
            input = `<span class="value">${esc(String(val))}</span>`;
        } else {
            input = `<input value="${esc(String(val))}" onchange="updateField('${itemId}','${fname}',this.value)" />`;
        }
        fieldsHtml += `<div class="detail-field"><label>${fname}</label>${input}</div>`;
    }

    const commentsHtml = (item.comments || []).map(c => `
        <div class="comment">
            <span class="comment-author">${esc(c.author)}</span>
            <span class="comment-time">${formatTime(c.created_at)}</span>
            <div class="comment-body">${esc(c.body)}</div>
        </div>
    `).join('');

    body.innerHTML = `
        <div class="detail-header">
            <span class="detail-id">${item.id} (${item.type})</span>
            <h2>${esc(item.title || '')}</h2>
        </div>
        <div class="detail-fields">${fieldsHtml}</div>
        <div class="comments">
            <h3>Comments</h3>
            ${commentsHtml || '<p style="color:#999">No comments yet</p>'}
            <div class="comment-form">
                <textarea id="comment-text" placeholder="Add a comment..."></textarea>
                <button onclick="addComment('${itemId}')">Post</button>
            </div>
        </div>
    `;
    modal.classList.add('open');
}

async function updateField(itemId, field, value) {
    await api('PATCH', `/items/${itemId}`, { [field]: value });
    loadBoard();
}

async function addComment(itemId) {
    const text = document.getElementById('comment-text').value.trim();
    if (!text) return;
    await api('POST', `/items/${itemId}/comments`, { body: text });
    showItem(itemId);
}

function closeModal() {
    document.getElementById('modal').classList.remove('open');
}

// ----- Create item -----

function showCreateForm() {
    const fieldsDiv = document.getElementById('create-fields');
    const types = Object.keys(schema);
    let html = `<label>Type</label><select name="type" id="create-type" onchange="renderCreateFields()">`;
    for (const t of types) html += `<option value="${t}">${t}</option>`;
    html += `</select><div id="create-type-fields"></div>`;
    fieldsDiv.innerHTML = html;
    renderCreateFields();
    document.getElementById('create-modal').classList.add('open');
}

function renderCreateFields() {
    const type = document.getElementById('create-type').value;
    const fields = schema[type]?.fields || {};
    const div = document.getElementById('create-type-fields');
    let html = '';
    for (const [fname, fdef] of Object.entries(fields)) {
        html += `<label>${fname}${fdef.required ? ' *' : ''}</label>`;
        if (fdef.type === 'enum' && fdef.values) {
            html += `<select name="${fname}">`;
            for (const v of fdef.values) html += `<option value="${v}" ${v === fdef.default ? 'selected' : ''}>${v}</option>`;
            html += `</select>`;
        } else if (fdef.type === 'text') {
            html += `<textarea name="${fname}"></textarea>`;
        } else {
            const val = fdef.default ?? '';
            html += `<input name="${fname}" value="${val}" />`;
        }
    }
    div.innerHTML = html;
}

async function createItem(e) {
    e.preventDefault();
    const form = document.getElementById('create-form');
    const data = {};
    for (const el of form.elements) {
        if (el.name && el.value) {
            data[el.name] = el.value;
        }
    }
    const result = await api('POST', '/items', data);
    if (!result.error) {
        closeCreateModal();
        loadBoard();
        loadItems();
    }
}

function closeCreateModal() {
    document.getElementById('create-modal').classList.remove('open');
}

// ----- Inbox -----

async function loadInbox() {
    const agent = document.getElementById('inbox-agent').value;
    const messages = await api('GET', `/inbox/${agent}`);
    const list = document.getElementById('inbox-messages');
    list.innerHTML = '';
    if (messages.length === 0) {
        list.innerHTML = '<p style="color:#999;padding:20px">No unread messages</p>';
        return;
    }
    for (const msg of messages) {
        const el = document.createElement('div');
        el.className = 'inbox-msg';
        el.innerHTML = `
            <span class="msg-from">${esc(msg.from_agent || 'system')}</span>
            <span class="msg-time">${formatTime(msg.created_at)}</span>
            <div class="msg-body">${esc(msg.message)}</div>
        `;
        list.appendChild(el);
    }
}

async function markInboxRead() {
    const agent = document.getElementById('inbox-agent').value;
    await api('DELETE', `/inbox/${agent}`);
    loadInbox();
}

async function sendInboxMessage() {
    const to = document.getElementById('inbox-to').value.trim();
    const msg = document.getElementById('inbox-msg').value.trim();
    if (!to || !msg) return;
    await api('POST', `/inbox/${to}`, { message: msg });
    document.getElementById('inbox-msg').value = '';
    loadInbox();
}

// ----- Events -----

async function loadEvents() {
    const events = await api('GET', '/events?limit=50');
    const list = document.getElementById('events-list');
    list.innerHTML = '';
    for (const ev of events.reverse()) {
        const row = document.createElement('div');
        row.className = 'event-row';
        row.innerHTML = `
            <span class="event-type">${ev.event_type}</span>
            <span class="event-time">${formatTime(ev.created_at)}</span>
            <span>${ev.agent_id || ''}</span>
        `;
        list.appendChild(row);
    }
}

// ----- Utils -----

function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function formatTime(iso) {
    if (!iso) return '';
    return iso.replace('T', ' ').substring(0, 19);
}

// ----- Start -----
init();
