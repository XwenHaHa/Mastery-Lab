"""Run against the documented isolated P0 instance only (local mock gateway)."""
import json
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data/qa-p0-20261118'
BASE = 'http://127.0.0.1:15173'
KEY = secrets.token_hex(30)
NAME = 'P0 QA ' + secrets.token_hex(4)
steps, gateway_calls, errors = [], [], []


class Gateway(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        ok = (self.path == '/v1/chat/completions' and self.headers.get('Authorization') == 'Bearer ' + KEY
              and body.get('model') == 'qa-local')
        gateway_calls.append(ok)
        self.send_response(200 if ok else 400)
        self.send_header('Content-Type', 'application/json'); self.end_headers()
        self.wfile.write(b'{"choices":[{"message":{"content":"QA reply"}}]}')

    def log_message(self, *args):
        pass


def run():
    health = json.load(urlopen(BASE + '/api/v1/health'))['data']
    assert Path(health['paths']['dataDir']).resolve() == DATA and health['database']['ok']
    assert urlopen('http://127.0.0.1:18080/docs').status == 200
    steps.append('Vite proxy / health / isolated SQLite / Swagger')
    with ThreadingHTTPServer(('127.0.0.1', 0), Gateway) as gateway, sync_playwright() as playwright:
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        page.goto(BASE, wait_until='networkidle')
        expect(page.get_by_role('heading', level=2, name='概览', exact=True)).to_be_visible()
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        page.screenshot(path=str(HERE / 'p0-dashboard.png'))
        page.get_by_role('link', name='设置').click(); page.get_by_role('button', name='浅色', exact=True).click()
        page.reload(); expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        steps.append('Dashboard / default dark / settings / light theme survives reload')
        page.get_by_role('link', name='模型配置').first.click()
        page.get_by_role('button', name='新建配置').first.click()
        dialog = page.get_by_role('dialog')
        fields = dialog.locator('input:not([type=checkbox])')
        for index, value in enumerate([NAME, f'http://127.0.0.1:{gateway.server_port}/v1', 'qa-local', KEY]):
            fields.nth(index).fill(value)
        dialog.get_by_role('button', name='测试连接').click(); expect(dialog.get_by_text('模型回复：QA reply')).to_be_visible()
        with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/models')) as saved:
            dialog.get_by_role('button', name='保存').click()
        assert saved.value.status == 201 and KEY not in saved.value.text()
        result = saved.value.json()['data']; assert result['apiKeyHint'] == '****'
        with closing(sqlite3.connect((DATA/'mastery_lab.db').as_uri() + '?mode=ro', uri=True)) as db:
            cipher, hint = db.execute('select api_key_cipher,api_key_hint from model_configs where id=?', (result['id'],)).fetchone()
            assert cipher.startswith('dpapi:v1:') and KEY not in cipher and hint == '****'
        page.reload(); row = page.get_by_role('row').filter(has_text=NAME); expect(row).to_be_visible()
        with page.expect_response(lambda response: response.url.endswith('/models/test')) as tested:
            row.get_by_role('button', name='测试', exact=True).click()
        assert tested.value.json()['data']['ok'] and gateway_calls == [True, True]
        steps.append('Browser create / encrypted SQLite / reload / draft and saved probes via local HTTP gateway')
        row.get_by_role('button', name='编辑').click()
        expect(fields.nth(3)).to_have_value(''); fields.nth(0).fill(NAME + ' edited')
        dialog.get_by_role('button', name='保存').click()
        expect(page.get_by_text(NAME + ' edited', exact=True)).to_be_visible()
        assert KEY not in page.evaluate('JSON.stringify([localStorage, sessionStorage])')
        row.get_by_role('button', name='删除').click()
        page.get_by_role('button', name='删除', exact=True).last.click()
        expect(row).to_have_count(0); page.reload(); expect(row).to_have_count(0)
        assert KEY not in json.dumps(json.load(urlopen(BASE + '/api/v1/models')))
        assert not any(KEY.encode() in file.read_bytes() for file in (DATA/'run').glob('*.log'))
        with closing(sqlite3.connect((DATA/'mastery_lab.db').as_uri() + '?mode=ro', uri=True)) as db:
            assert db.execute('select count(*) from model_configs where id=?', (result['id'],)).fetchone()[0] == 0
            assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        assert not errors
        steps.append('Edit without key / delete / SQLite quick_check / storage and logs / zero page errors')
        browser.close(); gateway.shutdown()


if __name__ == '__main__':
    passed = False
    try:
        run(); passed = True
    finally:
        report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'passed': passed, 'steps': steps,
                  'gateway': 'local mock, not external AI', 'pageErrors': errors}
        (HERE/'p0-browser-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
