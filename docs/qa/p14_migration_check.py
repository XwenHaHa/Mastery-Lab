"""Upgrade a read-only snapshot, never migrate the live database here."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
SOURCE = ROOT / 'data/mastery_lab.db'
report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'checks': []}


def snapshot(connection, columns):
    result = {}
    for table, names in columns.items():
        projection = ','.join(f'"{name}"' for name in names)
        rows = connection.execute(f'SELECT {projection} FROM "{table}" ORDER BY rowid').fetchall()
        result[table] = {'count': len(rows), 'sha256': hashlib.sha256(repr(rows).encode()).hexdigest()}
    return result


with tempfile.TemporaryDirectory(prefix='mastery-p14-migration-', dir=HERE) as directory:
    target = Path(directory) / 'migration.db'
    with closing(sqlite3.connect(SOURCE.resolve().as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as destination:
        source.backup(destination)
    with closing(sqlite3.connect(target)) as connection:
        report['sourceSchema'] = connection.execute("SELECT value FROM app_settings WHERE key='schema_version'").fetchone()[0]
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'") if row[0] != 'app_settings' and not row[0].startswith('sqlite_')]
        columns = {table: [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')] for table in tables}
        before = snapshot(connection, columns)
        legacy_ids = [row[0] for row in connection.execute("SELECT id FROM knowledge_points WHERE learning_status IN ('completed', 'mastered')")]
    env = {key.upper(): value for key, value in os.environ.items()}
    env.update(MASTERY_LAB_DATA_DIR=directory, MASTERY_LAB_DATABASE_URL=f'sqlite:///{target.as_posix()}', PYTHONIOENCODING='utf-8')
    command = [str(ROOT / 'apps/api/.venv/Scripts/python.exe'), '-c', 'from app.db import init_db,engine; from app.main import _record_schema_version; init_db(); _record_schema_version(); engine.dispose()']
    for iteration in range(2):
        result = subprocess.run(command, cwd=ROOT / 'apps/api', env=env, capture_output=True)
        (HERE / f'p14-migration-{iteration + 1}.log').write_bytes(result.stdout + result.stderr)
        assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
        with closing(sqlite3.connect(target)) as connection:
            assert snapshot(connection, columns) == before
            assert connection.execute("SELECT value FROM app_settings WHERE key='schema_version'").fetchone()[0] == '5'
            assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not connection.execute('PRAGMA foreign_key_check').fetchall()
            actual = {row[0]: row[1] for row in connection.execute('SELECT id, completion_source FROM knowledge_points')}
            assert all(actual[point_id] == 'legacy_manual' for point_id in legacy_ids)
            assert connection.execute('SELECT count(*) FROM teaching_progress').fetchone()[0] == 0
        report['checks'].append(f'升级第 {iteration + 1} 次：原表原列逐行摘要一致、旧完成来源标记、schema 5、完整性及外键正常')
    report['preserved'] = {table: value['count'] for table, value in before.items()}
    report['legacyCompletedCount'] = len(legacy_ids)
    report['passed'] = True
(HERE / 'p14-migration-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
