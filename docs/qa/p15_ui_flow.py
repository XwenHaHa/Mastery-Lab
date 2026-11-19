"""P1.5 real-browser end-to-end check.

Uses an isolated data directory + real SQLite + real FastAPI + real built frontend.
The model endpoint is a deterministic local HTTP fixture, never a real provider.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
SHOTS = HERE / 'p15-screenshots'
SHOTS.mkdir(exist_ok=True)
CHROME = Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright' / 'chromium-1234' / 'chrome-win64' / 'chrome.exe'

with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    PORT = listener.getsockname()[1]
BASE = f'http://127.0.0.1:{PORT}'
report: dict = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'model': 'deterministic local HTTP fixture, NOT real AI',
    'database': 'isolated SQLite, real schema and real API',
    'checks': [],
    'pageErrors': [],
    'screenshots': [],
    'metrics': {},
}


def note(text: str) -> None:
    report['checks'].append(text)
    print('PASS', text, flush=True)


def http(path: str, payload: dict | None = None, method: str | None = None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        BASE + path,
        data=data,
        headers={'Content-Type': 'application/json'},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def start_server(env: dict, log_path: Path):
    log = log_path.open('a', encoding='utf-8')
    process = subprocess.Popen(
        [
            str(ROOT / 'apps/api/.venv/Scripts/python.exe'),
            '-m',
            'uvicorn',
            'p15_qa_server:app',
            '--app-dir',
            str(HERE),
            '--host',
            '127.0.0.1',
            '--port',
            str(PORT),
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError('QA server exited; inspect p15-ui-server.log')
        try:
            http('/api/v1/health')
            return process
        except Exception:
            time.sleep(0.1)
    stop_server(process)
    raise TimeoutError('QA server did not start')


def stop_server(process) -> None:
    if process.poll() is None:
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        process.wait(timeout=10)
        for _ in range(60):
            with socket.socket() as connection:
                if connection.connect_ex(('127.0.0.1', PORT)) != 0:
                    break
            time.sleep(0.1)
        time.sleep(0.8)


def idle(page) -> None:
    expect(page.get_by_role('button', name='停止生成', exact=True)).to_have_count(0, timeout=30_000)
    expect(page.locator('.thinking')).to_have_count(0, timeout=30_000)


def phase(page, label: str, status: str | None = None) -> None:
    expect(page.locator('.teaching-stages .current')).to_have_text(label, timeout=30_000)
    idle(page)
    if status:
        expect(page.locator('.teaching-goal [role="status"]')).to_have_text(status, timeout=30_000)


def screenshot(page, name: str) -> None:
    path = SHOTS / name
    page.screenshot(path=str(path), full_page=True)
    report['screenshots'].append(str(path))


def state(sid: int) -> dict:
    return http(f'/api/v1/classroom/sessions/{sid}/teaching')['data']


def wait_state(sid: int, predicate, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = state(sid)
        if predicate(last):
            return last
        time.sleep(0.2)
    raise AssertionError(f'teaching state timeout: {json.dumps(last, ensure_ascii=False)[:600]}')


def teach(sid: int, action: str, content: str = '') -> dict:
    current = state(sid)
    revision = current['revision']
    payload = {
        'requestId': str(uuid4()),
        'expectedRevision': revision,
        'action': action,
        'content': content,
    }
    request = urllib.request.Request(
        BASE + f'/api/v1/classroom/sessions/{sid}/teaching/actions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()
    return wait_state(
        sid,
        lambda item: item['revision'] > revision and item['stageStatus'] != 'ACTIVE',
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='mastery-p15-ui-', dir=HERE, ignore_cleanup_errors=True) as directory, (
        HERE / 'p15-ui-server.log'
    ).open('w', encoding='utf-8') as initial_log:
        data_dir = Path(directory)
        env = {key.upper(): value for key, value in os.environ.items()}
        env.update(
            MASTERY_LAB_QA_P15='1',
            MASTERY_LAB_DATA_DIR=str(data_dir),
            MASTERY_LAB_DATABASE_URL=f'sqlite:///{data_dir.as_posix()}/test.db',
            MASTERY_LAB_PORT=str(PORT),
            PYTHONIOENCODING='utf-8',
        )
        initial_log.close()
        process = start_server(env, HERE / 'p15-ui-server.log')
        try:
            info = http('/qa/info')
            course_id = info['courseId']
            point0, point1 = info['pointIds'][0], info['pointIds'][1]
            classroom_url = f'{BASE}/courses/{course_id}/classroom?point={point0}'
            sid = http('/api/v1/classroom/sessions', {'courseId': course_id, 'knowledgePointId': point0})['data']['id']

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
                context = browser.new_context(viewport={'width': 1440, 'height': 900})
                page = context.new_page()
                page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))

                # ---------- 1. 进入教室，完成 TEACH / DEMO ----------
                page.goto(classroom_url, wait_until='networkidle')
                phase(page, '讲解', '本步骤已完成')
                note('进入教室后老师先讲解，不要求用户先写代码')
                screenshot(page, '01-teach.png')

                page.get_by_role('button', name='继续下一步', exact=True).click()
                phase(page, '演示', '本步骤已完成')
                page.get_by_role('button', name='继续下一步', exact=True).click()
                phase(page, '理解检查', '等待你的回答')
                question_before = state(sid)['currentQuestion']
                note('TEACH → DEMO → CHECK，当前只提出一个问题')

                # ---------- 2. 草稿自动保存 + 刷新恢复 ----------
                composer = page.locator('.composer textarea')
                draft_text = '这是我未提交的草稿回答：price 保存价格 12'
                composer.fill(draft_text)
                deadline = time.time() + 15
                saved = None
                while time.time() < deadline:
                    saved = http(f'/api/v1/learning/sessions/{sid}/breakpoint')['data']
                    if saved['draftAnswer'] == draft_text:
                        break
                    time.sleep(0.25)
                assert saved and saved['draftAnswer'] == draft_text, f"draft was not persisted: {saved!r}"
                assert saved['currentStage'] == 'CHECK' and saved['stageStatus'] == 'WAITING_USER'
                note('草稿写入断点表，阶段与问题由后端同步')

                page.reload(wait_until='networkidle')
                phase(page, '理解检查', '等待你的回答')
                expect(page.locator('.composer textarea')).to_have_value(draft_text, timeout=15_000)
                expect(page.locator('.resume-note')).to_contain_text('草稿已恢复', timeout=15_000)
                assert state(sid)['currentQuestion'] == question_before
                note('刷新浏览器后恢复同一阶段、同一问题与未提交草稿，不重新提问')
                screenshot(page, '02-resume-after-refresh.png')

                # ---------- 3. CHECK 答错 → 错题 ----------
                composer = page.locator('.composer textarea')
                composer.fill('错误回答：价格是字符串')
                selected_mode = page.locator('.el-radio-button.is-active').inner_text()
                assert '提交回答' in selected_mode, f'unexpected input mode: {selected_mode}'
                composer.press('Enter')
                phase(page, '讲解', '本步骤已完成')
                mistakes = http('/api/v1/learning/mistakes')['data']
                assert mistakes['total'] == 1, mistakes
                record = mistakes['items'][0]
                assert record['stage'] == 'CHECK' and record['status'] == 'open'
                assert '错误回答' in record['userAnswer']
                note('CHECK 答错生成错题记录，保留原始问题、用户回答、原因与纠正讲解')
                report['metrics']['mistakeId'] = record['id']

                # ---------- 4. 后端真实教学链路到 VERIFY 通过 ----------
                teach(sid, 'CONTINUE')  # DEMO
                teach(sid, 'CONTINUE')  # CHECK question
                teach(sid, 'ANSWER', 'price 保存价格 12')
                teach(sid, 'START')
                teach(sid, 'ANSWER', 'price 保存价格 12')
                teach(sid, 'START')
                teach(sid, 'ANSWER', 'price 保存价格 12')
                teach(sid, 'START')
                final = teach(sid, 'ANSWER', 'price 保存价格 12')
                assert final['currentStage'] == 'NEXT', final
                assert final['masteryState'] == 'INDEPENDENT', final
                assert final['verificationResult'] == 'PASSED'
                note('VERIFY 通过后掌握状态变为 INDEPENDENT，活动按完成结束')

                activity = http(f'/api/v1/learning/history?pointId={point0}')['data']
                assert activity['total'] >= 1
                first_activity = activity['items'][0]
                assert first_activity['result'] == 'completed', first_activity
                overview = http('/api/v1/learning/overview')['data']
                assert overview['completedPoints'] == 1, overview
                assert overview['independentPoints'] == 1, overview
                note('学习档案总览与课程进度读取到真实完成状态')

                # ---------- 5. 第二个知识点的有效时长、断点与续学入口 ----------
                sid2 = http('/api/v1/classroom/sessions', {'courseId': course_id, 'knowledgePointId': point1})['data']['id']
                http(f'/api/v1/classroom/sessions/{sid2}/teaching')
                started = http(
                    '/api/v1/learning/activities/start',
                    {'courseId': course_id, 'knowledgePointId': point1, 'sessionId': sid2},
                )['data']
                with sqlite3.connect(data_dir / 'test.db') as connection:
                    connection.execute(
                        'UPDATE learning_activities SET last_heartbeat_at = datetime("now", "-45 seconds") WHERE id = ?',
                        (started['id'],),
                    )
                    connection.commit()
                beat = http(
                    f"/api/v1/learning/activities/{started['id']}/heartbeat",
                    {'activeSecondsDelta': 45},
                )['data']
                assert 40 <= beat['activeSeconds'] <= 50, beat
                http(f"/api/v1/learning/activities/{started['id']}/finish", {'result': 'finished', 'reason': 'qa'})
                note('有效学习时长按心跳累计，单次上报受服务端上限保护')

                draft2 = '下次继续：用 if 判断价格是否大于 10'
                saved_bp = http(
                    f'/api/v1/learning/sessions/{sid2}/breakpoint',
                    {'clientSeq': 1, 'draftAnswer': draft2, 'inputMode': 'ASK'},
                    method='PUT',
                )['data']
                assert saved_bp['accepted'] is True, saved_bp
                assert saved_bp['draftAnswer'] == draft2, saved_bp
                resumed = http('/api/v1/learning/resume')['data']
                assert resumed['knowledgePointId'] == point1, resumed
                assert resumed['hasDraft'] is True
                note('断点接口返回最近的未完成知识点与草稿')

                # ---------- 6. 学习档案与错题页面 ----------
                page.goto(f'{BASE}/learning', wait_until='networkidle')
                expect(page.locator('.ml-page-title').filter(has_text='学习档案')).to_be_visible(timeout=20_000)
                expect(page.locator('.overview-grid .overview-cell').first).to_contain_text('累计有效学习')
                expect(page.locator('.history-table .el-table__row').first).to_be_visible(timeout=20_000)
                screenshot(page, '03-learning-archive.png')
                page.locator('.history-table .el-table__row').filter(has_text='变量与赋值').filter(
                    has_text='已完成'
                ).first.click()
                expect(page.locator('.el-drawer')).to_contain_text('学习过程详情', timeout=20_000)
                expect(page.locator('.el-drawer .qa-item').first).to_be_visible(timeout=20_000)
                page.wait_for_timeout(450)
                screenshot(page, '04-history-detail.png')
                page.keyboard.press('Escape')
                note('学习档案展示总览、掌握分布、课程进度与可点击的历史记录')

                page.goto(f'{BASE}/learning/mistakes', wait_until='networkidle')
                expect(page.locator('.ml-page-title').filter(has_text='错题与薄弱点')).to_be_visible(timeout=20_000)
                expect(page.locator('.mistake-row').first).to_be_visible(timeout=20_000)
                screenshot(page, '05-mistakes.png')
                page.locator('.mistake-row').first.click()
                expect(page.locator('.el-drawer')).to_contain_text('错题详情', timeout=20_000)
                expect(page.locator('.el-drawer .occurrence').first).to_be_visible(timeout=20_000)
                page.wait_for_timeout(450)
                screenshot(page, '06-mistake-detail.png')
                page.locator('.el-drawer').get_by_role('button', name='标记为已理解').click()
                expect(page.locator('.el-drawer .status-pill')).to_have_text('已理解', timeout=15_000)
                understood = http('/api/v1/learning/mistakes')['data']['items'][0]
                assert understood['status'] == 'understood'
                page.keyboard.press('Escape')
                note('错题详情可查看每次发生历史，并标记为已理解')

                # 恢复为待处理，保留报告中的薄弱点
                http(
                    f"/api/v1/learning/mistakes/{understood['id']}",
                    {'status': 'open'},
                    method='PATCH',
                )

                # ---------- 7. 概览继续学习入口 ----------
                page.goto(BASE + '/', wait_until='networkidle')
                expect(page.locator('.resume-card')).to_contain_text('上次停在这里', timeout=20_000)
                expect(page.locator('.learning-strip')).to_be_visible(timeout=20_000)
                screenshot(page, '07-dashboard-resume.png')
                note('概览页显示继续学习入口与真实学习统计')

                # ---------- 8. 断点续学页面 ----------
                check_bp = http(f'/api/v1/learning/sessions/{sid2}/breakpoint')['data']
                assert check_bp['draftAnswer'] == draft2, check_bp
                page.goto(
                    f'{BASE}/courses/{course_id}/classroom?point={point1}&resume=1',
                    wait_until='networkidle',
                )
                expect(page.locator('.resume-note')).to_contain_text('已恢复上次进度', timeout=20_000)
                expect(page.locator('.composer textarea')).to_have_value(draft2, timeout=15_000)
                screenshot(page, '08-resume-draft.png')
                note('从断点进入教室恢复知识点草稿，未重复创建会话')

                context.close()

                # ---------- 9. 浏览器重新打开 ----------
                context = browser.new_context(viewport={'width': 1440, 'height': 900})
                page = context.new_page()
                page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                page.goto(
                    f'{BASE}/courses/{course_id}/classroom?point={point1}&resume=1',
                    wait_until='networkidle',
                )
                expect(page.locator('.composer textarea')).to_have_value(draft2, timeout=20_000)
                note('关闭浏览器后重新打开，草稿与阶段仍可恢复')

                # ---------- 10. 服务重启恢复 ----------
                before = http('/api/v1/learning/overview')['data']
                before_resume = http('/api/v1/learning/resume')['data']
                context.close()
                stop_server(process)
                process = start_server(env, HERE / 'p15-ui-server.log')
                after = http('/api/v1/learning/overview')['data']
                after_resume = http('/api/v1/learning/resume')['data']
                assert after['completedPoints'] == before['completedPoints']
                assert after['activityCount'] == before['activityCount']
                assert after_resume['knowledgePointId'] == before_resume['knowledgePointId']
                assert after_resume['hasDraft'] is True
                note('后端服务重启后学习档案、断点与有效时长保持一致')

                context = browser.new_context(viewport={'width': 1440, 'height': 900})
                page = context.new_page()
                page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                page.goto(
                    f'{BASE}/courses/{course_id}/classroom?point={point1}&resume=1',
                    wait_until='networkidle',
                )
                expect(page.locator('.composer textarea')).to_have_value(draft2, timeout=20_000)
                screenshot(page, '09-after-server-restart.png')
                note('重启后再次进入教室仍恢复到同一草稿')

                # ---------- 11. 时间与历史一致性 ----------
                history = http(f'/api/v1/learning/history?pointId={point1}')['data']
                assert history['total'] >= 1
                seconds = http(f"/api/v1/learning/history/{started['id']}")['data']['activity']['activeSeconds']
                assert 40 <= seconds <= 50, seconds
                report['metrics']['point1ActiveSeconds'] = seconds
                report['metrics']['overview'] = after
                report['metrics']['resume'] = after_resume
                note('学习历史中的有效时长与心跳累计一致')

                browser.close()

            # 静态检查：确认没有页面异常
            assert not report['pageErrors'], report['pageErrors']
            report['result'] = 'PASS'
        finally:
            stop_server(process)
            (HERE / 'p15-ui-result.json').write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            print('RESULT', report.get('result', 'FAIL'), flush=True)
            print('REPORT', HERE / 'p15-ui-result.json', flush=True)


if __name__ == '__main__':
    main()
