import httpx
import json
import pathlib

url = 'http://127.0.0.1:16333'
headers = {'api-key': 'verify-test-key'}
client = httpx.Client(timeout=30.0, headers=headers)

# Restore snapshot
snapshot_path = r'backups\20260915T152421Z\qdrant.snapshot'
path = pathlib.Path(snapshot_path)
with path.open('rb') as f:
    response = client.post(
        f'{url}/collections/practice_knowledge_ollama_768/snapshots/upload',
        params={'priority': 'snapshot'},
        files={'snapshot': (path.name, f, 'application/octet-stream')}
    )
print('Restore status:', response.status_code)

# Get sample points
response = client.post(
    f'{url}/collections/practice_knowledge_ollama_768/points/scroll',
    json={'limit': 5, 'with_payload': True}
)
print('\nSample points:')
print(json.dumps(response.json(), indent=2))

# Check unique user_ids
response = client.post(
    f'{url}/collections/practice_knowledge_ollama_768/points/scroll',
    json={'limit': 100, 'with_payload': True, 'with_vector': False}
)
points = response.json()['result']['points']
user_ids = set()
academic_years = set()
for point in points:
    payload = point.get('payload', {})
    if 'user_id' in payload and payload['user_id']:
        user_ids.add(payload['user_id'])
    if 'academic_year' in payload:
        academic_years.add(payload['academic_year'])

print(f'\nUnique user_ids: {user_ids}')
print(f'Unique academic_years: {academic_years}')

# Test filter by academic_year
if academic_years:
    test_year = list(academic_years)[0]
    response = client.post(
        f'{url}/collections/practice_knowledge_ollama_768/points/scroll',
        json={
            'limit': 10,
            'with_payload': True,
            'filter': {
                'must': [
                    {'key': 'academic_year', 'match': {'value': test_year}}
                ]
            }
        }
    )
    filtered_points = response.json()['result']['points']
    print(f'\nFilter by academic_year={test_year}: {len(filtered_points)} points')
    if filtered_points:
        print(f'Sample filtered point academic_year: {filtered_points[0]["payload"].get("academic_year")}')

# Test filter by user_id
if user_ids:
    test_user = list(user_ids)[0]
    response = client.post(
        f'{url}/collections/practice_knowledge_ollama_768/points/scroll',
        json={
            'limit': 10,
            'with_payload': True,
            'filter': {
                'must': [
                    {'key': 'user_id', 'match': {'value': test_user}}
                ]
            }
        }
    )
    filtered_points = response.json()['result']['points']
    print(f'\nFilter by user_id={test_user}: {len(filtered_points)} points')
    if filtered_points:
        print(f'Sample filtered point user_id: {filtered_points[0]["payload"].get("user_id")}')
