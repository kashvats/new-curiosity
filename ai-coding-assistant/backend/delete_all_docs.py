import requests, json

docs = requests.get('http://localhost:8000/documents').json()
doc_list = docs if isinstance(docs, list) else docs.get('documents', [])
print(f'Found {len(doc_list)} documents')

deleted = 0
for d in doc_list:
    doc_id = d['id']
    r = requests.delete(f'http://localhost:8000/documents/{doc_id}')
    if r.status_code in (200, 204):
        deleted += 1
    else:
        print(f'Failed {doc_id}: {r.status_code} {r.text[:80]}')

print(f'Done: deleted {deleted}/{len(doc_list)}')
