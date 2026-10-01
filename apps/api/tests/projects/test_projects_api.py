"""The projects routes over the in-memory fakes: a bare FastAPI, no database.

The workspace dependency is a stub, because resolving it is identity's job and the
composition root's wiring. What is asserted here is the router's own contract: every route's
status, the status each refusal in the design's error table gets, and the shapes on the wire
the web builds on (design's HTTP API).
"""

from typing import Any, get_args

import pytest
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.testclient import TestClient

from support.projects import BENCH, World
from wiredex.projects.api.router import create_router
from wiredex.projects.api.schemas import RevisionStatusName
from wiredex.projects.domain.values import RevisionStatus, WorkspaceId

PROJECTS = "/api/projects"
REVISIONS = f"{PROJECTS}/revisions"
MADE_UP = "0199aaaa-0000-7000-8000-000000000000"
SIXTEEN_ZS = "Z" * 16


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


async def nobody(_request: Request) -> WorkspaceId:
    """A request with no valid session, which identity refuses before projects is reached."""
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "log in first")


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.projects_use_cases(), the_bench), prefix="/api")
    return TestClient(app)


def created(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POSTs something that is expected to work, so a test can get on with its point."""
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    answered: dict[str, Any] = response.json()
    return answered


# --- Projects -----------------------------------------------------------------------------


def test_a_new_project_comes_with_revision_a_and_its_next_label(client: TestClient) -> None:
    # Requirements 1.1 and 1.6: the project, its revision A, the latest and the suggestion.
    project = created(
        client,
        PROJECTS,
        {"name": "  Weather   station ", "description": "A BME280\r\non an ESP32.  "},
    )

    assert project["name"] == "Weather station"
    assert project["description"] == "A BME280\non an ESP32."
    [first] = project["revisions"]
    assert (first["label"], first["status"], first["forked_from"]) == ("A", "draft", None)
    assert first["project_id"] == project["id"]
    assert project["latest_revision_id"] == first["id"]
    assert project["next_label"] == "B"


def test_tags_are_normalized_on_the_way_in(client: TestClient) -> None:
    # Requirements 2.1 and 2.3: each once, folded, alphabetical, whatever was typed.
    project = created(
        client, PROJECTS, {"name": "Weather station", "tags": ["ESP32", " i2c ", "esp32"]}
    )

    assert project["tags"] == ["esp32", "i2c"]


@pytest.mark.parametrize("blank", ["", "   ", "\r\n\t"])
def test_a_blank_description_reads_as_none(client: TestClient, blank: str) -> None:
    project = created(client, PROJECTS, {"name": "Weather station", "description": blank})

    assert project["description"] is None


def test_a_name_another_project_holds_is_a_conflict_that_names_it(
    client: TestClient, world: World
) -> None:
    # Requirement 1.3: compared ignoring case, and the refusal names the holder.
    world.hold_project("Weather station")

    response = client.post(PROJECTS, json={"name": "WEATHER STATION"})

    assert response.status_code == 409
    assert response.json()["detail"] == "there is already a project named Weather station"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": "   "},
        {"name": "x" * 121},
        {"name": "Weather station", "description": "x" * 4_001},
        {"name": "Weather station", "tags": ["esp32,i2c"]},
        {"name": "Weather station", "tags": ["x" * 33]},
        {"name": "Weather station", "tags": [" "]},
    ],
)
def test_a_project_its_values_refuse_is_unprocessable(
    client: TestClient, world: World, body: dict[str, Any]
) -> None:
    response = client.post(PROJECTS, json=body)

    assert response.status_code == 422
    assert world.work.commits == 0


def test_a_refused_tag_is_named(client: TestClient) -> None:
    # Requirement 2.2: the sentence says which tag.
    response = client.post(PROJECTS, json={"name": "Weather station", "tags": ["i2c, spi"]})

    assert response.status_code == 422
    assert "i2c, spi" in response.json()["detail"]


def test_twenty_one_tags_are_refused(client: TestClient, world: World) -> None:
    # Requirement 2.4, at the edge: the request schema caps what it takes.
    tags = [f"tag{n}" for n in range(21)]

    too_many = client.post(PROJECTS, json={"name": "Weather station", "tags": tags})
    enough = client.post(PROJECTS, json={"name": "Weather station", "tags": tags[:20]})

    assert too_many.status_code == 422
    assert enough.status_code == 201
    assert world.work.commits == 1


def test_a_project_opens_with_its_revisions_oldest_first(client: TestClient, world: World) -> None:
    project = world.hold_project("Weather station", tags=["esp32"])
    world.hold_revision(project, "C", minutes=2)
    world.hold_revision(project, "B", minutes=1)

    response = client.get(f"{PROJECTS}/{project.id}")

    assert response.status_code == 200
    body = response.json()
    assert [revision["label"] for revision in body["revisions"]] == ["A", "B", "C"]
    assert body["latest_revision_id"] == body["revisions"][-1]["id"]
    # The latest is C, and its successor D is free.
    assert body["next_label"] == "D"
    assert body["tags"] == ["esp32"]


def test_a_project_with_no_label_left_has_no_next_label(client: TestClient, world: World) -> None:
    project = world.hold_project("Weather station", revision=SIXTEEN_ZS)

    response = client.get(f"{PROJECTS}/{project.id}")

    assert response.status_code == 200
    assert response.json()["next_label"] is None


def test_an_edit_replaces_the_details_whole(client: TestClient, world: World) -> None:
    # Requirement 1.5: what the edit leaves out is cleared, not kept.
    project = world.hold_project("Weather station", tags=["esp32"], description="Old words.")

    response = client.patch(
        f"{PROJECTS}/{project.id}", json={"name": "Weather Station", "tags": ["I2C"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["description"], body["tags"]) == ("Weather Station", None, ["i2c"])
    assert world.work.commits == 1


def test_an_edit_that_changes_nothing_writes_nothing(client: TestClient, world: World) -> None:
    project = world.hold_project("Weather station", tags=["esp32"])

    response = client.patch(
        f"{PROJECTS}/{project.id}", json={"name": "Weather station", "tags": ["ESP32"]}
    )

    assert response.status_code == 200
    assert world.work.commits == 0


def test_renaming_to_a_name_another_project_holds_is_a_conflict(
    client: TestClient, world: World
) -> None:
    world.hold_project("Greenhouse controller")
    project = world.hold_project("Weather station")

    response = client.patch(f"{PROJECTS}/{project.id}", json={"name": "greenhouse CONTROLLER"})

    assert response.status_code == 409


def test_an_edit_its_values_refuse_is_unprocessable(client: TestClient, world: World) -> None:
    project = world.hold_project("Weather station")

    response = client.patch(f"{PROJECTS}/{project.id}", json={"name": "   "})

    assert response.status_code == 422


def test_deleting_a_project_answers_no_content(client: TestClient, world: World) -> None:
    project = world.hold_project("Weather station")

    response = client.delete(f"{PROJECTS}/{project.id}")

    assert response.status_code == 204
    # To the trash (16's requirement 1.1): absent from the API from then on.
    assert world.work.projects.saved[project.id].in_trash
    assert client.get(f"{PROJECTS}/{project.id}").status_code == 404


def test_deleting_a_project_holding_a_built_revision_is_a_conflict(
    client: TestClient, world: World
) -> None:
    # Requirement 1.8, reachable only through the fakes before 10-build-lifecycle.
    project = world.hold_project("Weather station")
    world.hold_revision(project, "B", status=RevisionStatus.BUILT, minutes=1)

    response = client.delete(f"{PROJECTS}/{project.id}")

    assert response.status_code == 409
    assert "revision B is built" in response.json()["detail"]
    assert project.id in world.work.projects.saved


@pytest.mark.parametrize(
    ("method", "body"),
    [("GET", None), ("PATCH", {"name": "Nowhere"}), ("DELETE", None)],
)
def test_a_project_not_in_the_workspace_is_not_found(
    client: TestClient, method: str, body: dict[str, Any] | None
) -> None:
    # Requirements 1.9 and 8.2: another workspace's id reads as no project, never a 403.
    response = client.request(method, f"{PROJECTS}/{MADE_UP}", json=body)

    assert response.status_code == 404
    assert response.json()["detail"] == "that project doesn't exist"


# --- The list and its tags ----------------------------------------------------------------


def test_the_list_opens_on_the_freshest_work(client: TestClient, world: World) -> None:
    # Requirements 3.1 and 3.2: a revision's own date moves its project up the list.
    older = world.hold_project("Greenhouse controller", tags=["relay"], minutes=5)
    newer = world.hold_project("Weather station", tags=["esp32", "i2c"])
    world.hold_revision(newer, "B", minutes=10)

    response = client.get(PROJECTS)

    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == [str(newer.id), str(older.id)]
    first = rows[0]
    assert first["tags"] == ["esp32", "i2c"]
    assert first["revision_count"] == 2
    assert first["latest_revision"]["label"] == "B"
    assert first["latest_revision"]["status"] == "draft"
    assert first["latest_revision"]["summary"] is None


def test_the_list_narrows_by_text_and_by_normalized_tags(client: TestClient, world: World) -> None:
    # Requirements 3.3 and 3.4: every tag asked for, each spelled as a stored tag is.
    world.hold_project("Weather station", tags=["esp32", "i2c"])
    world.hold_project("Weather vane", tags=["esp32"])
    world.hold_project("Greenhouse controller", tags=["esp32", "i2c"])

    response = client.get(PROJECTS, params={"q": "WEATHER", "tag": ["ESP32", " i2c "]})

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == ["Weather station"]


def test_a_list_nothing_matches_is_empty(client: TestClient, world: World) -> None:
    # Requirement 3.5.
    world.hold_project("Weather station")

    response = client.get(PROJECTS, params={"q": "nowhere"})

    assert response.status_code == 200
    assert response.json() == []


def test_a_list_filter_its_tags_refuse_is_unprocessable(client: TestClient) -> None:
    too_many = client.get(PROJECTS, params={"tag": [f"tag{n}" for n in range(21)]})
    refused = client.get(PROJECTS, params={"tag": "a,b"})

    assert too_many.status_code == 422
    assert refused.status_code == 422


def test_the_workspace_s_tags_come_with_their_counts(client: TestClient, world: World) -> None:
    # Requirement 2.6: each tag once, alphabetical, with how many projects carry it.
    world.hold_project("Weather station", tags=["i2c", "esp32"])
    world.hold_project("Greenhouse controller", tags=["esp32", "relay"])

    response = client.get(f"{PROJECTS}/tags")

    assert response.status_code == 200
    assert response.json() == [
        {"tag": "esp32", "projects": 2},
        {"tag": "i2c", "projects": 1},
        {"tag": "relay", "projects": 1},
    ]


def test_tags_is_never_read_as_a_project_id(client: TestClient) -> None:
    # Declared before `/projects/{project_id}`, so an empty workspace answers an empty list,
    # not a 422 for a malformed UUID or a 404 for a project called "tags".
    response = client.get(f"{PROJECTS}/tags")

    assert response.status_code == 200
    assert response.json() == []


# --- Revisions ----------------------------------------------------------------------------


def test_a_new_revision_takes_the_suggested_label(client: TestClient, world: World) -> None:
    # Requirements 4.1 and 4.4: no label is the latest one stepped on.
    project = world.hold_project("Weather station")

    revision = created(client, f"{PROJECTS}/{project.id}/revisions", {"summary": " perfboard "})

    assert (revision["label"], revision["summary"], revision["status"]) == (
        "B",
        "perfboard",
        "draft",
    )
    assert revision["project_id"] == str(project.id)
    assert revision["forked_from"] is None


def test_a_new_revision_takes_the_label_given(client: TestClient, world: World) -> None:
    project = world.hold_project("Weather station")

    revision = created(
        client, f"{PROJECTS}/{project.id}/revisions", {"label": "v2", "notes": "Moved the BME280."}
    )

    assert (revision["label"], revision["notes"]) == ("v2", "Moved the BME280.")


@pytest.mark.parametrize("field", ["summary", "notes"])
def test_blank_revision_texts_read_as_none(client: TestClient, world: World, field: str) -> None:
    project = world.hold_project("Weather station")

    revision = created(client, f"{PROJECTS}/{project.id}/revisions", {field: "  \n "})

    assert revision[field] is None


def test_a_label_the_project_holds_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 4.3: ignoring case, and the refusal names the project and the label held.
    project = world.hold_project("Weather station")

    response = client.post(f"{PROJECTS}/{project.id}/revisions", json={"label": "a"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Weather station already has a revision A"


@pytest.mark.parametrize("label", ["-A", "a b", "é", "x" * 17, ""])
def test_a_label_outside_its_rules_is_unprocessable(
    client: TestClient, world: World, label: str
) -> None:
    # Requirement 4.2.
    project = world.hold_project("Weather station")

    response = client.post(f"{PROJECTS}/{project.id}/revisions", json={"label": label})

    assert response.status_code == 422


def test_no_label_left_asks_for_one(client: TestClient, world: World) -> None:
    # Requirement 4.6: sixteen Zs can't be stepped within sixteen characters.
    project = world.hold_project("Weather station", revision=SIXTEEN_ZS)

    response = client.post(f"{PROJECTS}/{project.id}/revisions", json={})

    assert response.status_code == 422
    assert response.json()["detail"] == "give the revision a label"


def test_a_revision_for_a_project_not_in_the_workspace_is_not_found(client: TestClient) -> None:
    response = client.post(f"{PROJECTS}/{MADE_UP}/revisions", json={})

    assert response.status_code == 404


def test_an_edit_replaces_a_revision_s_texts_whole(client: TestClient, world: World) -> None:
    # Requirement 4.8, in any status: a built revision is still relabelled.
    project = world.hold_project("Weather station")
    built = world.hold_revision(project, "B", status=RevisionStatus.BUILT, minutes=1)

    response = client.patch(
        f"{REVISIONS}/{built.id}", json={"label": "rev-b", "summary": "perfboard", "notes": " "}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["label"], body["summary"], body["notes"]) == ("rev-b", "perfboard", None)
    assert body["status"] == "built"


def test_relabelling_to_a_sibling_s_label_is_a_conflict(client: TestClient, world: World) -> None:
    project = world.hold_project("Weather station")
    second = world.hold_revision(project, "B", minutes=1)

    response = client.patch(f"{REVISIONS}/{second.id}", json={"label": "a"})

    assert response.status_code == 409


def test_an_edit_its_label_refuses_is_unprocessable(client: TestClient, world: World) -> None:
    project = world.hold_project("Weather station")
    second = world.hold_revision(project, "B", minutes=1)

    missing = client.patch(f"{REVISIONS}/{second.id}", json={"summary": "perfboard"})
    refused = client.patch(f"{REVISIONS}/{second.id}", json={"label": "B!"})

    assert missing.status_code == 422
    assert refused.status_code == 422


def test_deleting_a_draft_revision_answers_no_content(client: TestClient, world: World) -> None:
    # Requirement 5.1.
    project = world.hold_project("Weather station")
    second = world.hold_revision(project, "B", minutes=1)

    response = client.delete(f"{REVISIONS}/{second.id}")

    assert response.status_code == 204
    assert second.id not in world.work.revisions.saved


def test_deleting_the_only_revision_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 5.2: the project is what goes, not its last revision.
    project = world.hold_project("Weather station")
    [only] = world.work.revisions.saved.values()

    response = client.delete(f"{REVISIONS}/{only.id}")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "a project keeps at least one revision; delete the project instead"
    )
    assert project.id in world.work.projects.saved


def test_deleting_a_built_revision_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 5.3.
    project = world.hold_project("Weather station")
    built = world.hold_revision(project, "B", status=RevisionStatus.BUILT, minutes=1)

    response = client.delete(f"{REVISIONS}/{built.id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "revision B is built; dismantle the build first"


def test_a_fork_is_a_draft_that_remembers_its_source(client: TestClient, world: World) -> None:
    # Requirements 6.1 and 6.5: whatever the source's status, labelled as suggested.
    project = world.hold_project("Weather station")
    built = world.hold_revision(project, "B", status=RevisionStatus.BUILT, minutes=1)

    fork = created(client, f"{REVISIONS}/{built.id}/fork", {"summary": "first PCB"})

    assert (fork["label"], fork["status"], fork["summary"]) == ("C", "draft", "first PCB")
    assert fork["forked_from"] == str(built.id)
    assert fork["project_id"] == str(project.id)


def test_a_fork_under_a_label_the_project_holds_is_a_conflict(
    client: TestClient, world: World
) -> None:
    world.hold_project("Weather station")
    [source] = world.work.revisions.saved.values()

    response = client.post(f"{REVISIONS}/{source.id}/fork", json={"label": "A"})

    assert response.status_code == 409


def test_a_fork_with_no_label_left_asks_for_one(client: TestClient, world: World) -> None:
    world.hold_project("Weather station", revision=SIXTEEN_ZS)
    [source] = world.work.revisions.saved.values()

    response = client.post(f"{REVISIONS}/{source.id}/fork", json={})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", f"{REVISIONS}/{MADE_UP}", {"label": "B"}),
        ("DELETE", f"{REVISIONS}/{MADE_UP}", None),
        ("POST", f"{REVISIONS}/{MADE_UP}/fork", {}),
    ],
)
def test_a_revision_not_in_the_workspace_is_not_found(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    # Requirements 5.6 and 8.2.
    response = client.request(method, path, json=body)

    assert response.status_code == 404
    assert response.json()["detail"] == "that revision doesn't exist"


# --- The contract -------------------------------------------------------------------------


def test_the_wire_names_every_revision_status() -> None:
    # A fifth state stops here until the client's union lists it too, the way
    # `MovementReasonName` keeps its own contract honest.
    assert set(get_args(RevisionStatusName.__value__)) == {s.value for s in RevisionStatus}


def test_a_request_with_no_session_never_reaches_projects(world: World) -> None:
    # Requirement 8.5: identity refuses first, so no use case runs.
    app = FastAPI()
    app.include_router(create_router(world.projects_use_cases(), nobody), prefix="/api")
    logged_out = TestClient(app)

    response = logged_out.post(PROJECTS, json={"name": "Weather station"})

    assert response.status_code == 401
    assert world.work.opened_for == []
