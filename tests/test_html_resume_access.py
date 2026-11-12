"""End-point specific access tests for HTML and ZIP downloads."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from tests.test_shared_login import runtimes, shared_app, sign_in  # noqa: F401


@pytest.mark.parametrize('account', ['owner', 'demo'])
def test_html_resume_access(shared_app, account, synthetic_download):  # noqa: F811
    with TestClient(shared_app) as client:
        owner, demo = runtimes(shared_app)
        source = owner if account == 'owner' else demo
        other_account = 'demo' if account == 'owner' else 'owner'

        slug = 'synthetic_test_slug'
        content = b'%PDF synthetic'

        # Seed in the primary account
        synthetic_download(source, slug, content)

        # --- Positive test for primary account ---
        assert sign_in(client, account).status_code == 303

        html_resp = client.get(f'/download/{slug}/html')
        zip_resp = client.get(f'/download/{slug}/zip')
        preview_resp = client.get(f'/html-preview/{slug}')

        assert html_resp.status_code == 200
        assert zip_resp.status_code == 200
        assert preview_resp.status_code == 200

        profile_name = source.state.profile.personal.name

        assert profile_name in html_resp.text
        assert profile_name in preview_resp.text

        # Check ZIP content
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as archive:
            html_names = [name for name in archive.namelist() if name.endswith('.html')]
            assert len(html_names) == 1
            assert set(archive.namelist()) == {html_names[0], 'style.css'}
            assert profile_name in archive.read(html_names[0]).decode('utf-8')

        # --- Negative test for other account ---
        # Log in as the other account
        assert sign_in(client, other_account).status_code == 303

        # Verification that the other account cannot access the primary account's slug
        # even with query params or X-Account header.
        for query in ('', f'?account={account}', f'?account={other_account}'):
            assert client.get(f'/download/{slug}/html{query}').status_code == 404
            assert client.get(f'/download/{slug}/zip{query}').status_code == 404
            assert client.get(f'/html-preview/{slug}{query}').status_code == 404

        # Also check with X-Account header
        for query in ('', f'?account={account}', f'?account={other_account}'):
            assert client.get(f'/download/{slug}/html{query}', headers={'X-Account': account}).status_code == 404
            assert client.get(f'/download/{slug}/zip{query}', headers={'X-Account': account}).status_code == 404
            assert client.get(f'/html-preview/{slug}{query}', headers={'X-Account': account}).status_code == 404
