"""Real browser + isolated API/SQLite + deterministic HTTP mock model."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
SHOTS = HERE / 'p14-screenshots'
SHOTS.mkdir(exist_ok=True)
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    PORT = listener.getsockname()[1]
BASE = f'http://127.0.0.1:{PORT}'
report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'model': 'deterministic HTTP fixture, NOT real AI', 'checks': [], 'pageErrors': []}


def http(path, payload=None):
    request = urllib.request.Request(BASE + path, data=None if payload is None else json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def note(text):
    report['checks'].append(text)
    print('PASS', text, flush=True)


def idle(page):
    expect(page.get_by_role('button', name='停止生成', exact=True)).to_have_count(0, timeout=20000)
    expect(page.locator('.thinking')).to_have_count(0, timeout=20000)


def phase(page, label, status='等待你的回答'):
    expect(page.locator('.teaching-stages .current')).to_have_text(label, timeout=20000)
    expect(page.locator('.teaching-goal [role="status"]')).to_have_text(status, timeout=20000)
    idle(page)


def screenshot(page, name):
    page.screenshot(path=str(SHOTS / name), full_page=True)


def start_server(env, log):
    process = subprocess.Popen([str(ROOT / 'apps/api/.venv/Scripts/python.exe'), '-m', 'uvicorn', 'p14_qa_server:app', '--app-dir', str(HERE), '--host', '127.0.0.1', '--port', str(PORT)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    for attempt in range(100):
        if process.poll() is not None:
            raise RuntimeError('QA server exited; inspect p14-ui-server.log')
        try:
            http('/api/v1/health')
            return process
        except Exception:
            time.sleep(0.1)
    stop_server(process)
    raise TimeoutError('QA server did not start')


def stop_server(process):
    if process.poll() is None:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        process.wait(timeout=10)
        for attempt in range(50):
            with socket.socket() as connection:
                if connection.connect_ex(('127.0.0.1', PORT)) != 0:
                    break
            time.sleep(0.1)
        time.sleep(1)


def main():
    with tempfile.TemporaryDirectory(prefix='mastery-p14-ui-', dir=HERE) as directory, (HERE / 'p14-ui-server.log').open('w', encoding='utf-8') as log:
        env = {key.upper(): value for key, value in os.environ.items()}
        env.update(MASTERY_LAB_QA_P14='1', MASTERY_LAB_DATA_DIR=directory, MASTERY_LAB_DATABASE_URL=f'sqlite:///{Path(directory).as_posix()}/test.db', MASTERY_LAB_PORT=str(PORT), PYTHONIOENCODING='utf-8')
        process = start_server(env, log)
        try:
            info = http('/qa/info')
            course_id, point_id = info['courseId'], info['pointIds'][0]
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                page.goto(f'{BASE}/courses/{course_id}/classroom?point={point_id}', wait_until='networkidle')
                phase(page, '讲解', '本步骤已完成')
                assert page.locator('.turn.user').count() == 0
                note('进入新知识点主动讲解，不要求先写代码')
                screenshot(page, '01-teach-dark.png')
                page.get_by_role('button', name='继续下一步', exact=True).click()
                phase(page, '演示', '本步骤已完成')
                expect(page.locator('.turn.assistant').last.locator('pre code')).to_be_visible()
                page.get_by_role('button', name='继续下一步', exact=True).click()
                phase(page, '理解检查')
                sid = http('/api/v1/classroom/sessions', {'courseId': course_id, 'knowledgePointId': point_id})['data']['id']
                state_path = f'/api/v1/classroom/sessions/{sid}/teaching'
                question = http(state_path)['data']['currentQuestion']
                note('TEACH → DEMO → CHECK，完整代码渲染且一次只有一题')
                page.get_by_role('button', name='暂停学习', exact=True).click()
                phase(page, '理解检查', '已暂停')
                page.reload(wait_until='networkidle')
                phase(page, '理解检查', '已暂停')
                page.get_by_role('button', name='继续学习', exact=True).click()
                phase(page, '理解检查')
                assert http(state_path)['data']['currentQuestion'] == question
                note('待答阶段暂停、刷新、继续保留相同问题')
                composer = page.locator('.composer textarea')
                page.locator('.el-radio-button').filter(has_text='自由提问').click()
                composer.fill('请解释变量名字')
                composer.press('Enter')
                phase(page, '理解检查')
                assert http(state_path)['data']['checkAttempts'] == 0
                page.locator('.el-radio-button').filter(has_text='提交回答').click()
                composer.fill('无效结构')
                composer.press('Enter')
                expect(page.locator('.teaching-error')).to_contain_text('结构无效', timeout=20000)
                idle(page)
                assert http(state_path)['data']['currentQuestion'] == question
                note('自由提问不评价；无效模型 JSON 不推进且保留问题')
                composer.fill('不完整：price 保存数字')
                composer.press('Enter')
                expect(page.locator('.turn.assistant').last).to_contain_text('重新赋值', timeout=20000)
                phase(page, '理解检查')
                assert http(state_path)['data']['currentQuestion'] != question
                note('PARTIAL 补讲后自动针对薄弱点重新检查')
                composer.fill('price 保存价格 12')
                composer.press('Enter')
                phase(page, '共同实践')
                for step in range(2):
                    composer.fill('price = 12，保存价格数值')
                    composer.press('Enter')
                    if step == 0:
                        expect(page.locator('.teaching-next')).to_contain_text('小步骤 2/2', timeout=20000)
                        phase(page, '共同实践')
                    else:
                        phase(page, '独立验证')
                screenshot(page, '02-verify.png')
                note('PAIR 两个小步骤按答题结果推进至独立验证')
                composer.fill('price 保存价格 12')
                composer.press('Enter')
                phase(page, '本节总结', '本步骤已完成')
                state = http(state_path)['data']
                assert state['masteryState'] == 'INDEPENDENT'
                screenshot(page, '03-next-summary.png')
                page.reload(wait_until='networkidle')
                phase(page, '本节总结', '本步骤已完成')
                assert http(state_path)['data']['verificationResult'] == 'PASSED'
                note('VERIFY 通过才完成；刷新恢复总结和证据')
                page.get_by_role('button', name='继续下一知识点', exact=True).click()
                phase(page, '讲解', '本步骤已完成')
                expect(page.locator('.stage-title h1')).to_have_text('条件判断')
                expect(page.locator('.teaching-note')).to_contain_text('历史手工完成')
                note('NEXT 进入下一知识点；旧完成明确标注为手工记录')
                http('/qa/options', {'slow': True})
                page.get_by_role('button', name='再讲一遍', exact=True).click()
                expect(page.get_by_role('button', name='停止生成', exact=True)).to_be_visible()
                page.get_by_role('button', name='暂停学习', exact=True).click()
                phase(page, '讲解', '已暂停')
                page.get_by_role('button', name='继续学习', exact=True).click()
                expect(page.locator('.teaching-goal [role="status"]')).to_have_text('需要重试', timeout=20000)
                page.get_by_role('button', name='开始当前步骤', exact=True).click()
                phase(page, '讲解', '本步骤已完成')
                note('生成中暂停可中止上游，不误记完成，重试后恢复')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.reload(wait_until='networkidle')
                phase(page, '讲解', '本步骤已完成')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                screenshot(page, '04-mobile.png')
                note('390px 窄屏无页面横向溢出')
                page.set_viewport_size({'width': 1440, 'height': 900})
                http('/qa/options', {'slow': True})
                composer.fill('请用更慢的速度解释')
                composer.press('Enter')
                expect(page.get_by_role('button', name='停止生成', exact=True)).to_be_visible()
                second_sid = http('/api/v1/classroom/sessions', {'courseId': course_id, 'knowledgePointId': info['pointIds'][1]})['data']['id']
                for attempt in range(80):
                    saved = http(f'/api/v1/classroom/sessions/{second_sid}')['data']['messages'][-1]
                    if saved['status'] == 'streaming' and len(saved['content']) > 15:
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError('No streaming checkpoint saved')
                checkpoint = saved['content']
                stop_server(process)
                process = start_server(env, log)
                restored = http(f'/api/v1/classroom/sessions/{second_sid}')['data']['messages'][-1]
                assert restored['status'] == 'interrupted' and restored['content'] == checkpoint
                page.reload(wait_until='networkidle')
                phase(page, '讲解', '本步骤已完成')
                expect(page.locator('.turn-flag').last).to_have_text('已停止')
                screenshot(page, '05-restart-recovery.png')
                note('真实终止并重启 API 进程：部分文本及原阶段恢复，无伪完成')
                http('/qa/options', {'fail': True})
                page.get_by_role('button', name='再讲一遍', exact=True).click()
                expect(page.locator('.teaching-error')).to_contain_text('429', timeout=20000)
                idle(page)
                expect(page.locator('.teaching-stages .current')).to_have_text('讲解')
                page.get_by_role('button', name='开始当前步骤', exact=True).click()
                phase(page, '讲解', '本步骤已完成')
                note('模拟上游 429 显示安全错误，不推进且可重试')
                page.goto(f'{BASE}/courses/{course_id}?point={info["pointIds"][1]}', wait_until='networkidle')
                page.get_by_role('button', name='进入教学验证', exact=True).click()
                phase(page, '讲解', '本步骤已完成')
                expect(page.locator('.stage-title h1')).to_have_text('条件判断')
                note('课程详情完成入口进入对应知识点教学，不手工绕过 VERIFY')
                page.evaluate("localStorage.setItem('mastery-lab:theme', 'light')")
                page.reload(wait_until='networkidle')
                phase(page, '讲解', '本步骤已完成')
                assert page.locator('html').get_attribute('data-theme') == 'light'
                screenshot(page, '06-light.png')
                note('浅色主题恢复正常')
                for model in http('/api/v1/models')['data']:
                    response = page.request.delete(f'{BASE}/api/v1/models/{model["id"]}')
                    assert response.ok
                page.reload(wait_until='networkidle')
                expect(page.locator('.model-missing')).to_contain_text('还没有可用的模型配置')
                expect(page.get_by_role('button', name='继续下一步', exact=True)).to_be_disabled()
                expect(page.locator('.turn.assistant').first).to_be_visible()
                note('无模型时禁用生成，历史和阶段仍可读取')
                assert not report['pageErrors'], report['pageErrors']
                browser.close()
            import p12_api_check as regression
            regression.API = BASE + '/api/v1'
            regression.DB = Path(directory) / 'test.db'
            regression.RESULT_PATH = HERE / 'p14-course-regression-result.json'
            regression.main()
            note('P0 配置、P1.1 导入、P1.2 课程 CRUD/进度在隔离服务回归')
            report['passed'] = True
        finally:
            if process.poll() is None:
                stop_server(process)


try:
    main()
except Exception as error:
    report['passed'] = False
    report['error'] = str(error)
    raise
finally:
    (HERE / 'p14-ui-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
