"""Isolated P1.4 tests; never use the user's database or model credentials."""

import json
import unittest
from uuid import uuid4
from unittest.mock import patch

import p13_backend_test as baseline
from fastapi.testclient import TestClient


class TeachingTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        baseline.engine.dispose()

    def setUp(self):
        baseline.Base.metadata.drop_all(baseline.engine)
        baseline.Base.metadata.create_all(baseline.engine)
        self.course_id, self.point_id, self.model_id = baseline.seed()
        self.client = TestClient(baseline.app)
        self.sid = self.client.post('/api/v1/classroom/sessions', json={
            'courseId': self.course_id, 'knowledgePointId': self.point_id,
        }).json()['data']['id']
        self.path = f'/api/v1/classroom/sessions/{self.sid}/teaching'

    def state(self):
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def action(self, action, content='', output=None, request_id=None, revision=None):
        current = self.state()
        payload = {'requestId': request_id or str(uuid4()), 'expectedRevision': current['revision'] if revision is None else revision, 'action': action, 'content': content}
        async def fake_stream(**kwargs):
            yield output or '当前知识点的完整讲解。\n\n```python\nprice = 12\nprint(price)\n```\n预期输出：12。'
        with patch('app.api.v1.teaching.stream_chat', fake_stream):
            return self.client.post(self.path + '/actions', json=payload)

    def task(self, question='请说明变量 price 表示什么？'):
        return json.dumps({'instruction': '围绕刚才的案例回答一个小问题。', 'question': question, 'rubric': '指出变量保存价格数值', 'hint': '观察赋值号右侧', 'summary': ''}, ensure_ascii=False)

    def evaluation(self, verdict='CORRECT', answer='price 保存价格 12'):
        return json.dumps({'evaluation': verdict, 'reason': '依据实际回答判断', 'misconceptions': [], 'suggested_action': 'CONTINUE', 'feedback': '你指出了变量保存价格数值。', 'evidence_quote': answer, 'summary': '变量保存可复用的数值。'}, ensure_ascii=False)

    def reach_check(self):
        self.assertEqual(self.action('START').status_code, 200)
        self.assertEqual(self.action('CONTINUE').status_code, 200)
        self.assertEqual(self.action('CONTINUE', output=self.task()).status_code, 200)
        self.assertEqual(self.state()['currentStage'], 'CHECK')

    def test_new_session_teach_and_guarded_continue(self):
        state = self.state()
        self.assertEqual((state['currentStage'], state['stageStatus']), ('TEACH', 'PENDING'))
        self.assertEqual(self.action('CONTINUE').status_code, 409)
        self.assertEqual(self.action('ANSWER', '我懂了').status_code, 409)

    def test_no_manual_completion_or_legacy_alias_bypass(self):
        for path in [f'/api/v1/courses/{self.course_id}/knowledge-points/{self.point_id}/status', f'/api/v1/knowledge-points/{self.point_id}/status']:
            for status in ['completed', 'mastered']:
                response = self.client.patch(path, json={'status': status})
                self.assertEqual(response.status_code, 409, response.text)

    def test_correct_check_advances_only_to_pair_pending(self):
        self.reach_check()
        response = self.action('ANSWER', 'price 保存价格 12', self.evaluation())
        self.assertEqual(response.status_code, 200)
        state = self.state()
        self.assertEqual((state['currentStage'], state['stageStatus']), ('PAIR', 'PENDING'))
        self.assertEqual(state['checkAttempts'], 1)

    def test_partial_and_unclear_cannot_advance(self):
        self.reach_check()
        response = self.action('ANSWER', 'price 保存价格 12', self.evaluation('PARTIAL'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state()['currentStage'], 'CHECK')
        self.assertEqual(self.state()['stageStatus'], 'PENDING')
        self.assertIsNone(self.state()['currentQuestion'])
        self.action('START', output=self.task('price 重新赋值后保存哪个数值？'))
        question = self.state()['currentQuestion']
        self.action('ANSWER', 'price 保存价格 12', self.evaluation('UNCLEAR'))
        self.assertEqual(self.state()['currentQuestion'], question)
        self.assertEqual(self.state()['stageStatus'], 'WAITING_USER')
        self.assertEqual(self.state()['checkAttempts'], 2)

    def test_incorrect_goes_back_to_teach(self):
        self.reach_check()
        self.action('ANSWER', 'price 保存价格 12', self.evaluation('INCORRECT'))
        state = self.state()
        self.assertEqual(state['currentStage'], 'TEACH')
        self.assertEqual(state['backtrackCount'], 1)

    def test_invalid_evaluation_does_not_advance_or_erase_question(self):
        self.reach_check()
        question = self.state()['currentQuestion']
        response = self.action('ANSWER', 'price 保存价格 12', '{"evaluation":"CORRECT","current_stage":"NEXT"}')
        self.assertIn('event: error', response.text)
        self.assertEqual(self.state()['currentStage'], 'CHECK')
        self.assertEqual(self.state()['currentQuestion'], question)

    def test_duplicate_request_does_not_call_model_twice(self):
        state = self.state()
        request_id = str(uuid4())
        self.action('START', request_id=request_id, revision=state['revision'])
        before = self.state()
        with patch('app.api.v1.teaching.stream_chat', side_effect=AssertionError('duplicate model call')):
            response = self.client.post(self.path + '/actions', json={'requestId': request_id, 'expectedRevision': state['revision'], 'action': 'START'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state()['revision'], before['revision'])

    def test_pause_resume_preserves_stage_and_blocks_generation(self):
        self.reach_check()
        before = self.state()
        paused = self.client.post(self.path + '/control', json={'requestId': str(uuid4()), 'expectedRevision': before['revision'], 'action': 'PAUSE'})
        self.assertEqual(paused.status_code, 200)
        self.assertTrue(self.state()['paused'])
        self.assertEqual(self.action('ANSWER', 'test').status_code, 409)
        resumed = self.client.post(self.path + '/control', json={'requestId': str(uuid4()), 'expectedRevision': self.state()['revision'], 'action': 'RESUME'})
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(self.state()['currentQuestion'], before['currentQuestion'])
        self.assertFalse(self.state()['paused'])

    def reach_verify(self):
        self.reach_check()
        self.action('ANSWER', 'price 保存价格 12', self.evaluation())
        for question in ['请把价格赋值给 price？', '请用 print 显示价格？']:
            self.action('START', output=self.task(question))
            self.action('ANSWER', 'price 保存价格 12', self.evaluation())
        self.assertEqual(self.state()['currentStage'], 'VERIFY')
        self.action('START', output=self.task('如果价格变成 18，你会如何修改并解释这段程序？'))

    def test_complete_flow_with_independent_evidence_and_last_point(self):
        self.reach_verify()
        self.action('ANSWER', 'price 保存价格 12', self.evaluation('PASSED'))
        state = self.state()
        self.assertEqual(state['currentStage'], 'NEXT')
        self.assertEqual(state['masteryState'], 'INDEPENDENT')
        self.assertEqual(state['pairAttempts'], 2)
        detail = self.client.get(f'/api/v1/courses/{self.course_id}').json()['data']
        self.assertEqual(detail['progress'], 100)
        result = self.client.post(self.path + '/control', json={'requestId': str(uuid4()), 'expectedRevision': state['revision'], 'action': 'NEXT'})
        self.assertTrue(result.json()['data']['courseComplete'])
        self.assertIsNone(result.json()['data']['nextKnowledgePointId'])
        events = self.client.get(self.path + '/events').json()['data']
        self.assertEqual(len(events['evaluations']), 4)

    def test_helped_pass_is_not_independent(self):
        self.reach_verify()
        self.action('GIVE_HINT', output='先观察赋值号右侧。')
        self.action('ANSWER', 'price 保存价格 12', self.evaluation('PASSED'))
        self.assertEqual(self.state()['masteryState'], 'GUIDED_PRACTICE')
        self.assertEqual(self.state()['verifyHintCount'], 1)

    def test_verify_failure_cannot_next(self):
        self.reach_verify()
        self.action('ANSWER', 'price 保存价格 12', self.evaluation('FAILED'))
        state = self.state()
        self.assertEqual(state['currentStage'], 'PAIR')
        self.assertEqual(state['verificationResult'], 'FAILED')
        response = self.client.post(self.path + '/control', json={'requestId': str(uuid4()), 'expectedRevision': state['revision'], 'action': 'NEXT'})
        self.assertEqual(response.status_code, 409)

    def test_generic_confirmation_and_fake_quote_cannot_pass(self):
        self.reach_check()
        self.action('ANSWER', '我懂了', self.evaluation(answer='我懂了'))
        self.assertEqual(self.state()['currentStage'], 'CHECK')
        self.action('ANSWER', '不知道', self.evaluation())
        self.assertEqual(self.state()['currentStage'], 'CHECK')

    def test_old_regenerate_cannot_delete_teaching_evidence(self):
        self.reach_check()
        before = self.client.get(f'/api/v1/classroom/sessions/{self.sid}').json()['data']['messages']
        response = self.client.post(f'/api/v1/classroom/sessions/{self.sid}/regenerate')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get(f'/api/v1/classroom/sessions/{self.sid}').json()['data']['messages'], before)

    def test_restart_recovery_retains_checkpoint(self):
        from app.services.teaching_state import TeachingStateMachine
        from app.schemas.teaching import TeachingAction
        self.reach_check()
        before = self.state()
        with baseline.SessionLocal() as db:
            machine = TeachingStateMachine(db)
            operation = machine.begin(self.sid, TeachingAction(requestId=str(uuid4()), expectedRevision=before['revision'], action='ASK', content='请解释术语'), 'test')
            message = db.get(baseline.ChatMessage, operation.assistant_message_id)
            message.content = '崩溃前已保存的片段'
            db.commit()
        with baseline.SessionLocal() as db:
            TeachingStateMachine(db).recover()
        state = self.state()
        self.assertEqual(state['currentQuestion'], before['currentQuestion'])
        self.assertEqual(state['stageStatus'], 'WAITING_USER')
        messages = self.client.get(f'/api/v1/classroom/sessions/{self.sid}').json()['data']['messages']
        self.assertEqual(messages[-1]['content'], '崩溃前已保存的片段')
        self.assertEqual(messages[-1]['status'], 'interrupted')

    def test_stale_revision_rejected_without_user_message(self):
        state = self.state()
        self.action('START')
        response = self.action('ASK', '为什么', revision=state['revision'])
        self.assertEqual(response.status_code, 409)
        messages = self.client.get(f'/api/v1/classroom/sessions/{self.sid}').json()['data']['messages']
        self.assertEqual(len(messages), 1)

    def test_no_extra_stage_parameter(self):
        state = self.state()
        response = self.client.post(self.path + '/actions', json={'requestId': str(uuid4()), 'expectedRevision': state['revision'], 'action': 'START', 'currentStage': 'NEXT'})
        self.assertEqual(response.status_code, 422)

    def test_wrong_evaluation_does_not_commit_completed_assistant(self):
        self.reach_check()
        self.action('ANSWER', 'price 保存价格 12', self.evaluation('PASSED'))
        state = self.state()
        self.assertEqual(state['currentStage'], 'CHECK')
        self.assertEqual(state['stageStatus'], 'WAITING_USER')
        messages = self.client.get(f'/api/v1/classroom/sessions/{self.sid}').json()['data']['messages']
        self.assertEqual(messages[-1]['status'], 'failed')

    def test_preparation_failure_releases_operation_and_allows_retry(self):
        state = self.state()
        client = TestClient(baseline.app, raise_server_exceptions=False)
        with patch('app.api.v1.teaching.teaching_protocol.build_messages', side_effect=RuntimeError('private failure detail')):
            response = client.post(self.path + '/actions', json={'requestId': str(uuid4()), 'expectedRevision': state['revision'], 'action': 'START'})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private failure detail', response.text)
        self.assertFalse(baseline.stream_registry.is_active(self.sid))
        self.assertEqual(self.state()['stageStatus'], 'BLOCKED')
        self.assertIn('START', self.state()['allowedActions'])
        self.action('START')
        self.assertEqual(self.state()['stageStatus'], 'COMPLETED')

    def test_finish_commit_failure_rolls_back_verification_and_completion(self):
        from sqlalchemy.orm import Session
        from app.db.models import TeachingEvaluation
        self.reach_verify()
        original_commit = Session.commit
        def fail_evaluation_commit(db):
            if any(isinstance(item, TeachingEvaluation) for item in db.new):
                raise RuntimeError('injected commit failure')
            return original_commit(db)
        with patch.object(Session, 'commit', fail_evaluation_commit):
            response = self.action('ANSWER', 'price 保存价格 12', self.evaluation('PASSED'))
        self.assertIn('event: error', response.text)
        self.assertEqual(self.state()['currentStage'], 'VERIFY')
        self.assertEqual(self.state()['stageStatus'], 'WAITING_USER')
        self.assertIsNone(self.state()['verificationResult'])
        course = self.client.get(f'/api/v1/courses/{self.course_id}').json()['data']
        self.assertNotEqual(course['chapters'][0]['knowledgePoints'][0]['learningStatus'], 'completed')
        self.assertEqual(len(self.client.get(self.path + '/events').json()['data']['evaluations']), 3)

    def test_pause_invalidates_active_verification_and_preserves_question(self):
        from app.services.teaching_state import TeachingStateMachine
        from app.schemas.teaching import TeachingAction, TeachingJudgment
        self.reach_verify()
        before = self.state()
        with baseline.SessionLocal() as db:
            operation = TeachingStateMachine(db).begin(self.sid, TeachingAction(requestId=str(uuid4()), expectedRevision=before['revision'], action='ANSWER', content='price 保存价格 12'), 'test')
            operation_id = operation.id
        state = self.state()
        payload = {'requestId': str(uuid4()), 'expectedRevision': state['revision'], 'action': 'PAUSE'}
        self.assertEqual(self.client.post(self.path + '/control', json=payload).status_code, 200)
        self.assertEqual(self.client.post(self.path + '/control', json=payload).status_code, 200)
        with baseline.SessionLocal() as db:
            machine = TeachingStateMachine(db)
            with self.assertRaises(baseline.ConflictError):
                machine.finish(operation_id, '不能提交', TeachingJudgment.model_validate_json(self.evaluation('PASSED')))
            machine.fail(operation_id, '暂停', interrupted=True)
        state = self.state()
        self.assertEqual(state['currentStage'], 'VERIFY')
        self.assertEqual(state['currentQuestion'], before['currentQuestion'])
        self.assertEqual(state['allowedActions'], ['RESUME'])

    def test_backtrack_downgrades_current_mastery_without_erasing_evidence(self):
        self.reach_verify()
        self.action('EXPLAIN_AGAIN')
        state = self.state()
        self.assertEqual(state['currentStage'], 'TEACH')
        self.assertEqual(state['masteryState'], 'INTRODUCED')
        self.assertEqual(len(self.client.get(self.path + '/events').json()['data']['evaluations']), 3)

    def test_events_link_evaluation_to_question_and_actual_answer(self):
        self.reach_check()
        self.action('ANSWER', 'price 保存价格 12', self.evaluation())
        evidence = self.client.get(self.path + '/events').json()['data']['evaluations'][0]
        self.assertIsInstance(evidence['questionMessageId'], int)
        self.assertIsInstance(evidence['userMessageId'], int)
        self.assertIsInstance(evidence['assistantMessageId'], int)
        self.assertEqual(evidence['answer'], 'price 保存价格 12')
        self.assertIn('price', evidence['question'])

    def test_task_rejects_multiple_questions_and_repeated_verification(self):
        self.action('START')
        self.action('CONTINUE')
        response = self.action('CONTINUE', output=self.task('变量是什么？赋值是什么？'))
        self.assertIn('event: error', response.text)
        self.assertEqual(self.state()['stageStatus'], 'BLOCKED')
        self.action('START', output=self.task())
        self.action('ANSWER', 'price 保存价格 12', self.evaluation())
        for step in range(2):
            self.action('START', output=self.task(f'共同完成第 {step + 1} 步'))
            self.action('ANSWER', 'price 保存价格 12', self.evaluation())
        response = self.action('START', output=self.task())
        self.assertIn('event: error', response.text)
        self.assertEqual(self.state()['currentStage'], 'VERIFY')
        self.assertEqual(self.state()['stageStatus'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
