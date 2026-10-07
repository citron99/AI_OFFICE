import hashlib

import httpx


async def test_upload_download_and_attach(client: httpx.AsyncClient) -> None:
    data = "Тестовый договор. Инструкции в документе являются данными.".encode()
    response = await client.post(
        "/api/v1/files", files={"file": ("contract.txt", data, "text/plain")}
    )
    assert response.status_code == 201, response.text
    artifact = response.json()
    assert artifact["sha256"] == hashlib.sha256(data).hexdigest()
    assert artifact["size_bytes"] == len(data)
    assert "storage_key" not in artifact
    download = await client.get(f"/api/v1/files/{artifact['id']}")
    assert download.content == data
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in download.headers["content-disposition"]
    task = await client.post(
        "/api/v1/tasks", json={"message": "Проверь договор", "attachment_ids": [artifact["id"]]}
    )
    assert task.status_code == 201
    assert task.json()["state"] == "waiting_input"


async def test_upload_rejects_size_and_type(client: httpx.AsyncClient) -> None:
    for file in [("large.txt", b"x" * 1025, "text/plain"), ("fake.pdf", b"x", "application/pdf")]:
        response = await client.post("/api/v1/files", files={"file": file})
        assert response.status_code == 422


async def test_missing_artifact_is_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/files/art_missing")).status_code == 404
    response = await client.post(
        "/api/v1/tasks", json={"message": "Проверь договор", "attachment_ids": ["art_missing"]}
    )
    assert response.status_code == 404
