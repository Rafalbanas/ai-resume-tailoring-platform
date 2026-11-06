"""Read-only, account-local history times and file availability."""
import json

from app.services.history_view import prepare_history, timestamp
from app.services.storage import Storage


def seed(storage, slug, *, created_at=None, draft_id=None, pdf=True, docx=True):
    folder = storage.generated_dir / slug
    folder.mkdir()
    metadata = {'company': slug, 'role': 'Synthetic role', 'date': '2026-11-06',
                'match_level': 'MEDIUM', 'recommendation': 'REVIEW', 'draft_id': draft_id}
    if created_at:
        metadata['created_at'] = created_at
    (folder / 'metadata.json').write_text(json.dumps(metadata))
    if pdf:
        (folder / 'resume.pdf').write_bytes(b'synthetic pdf')
    if docx:
        (folder / 'resume.docx').write_bytes(b'synthetic docx')
    return folder


def test_history_orders_full_times_not_company_or_slug(tmp_path):
    storage = Storage(tmp_path)
    seed(storage, 'z-old', created_at='2026-11-06T08:30:00+00:00')
    seed(storage, 'a-new', created_at='2026-11-06T12:30:00+00:00')
    rows, _, _ = prepare_history(storage, storage.history(), [])
    assert [row['slug'] for row in rows] == ['a-new', 'z-old']
    assert rows[0]['history_time_label'] == '2026-11-06 12:30:00 UTC'


def test_finish_time_is_after_export_and_not_replaced_by_later_edits(tmp_path):
    storage = Storage(tmp_path)
    folder = seed(storage, 'synthetic', created_at='2026-11-06T08:30:00+00:00')
    path = folder / 'metadata.json'
    metadata = json.loads(path.read_text())
    metadata['document_status'] = 'pending_export'
    path.write_text(json.dumps(metadata))
    storage.mark_export_checked('synthetic')
    first = json.loads(path.read_text())
    assert timestamp(first['generation_completed_at'])
    storage.mark_export_checked('synthetic')
    second = json.loads(path.read_text())
    assert second['generation_completed_at'] == first['generation_completed_at']
    assert timestamp(second['last_export_completed_at']) >= timestamp(first['last_export_completed_at'])
    rows, _, _ = prepare_history(storage, storage.history(), [])
    assert rows[0]['history_timestamp'] == first['generation_completed_at']


def test_legacy_draft_time_is_labelled_and_does_not_rewrite_saved_data(tmp_path):
    storage = Storage(tmp_path)
    draft_id = 'a' * 32
    folder = seed(storage, 'legacy', draft_id=draft_id)
    (storage.drafts_dir / f'{draft_id}.json').write_text(json.dumps({'created_at': '2026-11-06T12:00:00Z'}))
    path = folder / 'metadata.json'
    before = path.read_bytes()
    rows, _, _ = prepare_history(storage, storage.history(), [])
    assert rows[0]['history_time_source'] == 'Draft time (legacy)'
    assert not rows[0]['generation_finished_label']
    assert path.read_bytes() == before


def test_missing_and_empty_files_do_not_get_downloadable_badges(tmp_path):
    storage = Storage(tmp_path)
    folder = seed(storage, 'one-file', pdf=True, docx=False)
    (folder / 'resume.docx').write_bytes(b'')
    rows, _, _ = prepare_history(storage, storage.history(), [])
    assert rows[0]['has_pdf'] and not rows[0]['has_docx']
    assert rows[0]['history_status'] == 'partial_files'


def test_batch_membership_joins_ids_not_shared_urls_or_company_names(tmp_path):
    storage = Storage(tmp_path)
    draft_id, batch_id = 'a' * 32, 'b' * 32
    seed(storage, 'one', draft_id=draft_id)
    seed(storage, 'two', draft_id='c' * 32)
    tasks = tmp_path / 'tasks'
    tasks.mkdir()
    (tasks / f'{batch_id}.json').write_text(json.dumps({'task_id': batch_id, 'kind': 'batch',
        'created_at': '2026-11-06T12:30:00Z', 'result': {'items': [{'draft_id': draft_id, 'status': 'completed'}]}}))
    rows, _, batches = prepare_history(storage, storage.history(), [])
    assert next(row for row in rows if row['slug'] == 'one')['batch_ids'] == [batch_id]
    assert next(row for row in rows if row['slug'] == 'two')['batch_ids'] == []
    assert [batch['id'] for batch in batches] == [batch_id]


def test_draft_status_and_recommendation_are_visible_without_an_export(tmp_path):
    storage = Storage(tmp_path)
    draft_id, batch_id = 'a' * 32, 'b' * 32
    (storage.drafts_dir / f'{draft_id}.json').write_text(json.dumps({'response': {
        'analysis': {'match_level': 'LOW', 'recommendation': 'REVIEW'}}}))
    tasks = tmp_path / 'tasks'
    tasks.mkdir()
    (tasks / f'{batch_id}.json').write_text(json.dumps({'task_id': batch_id, 'kind': 'batch', 'result': {
        'items': [{'draft_id': draft_id, 'status': 'review_required'}]}}))
    _, rows, _ = prepare_history(storage, [], [{'draft_id': draft_id, 'company': 'Synthetic', 'role': 'Role',
        'date': '2026-11-06T12:00:00Z', 'status': 'report_ready'}])
    assert rows[0]['history_status'] == 'review_required'
    assert rows[0]['recommendation'] == 'REVIEW'
    assert rows[0]['match_level'] == 'LOW'


def test_corrupt_batches_and_unknown_times_do_not_hide_valid_history(tmp_path):
    storage = Storage(tmp_path)
    seed(storage, 'legacy')
    tasks = tmp_path / 'tasks'
    tasks.mkdir()
    (tasks / ('a' * 32 + '.json')).write_text('{invalid')
    rows, _, batches = prepare_history(storage, storage.history(), [])
    assert len(rows) == 1 and batches == []
    assert rows[0]['history_timestamp'] == ''
    assert rows[0]['history_time_source'] == 'Date only — time unknown'
    assert timestamp('2026-11-06') is None
    assert timestamp('2026-11-06T12:00:00') is None
