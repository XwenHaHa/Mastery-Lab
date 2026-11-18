"""Opt-in: make exactly one small HTTPS request using the saved local model."""
import asyncio
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/api'))
from app.core.security import decrypt_secret
from app.services.llm_client import probe_chat


def run():
    with closing(sqlite3.connect((ROOT/'data/mastery_lab.db').as_uri()+'?mode=ro', uri=True)) as db:
        row = db.execute('select base_url,model_name,api_key_cipher from model_configs order by is_default desc,id limit 1').fetchone()
    if not row:
        return {'ok': False, 'message': 'No saved configuration; skipped.'}
    url, model, cipher = row
    if urlsplit(url).scheme != 'https':
        return {'ok': False, 'message': 'Non-HTTPS configuration; skipped.'}
    probe = asyncio.run(probe_chat(base_url=url, model_name=model, api_key=decrypt_secret(cipher), prompt='请只回复：可用'))
    return {'ok': probe.ok, 'httpStatus': probe.http_status, 'latencyMs': probe.latency_ms,
            'replyChars': len(probe.reply), 'message': probe.message}


if __name__ == '__main__':
    if sys.argv[1:] != ['--confirm-one-request']:
        raise SystemExit('Requires --confirm-one-request (may incur provider charges).')
    result = {'timestamp': datetime.now(timezone.utc).isoformat(), 'kind': 'external-provider-readonly-config', **run()}
    Path(__file__).with_name('p0-real-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False)); sys.exit(0 if result['ok'] else 1)
