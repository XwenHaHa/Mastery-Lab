"""P1.6-G：课程素材上传、读取与删除。"""

from __future__ import annotations

import base64

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lK3Q6wAAAABJRU5ErkJggg=="
)


def _upload(client, course_id, name="dot.png", content=PNG_1PX, mime="image/png", caption="红点"):
    return client.post(
        f"/api/v1/courses/{course_id}/materials",
        files={"file": (name, content, mime)},
        data={"caption": caption},
    )


def test_upload_list_read_delete_material(client, seeded):
    course_id = seeded["course"].id
    response = _upload(client, course_id)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["kind"] == "image"
    assert data["mimeType"] == "image/png"
    assert data["caption"] == "红点"
    assert data["url"].endswith(f"/materials/{data['id']}/content")

    listed = client.get(f"/api/v1/courses/{course_id}/materials")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [data["id"]]

    content = client.get(data["url"])
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/png")
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.content.startswith(b"\x89PNG")

    deleted = client.delete(f"/api/v1/materials/{data['id']}")
    assert deleted.status_code == 200
    assert client.get(data["url"]).status_code == 404
    assert client.get(f"/api/v1/materials/{data['id']}").status_code == 404


def test_material_rejects_unsupported_and_fake_files(client, seeded):
    course_id = seeded["course"].id
    svg = _upload(client, course_id, name="x.svg", content=b"<svg/>", mime="image/svg+xml")
    assert svg.status_code == 415

    fake = _upload(client, course_id, name="fake.png", content=b"<html>hello</html>")
    assert fake.status_code == 400

    empty = _upload(client, course_id, name="empty.png", content=b"")
    assert empty.status_code == 400

    missing = _upload(client, 999999)
    assert missing.status_code == 404


def test_deleting_course_removes_material_files(client, seeded):
    course_id = seeded["course"].id
    response = _upload(client, course_id)
    data = response.json()["data"]

    deleted = client.delete(f"/api/v1/courses/{course_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/materials/{data['id']}").status_code == 404
    assert client.get(data["url"]).status_code == 404
