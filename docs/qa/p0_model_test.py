"""Offline P0 credential and probe contracts; no user database or gateway access."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/api'))
from app.core.response import ValidationError
from app.core.security import mask_secret
from app.core import security
from app.db.models import ModelConfig
from app.schemas.model_config import ModelConfigCreate
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.schemas.model_config import ModelConfigUpdate, ModelTestRequest
from app.services import model_registry as registry, llm_client


class Contracts(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.get.return_value = Mock(base_url='https://old.invalid/v1', model_name='old',
                                        last_test_ok=True, last_test_message='previous', is_default=False)

    def test_change_endpoint_requires_fresh_key_before_save(self):
        with self.assertRaises(ValidationError):
            registry.update_config(self.db, 1, ModelConfigUpdate(base_url='https://new.invalid/v1'))
        self.db.commit.assert_not_called()

    def test_change_endpoint_requires_fresh_key_before_probe(self):
        with patch.object(registry, 'decrypt_secret') as decrypt, patch.object(registry, 'probe_chat', new_callable=AsyncMock), self.assertRaises(ValidationError):
            asyncio.run(registry.test_config(self.db, ModelTestRequest(id=1, base_url='https://new.invalid/v1')))
        decrypt.assert_not_called()

    def test_only_saved_settings_get_probe_history(self):
        with patch.object(registry, 'probe_chat', new_callable=AsyncMock, return_value=llm_client.ChatProbeResult(True, 'ok')):
            asyncio.run(registry.test_config(self.db, ModelTestRequest(id=1, api_key='temporary', model_name='preview')))
        self.db.commit.assert_not_called()

    def test_model_name_change_invalidates_probe(self):
        with patch.object(registry, 'to_out'):
            registry.update_config(self.db, 1, ModelConfigUpdate(model_name='new'))
        self.assertIsNone(self.db.get.return_value.last_test_ok)

    def test_hint_contains_no_secret_characters(self):
        for key in ('abcd', 'long-test-key'):
            self.assertEqual(mask_secret(key), '****')

    def test_only_nonblank_text_counts_as_reply(self):
        for content in (None, {}, '   '):
            self.assertEqual(llm_client._extract_reply({'choices': [{'message': {'content': content}}]}), '')

    def test_windows_encryption_failure_does_not_downgrade(self):
        with patch.object(security, '_dpapi_available', return_value=True), patch.object(security, '_dpapi_crypt', side_effect=security.SecretError('DPAPI unavailable')), patch.object(security, '_load_fernet') as fallback:
            with self.assertRaises(security.SecretError):
                security.encrypt_secret('test-only')
            fallback.assert_not_called()

    def test_switch_default_between_two_configurations(self):
        engine = create_engine('sqlite://')
        ModelConfig.__table__.create(engine)
        with Session(engine) as session, patch.object(registry, 'encrypt_secret', return_value='dpapi:v1:fixture'):
            for name in ['first', 'second']:
                registry.create_config(session, ModelConfigCreate(name=name, base_url='https://model.invalid', model_name=name, api_key='test-only'))
            first, second = registry.list_configs(session)
            self.assertTrue(first.is_default); self.assertFalse(second.is_default)
            registry.update_config(session, second.id, ModelConfigUpdate(is_default=True))
            self.assertEqual([row.is_default for row in registry.list_configs(session)], [False, True])
            registry.delete_config(session, second.id)
            self.assertTrue(registry.list_configs(session)[0].is_default)
        engine.dispose()


if __name__ == '__main__':
    unittest.main(verbosity=2)
