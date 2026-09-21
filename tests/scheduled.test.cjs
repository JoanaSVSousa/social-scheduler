const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadScheduled} = require('../static/scheduled.js');
function element() {
    return {textContent: '', children: [], appendChild(child) {this.children.push(child);},
        replaceChildren() {this.children = [];}};
}
function fixture() {
    const status = element(), results = element();
    const root = {dataset: {endpoint: '/api/scheduled'}, ownerDocument: {createElement: element},
        setAttribute(key, value) {this[key] = value;},
        querySelector(selector) {return selector === '#scheduled-status' ? status : results;}};
    return {root, status, results};
}
const response = (posts) => ({ok: true, json: async () => ({posts})});
test('loading persists while response pending; successful empty only', async () => {
    const {root, status} = fixture();
    let resolve;
    const pending = loadScheduled(root, () => new Promise(r => {resolve = r;}));
    assert.match(status.textContent, /A carregar/);
    assert.equal(root['aria-busy'], 'true');
    resolve(response([]));
    await pending;
    assert.equal(status.textContent, 'Não existem posts agendados');
    assert.equal(root['aria-busy'], 'false');
});
for (const code of [404, 500, 503, 401]) test(`API ${code} is never empty`, async () => {
    const {root, status} = fixture();
    await loadScheduled(root, async () => ({ok: false, status: code}));
    assert.doesNotMatch(status.textContent, /Não existem/);
    assert.match(status.textContent, code === 401 ? /Sessão expirada/ : new RegExp(String(code)));
});
for (const error of [new TypeError('offline'), Object.assign(new Error(), {name: 'AbortError'})]) {
    test(`no response: ${error.name}`, async () => {
        const {root, status} = fixture();
        await loadScheduled(root, async () => {throw error;});
        assert.match(status.textContent, /API sem resposta/);
    });
}
test('malformed payload and login redirects are errors', async () => {
    for (const result of [{ok: true, json: async () => ({})}, {redirected: true}]) {
        const {root, status} = fixture();
        await loadScheduled(root, async () => result);
        assert.doesNotMatch(status.textContent, /Não existem/);
        assert.match(status.textContent, /inválida|Sessão/);
    }
});
test('renders data safely with timezone and distinct statuses', async () => {
    const {root, results, status} = fixture();
    await loadScheduled(root, async () => response([{
        title: '<script>alert(1)</script>', content: 'copy', source_type: 'Regular',
        url: 'javascript:alert(1)', platform: 'Facebook', content_format: 'Feed Post',
        media: [{name: 'photo.png', type: 'image'}], scheduled_at: '2026-09-22T10:00:00+01:00',
        scheduled_label: '22/09/2026 10:00 WEST (UTC+0100)', timezone: 'Europe/Lisbon',
        status: 'Scheduled', post_status: 'Published', error: 'historical error'
    }]));
    assert.match(status.textContent, /1 ocorrência/);
    const children = results.children[0].children;
    assert.equal(children[0].textContent, '<script>alert(1)</script>');
    assert.ok(children.some(child => child.textContent.includes('Europe/Lisbon')));
    assert.ok(children.some(child => child.textContent.includes('Post: Published')));
    assert.ok(children.every(child => !child.href));
});
