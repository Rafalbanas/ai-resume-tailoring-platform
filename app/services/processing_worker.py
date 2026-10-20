"""Disposable Linux worker. Its production pod has no account mounts or AI secrets."""
import json
import resource
import sys
from pathlib import Path


def main():
    work = Path(sys.argv[1])
    request = json.loads((work / 'input.json').read_text())
    if request['operation'] != 'browser':
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    resource.setrlimit(resource.RLIMIT_FSIZE, (12 * 1024 * 1024, 12 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        result = dispatch(request['operation'], request['payload'], work)
        response = {'ok': True, 'result': result}
    except Exception:
        # Parser exceptions can contain candidate content, paths or native details.
        response = {'ok': False, 'error': 'Document is invalid or exceeds processing limits.'}
    (work / 'output.json').write_text(json.dumps(response), encoding='utf-8')


def dispatch(operation, payload, work):
    from app.services.processing import decoded, encoded
    if operation != 'browser':
        from app.services.processing_security import restrict_network
        restrict_network()
    if operation == 'check':
        import socket
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except PermissionError:
            return {'protocol': 1, 'network_blocked': True}
        raise RuntimeError('Network sandbox is not enforced')
    if operation != 'browser':
        from pypdf import apply_configuration
        apply_configuration(zlib_maximum_output_length=8_000_000, lzw_maximum_output_length=8_000_000,
                            run_length_maximum_output_length=8_000_000, array_based_stream_maximum_output_length=8_000_000,
                            stream_decoding_work_maximum_length=16_000_000, maximum_declared_stream_length=10_000_000)
    if operation == 'browser':
        import asyncio

        from app.services.job_extractors.playwright_renderer import SafePlaywrightRenderer
        from app.services.job_extractors.security import PublicUrlGuard
        renderer = SafePlaywrightRenderer(PublicUrlGuard(), payload['timeout'], payload['max_bytes'], payload['max_redirects'], isolated=False)
        page = asyncio.run(renderer.render(payload['url']))
        return {'url': page.url, 'html': page.html}
    if operation == 'reference':
        from app.services.reference_cvs import ReferenceCVLibrary
        if payload['suffix'] not in {'.pdf', '.docx'}:
            raise ValueError('Unsupported reference type')
        path = work / ('reference' + payload['suffix'])
        path.write_bytes(decoded(payload['content']))
        return ReferenceCVLibrary._extract_text_local(path)
    if operation == 'photo':
        from app.services.profile_photo import ProfilePhotoStore
        store = ProfilePhotoStore(work / 'photo')
        store._save_local(payload['filename'], payload['mime'], decoded(payload['content']),
                          payload['crop_x'], payload['crop_y'], payload['crop_zoom'])
        return {'webp': encoded(store.webp_path.read_bytes()), 'jpg': encoded(store.jpg_path.read_bytes())}
    if operation in {'pdf', 'preview', 'metrics', 'docx'}:
        from app.models.candidate import CandidateProfile
        from app.models.resume import TailoredResume
        from app.services.pdf_generator import PDFGenerator
        from app.services.profile_photo import ProfilePhotoStore
        root = Path(__file__).resolve().parents[2]
        photo = ProfilePhotoStore(work / 'photo')
        if payload.get('photo'):
            photo.directory.mkdir()
            photo.jpg_path.write_bytes(decoded(payload['photo']))
        generator = PDFGenerator(root / 'templates', root / 'static', work, photo, isolated=False)
        resume = TailoredResume.model_validate(payload['resume'])
        profile = CandidateProfile.model_validate(payload['profile'])
        guide = payload.get('guide') or {}
        options = payload.get('options') or {}
        if operation == 'preview':
            return generator.render_preview(resume, profile, guide, **options)
        if operation == 'metrics':
            return generator._layout_metrics(resume, profile, guide)
        if operation == 'docx':
            from app.services.docx_generator import _generate_docx_local
            path = work / 'resume.docx'
            _generate_docx_local(resume, profile, path, photo_path=photo.path, **options)
        else:
            path = work / 'resume.pdf'
            generator.generate(resume, profile, path, guide, **options)
        return encoded(path.read_bytes())
    raise ValueError('Unknown processing operation')


if __name__ == '__main__':
    main()
