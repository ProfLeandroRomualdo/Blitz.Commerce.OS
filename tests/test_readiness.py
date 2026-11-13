
def test_readiness(client):
    response = client.get('/readyz')
    assert response.status_code == 200
    assert response.json()['database'] == 'sqlite-demo'
