from fastapi.testclient import TestClient


def test_notice_is_public_without_exposing_private_pages():
    from app.main import app
    with TestClient(app) as client:
        response = client.get('/cookies')
        assert response.status_code == 200
        assert 'About cookies' in response.text
        assert '<code>session</code>' in response.text
        assert '<code>csrf_token</code>' in response.text
        assert '8 hours' in response.text
        assert 'no-store' in response.headers['cache-control']
        assert client.get('/profile', follow_redirects=False).status_code == 303
        assert 'href="/cookies"' in client.get('/login').text
