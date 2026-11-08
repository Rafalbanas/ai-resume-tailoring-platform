"""Read-only history presentation: time, batch membership and actual downloads.

Availability describes files, never a human approval or a hiring recommendation.
Legacy timestamps retain their provenance instead of rewriting saved records.
"""
import json
import re
from datetime import datetime, timezone

STATUSES = {
    'completed': 'Files available — review before sending',
    'partial_files': 'Only one export format available',
    'no_files': 'No export files available',
    'report_ready': 'Report ready — CV not generated',
    'draft_ready': 'Draft ready — CV not generated',
    'review_required': 'Review required before export',
    'failed': 'Generation failed',
    'queued': 'Queued',
    'running': 'In progress',
    'rejected': 'Rejected — history kept',
    'cancelled': 'Cancelled — saved results kept',
    'manual_required': 'Manual input required',
}


def read_object(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def timestamp(value):
    """Only offset-aware times are exact; a date alone must not invent midnight."""
    if not isinstance(value, str) or 'T' not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except ValueError:
        return None


def prepare_history(storage, rows, analyses):
    """Enrich copies of account-local records without touching files or providers."""
    rows, analyses = [dict(row) for row in rows], [dict(row) for row in analyses]
    by_slug, by_draft, by_task, batches = {}, {}, {}, {}
    for path in (storage.data_dir / 'tasks').glob('*.json'):
        if not re.fullmatch(r'[a-f0-9]{32}', path.stem):
            continue
        task = read_object(path)
        if task.get('kind') != 'batch' or task.get('task_id') != path.stem:
            continue
        created = timestamp(task.get('created_at'))
        batch_id = path.stem
        batches[batch_id] = {
            'id': batch_id,
            'label': f"{created.strftime('%Y-%m-%d %H:%M UTC') if created else 'Unknown date'} · {batch_id[:8]}",
            'created_at': created.isoformat() if created else '',
        }
        result = task.get('result')
        items = result.get('items', []) if isinstance(result, dict) else []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field, index in [('slug', by_slug), ('draft_id', by_draft), ('task_id', by_task)]:
                value = item.get(field)
                if isinstance(value, str) and value:
                    index.setdefault(value, []).append((batch_id, item.get('status')))

    used_batches = set()
    for generated, entries in [(True, rows), (False, analyses)]:
        for row in entries:
            draft_id = row.get('draft_id')
            if not isinstance(draft_id, str):
                draft_id = None
            draft = (read_object(storage.drafts_dir / f'{draft_id}.json')
                     if isinstance(draft_id, str) and re.fullmatch(r'[a-f0-9]{32}', draft_id) else {})
            associations = by_slug.get(row.get('slug'), []) or by_draft.get(draft_id, [])
            if not associations and not generated:
                match = re.fullmatch(r'/tasks/([a-f0-9]{32})/view', row.get('view_url', ''))
                associations = by_task.get(match[1], []) if match else []
            row['batch_ids'] = sorted({batch_id for batch_id, _ in associations})
            row['batch_labels'] = [batches[batch_id]['label'] for batch_id in row['batch_ids']]
            used_batches.update(row['batch_ids'])
            finished = timestamp(row.get('generation_completed_at')) if generated else None
            row['generation_finished_label'] = finished.strftime('%Y-%m-%d %H:%M:%S UTC') if finished else ''
            moment = (finished or timestamp(row.get('created_at'))) if generated else timestamp(row.get('date'))
            source = ('Generation finished' if finished else 'Generation started') if generated else 'Analysis created'
            if moment is None and generated:
                moment = timestamp(draft.get('created_at'))
                source = 'Draft time (legacy)'
            if moment is None and generated:
                slug = row.get('slug', '')
                # Use only known filenames in an already validated storage folder.
                try:
                    folder = storage.application_folder(slug)
                    moment = datetime.fromtimestamp((folder / 'resume.generated.json').stat().st_mtime, timezone.utc)
                    source = 'File time (legacy estimate)'
                except (OSError, ValueError):
                    pass
            row['history_timestamp'] = moment.isoformat() if moment else ''
            row['history_time_label'] = moment.strftime('%Y-%m-%d %H:%M:%S UTC') if moment else row.get('date', '')
            row['history_time_source'] = source if moment else 'Date only — time unknown'
            if generated:
                try:
                    folder = storage.application_folder(row['slug'])
                except (OSError, ValueError):
                    folder = None
                for kind in ('pdf', 'docx'):
                    artifact = folder / f'resume.{kind}' if folder else None
                    try:
                        row[f'has_{kind}'] = bool(artifact and artifact.is_file() and artifact.stat().st_size > 0)
                    except OSError:
                        row[f'has_{kind}'] = False
                count = sum(bool(row.get(f'has_{kind}')) for kind in ('pdf', 'docx'))
                status = {2: 'completed', 1: 'partial_files', 0: 'no_files'}[count]
            else:
                status = row.get('status', 'report_ready')
                if status == 'report_ready' and associations:
                    candidate = associations[-1][1]
                    if candidate in {'review_required', 'draft_ready', 'failed', 'manual_required'}:
                        status = candidate
                response = draft.get('response')
                analysis = response.get('analysis', {}) if isinstance(response, dict) else {}
                if isinstance(analysis, dict):
                    row['match_level'] = analysis.get('match_level', '')
                    row['recommendation'] = analysis.get('recommendation', '')
            row['history_status'] = status
            row['history_status_label'] = STATUSES.get(status, 'Review required')

    def order(row):
        return (row['history_timestamp'] or row.get('date', ''), row.get('slug', row.get('view_url', '')))

    return (sorted(rows, key=order, reverse=True), sorted(analyses, key=order, reverse=True),
            sorted((batches[key] for key in used_batches), key=lambda batch: batch['created_at'], reverse=True))
