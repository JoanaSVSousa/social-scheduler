/* Read-only view. Never infer an empty list from a failed request. */
async function loadScheduled(root, fetcher = fetch) {
    const status = root.querySelector('#scheduled-status');
    const results = root.querySelector('#scheduled-results');
    const doc = root.ownerDocument;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    root.setAttribute('aria-busy', 'true');
    status.textContent = 'A carregar agendamentos…';
    results.replaceChildren();
    function text(parent, tag, value) {
        const element = doc.createElement(tag);
        element.textContent = value;
        parent.appendChild(element);
        return element;
    }
    try {
        const response = await fetcher(root.dataset.endpoint, {
            signal: controller.signal, headers: {Accept: 'application/json'}, cache: 'no-store'
        });
        if (response.redirected || response.status === 401) throw new Error('Sessão expirada. Inicie sessão novamente.');
        if (response.status === 404) throw new Error('Rota da API inexistente (404).');
        if (!response.ok) throw new Error(`Erro da API (${response.status}).`);
        const payload = await response.json();
        if (!payload || !Array.isArray(payload.posts)) throw new Error('Resposta inválida da API.');
        if (!payload.posts.length) {
            status.textContent = 'Não existem posts agendados';
            return;
        }
        for (const post of payload.posts) {
            const card = doc.createElement('article');
            card.className = 'panel';
            text(card, 'h2', post.title);
            text(card, 'p', `${post.platform} · ${post.content_format} · Origem: ${post.source_type}`);
            if (post.url) {
                const url = new URL(post.url, 'https://invalid.local');
                if (['https:', 'http:'].includes(url.protocol)) {
                    const link = text(card, 'a', post.url);
                    link.href = url.href;
                    link.rel = 'noopener noreferrer';
                }
            } else text(card, 'p', 'URL de origem não disponível');
            text(card, 'p', post.content);
            const date = text(card, 'time', `${post.scheduled_label} · ${post.timezone}`);
            if (post.scheduled_at) date.dateTime = post.scheduled_at;
            text(card, 'p', `Ocorrência: ${post.status} · Post: ${post.post_status}`);
            text(card, 'p', `Media: ${post.media.map(item => `${item.name} (${item.type})`).join(', ') || 'Sem media'}`);
            if (post.date_error) text(card, 'p', post.date_error);
            text(card, 'p', post.error ? `Último erro registado no post (histórico): ${post.error}` : 'Sem erros registados');
            results.appendChild(card);
        }
        status.textContent = `${payload.posts.length} ocorrência(s) agendada(s)`;
    } catch (error) {
        results.replaceChildren();
        status.textContent = error.name === 'AbortError' || error instanceof TypeError
            ? 'API sem resposta. Não foi possível carregar os agendamentos.'
            : error.message;
    } finally {
        clearTimeout(timeout);
        root.setAttribute('aria-busy', 'false');
    }
}
if (typeof document !== 'undefined') {
    const root = document.querySelector('#scheduled-view');
    if (root) loadScheduled(root);
}
if (typeof module !== 'undefined') module.exports = {loadScheduled};
