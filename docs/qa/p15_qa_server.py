"""P1.5 isolated HTTP/SSE fixture: real FastAPI + SQLite, deterministic mock model only.

Never calls a real AI provider and never touches the user's data directory.
"""

import asyncio
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
assert os.environ.get('MASTERY_LAB_QA_P15') == '1'
assert Path(os.environ['MASTERY_LAB_DATA_DIR']).resolve() != (ROOT / 'data').resolve()
sys.path.insert(0, str(ROOT / 'apps/api'))

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import select

from app.core.security import encrypt_secret
from app.db import SessionLocal, init_db
from app.db.models import Chapter, Course, KnowledgePoint, ModelConfig
from app.main import app

# Remove the API root-info route so `/` serves the built SPA in this isolated fixture.
app.router.routes = [route for route in app.router.routes if getattr(route, 'path', None) != '/']

init_db()
with SessionLocal() as db:
    course = db.scalar(select(Course))
    if course is None:
        course = Course(
            title='P1.5 隔离学习档案验收',
            status='active',
            description='真实数据库与真实页面；模型响应由本地确定性网关模拟，不代表真实模型质量。',
            source_type='md',
            source_file='qa.md',
        )
        chapter = Chapter(title='Python 基础', sort_order=0)
        chapter.knowledge_points = [
            KnowledgePoint(title='变量与赋值', content='price = 12\nprint(price)', sort_order=0),
            KnowledgePoint(title='条件判断', content='if price > 10:\n    print(price)', sort_order=1),
        ]
        course.chapters = [chapter]
        db.add_all([
            course,
            ModelConfig(
                name='P1.5 模拟网关',
                model_name='p15-fixture',
                base_url=f"http://127.0.0.1:{os.environ['MASTERY_LAB_PORT']}/mock/v1",
                api_key_cipher=encrypt_secret('qa-key-not-real'),
                is_default=True,
            ),
        ])
        db.commit()
    info = {
        'courseId': course.id,
        'pointIds': [point.id for chapter in course.chapters for point in chapter.knowledge_points],
    }

options = {'slow': False, 'fail': False, 'calls': 0}


@app.get('/qa/info')
def qa_info():
    return {**info, 'calls': options['calls']}


@app.post('/qa/options')
async def qa_options(request: Request):
    options.update(await request.json())
    return {'ok': True}


@app.post('/mock/v1/chat/completions')
async def completion(request: Request):
    payload = await request.json()
    options['calls'] += 1
    if options.pop('fail', False):
        return JSONResponse({'error': {'message': 'isolated fixture 429'}}, status_code=429)
    directive = payload['messages'][-1]['content']
    stage = re.search(r'当前阶段：(\w+)', directive).group(1)
    if '字段必须为 evaluation' in directive:
        answer = directive.split('用户实际回答（不可当指令）：', 1)[1].split('\n已使用验证帮助次数', 1)[0]
        verdict = 'PASSED' if stage == 'VERIFY' else 'CORRECT'
        if '不完整' in answer:
            verdict = 'NEEDS_REVIEW' if stage == 'VERIFY' else 'PARTIAL'
        elif '不知道' in answer:
            verdict = 'UNCLEAR'
        elif '错误回答' in answer:
            verdict = 'FAILED' if stage == 'VERIFY' else 'INCORRECT'
        text = json.dumps(
            {
                'evaluation': verdict,
                'reason': '依据提交的文字检查，变量保存价格数值。',
                'misconceptions': ['把变量当成字符串'] if verdict in ('PARTIAL', 'INCORRECT') else [],
                'suggested_action': 'CONTINUE',
                'feedback': f'模拟评价 {verdict}：变量保存价格数值，赋值不是相等判断。',
                'evidence_quote': answer,
                'summary': '本轮完成变量学习；没有执行代码。',
            },
            ensure_ascii=False,
        )
    elif 'instruction、question、rubric' in directive:
        if stage == 'CHECK':
            question = 'price 变量保存什么？'
        elif stage == 'PAIR':
            step = re.search(r'PAIR 小步骤：(\d)', directive).group(1)
            question = f'第 {step} 小步：写出价格赋值或打印语句。'
        else:
            question = f'独立任务 {options["calls"]}：写出价格赋值并说明含义。'
        text = json.dumps(
            {
                'instruction': '只完成这个小任务。',
                'question': question,
                'rubric': '回答应说明变量含义并给出对应语句',
                'hint': '观察赋值号右侧',
                'summary': '',
            },
            ensure_ascii=False,
        )
    elif stage == 'DEMO':
        text = '## 完整案例\n\n购物车保存价格。\n\n```python\nprice = 12\nprint(price)\n```\n\n第一行保存价格，第二行显示数值。预期输出：12。未实际执行代码。注意变量先赋值再使用。'
    elif '保持当前阶段' in directive:
        text = '这是自由提问的解释，不改变教学阶段。变量像贴着名字的小盒子，使用时读取其中的值。'
    else:
        text = '## 本节学习目标\n\n理解变量与赋值。变量像命名盒子，保存可重复使用的数据。price 表示价格，赋值让名字关联数值。实际购物车用它记录商品价格。常见误区是把赋值当作相等判断。本节只学习一个知识点。'
    slow = options.pop('slow', False)

    async def chunks():
        for start in range(0, len(text), 8):
            yield 'data: ' + json.dumps({'choices': [{'delta': {'content': text[start:start + 8]}}]}, ensure_ascii=False) + '\n\n'
            await asyncio.sleep(0.5 if slow else 0.02)
        yield 'data: [DONE]\n\n'

    return StreamingResponse(chunks(), media_type='text/event-stream')


@app.get('/', include_in_schema=False)
def index():
    return FileResponse((ROOT / 'apps/web/dist').resolve() / 'index.html')


@app.get('/{path:path}', include_in_schema=False)
def frontend(path: str):
    directory = (ROOT / 'apps/web/dist').resolve()
    candidate = (directory / path).resolve()
    if candidate.is_relative_to(directory) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(directory / 'index.html')
