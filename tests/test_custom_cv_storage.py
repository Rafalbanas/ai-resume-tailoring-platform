import json

import pytest

from app.services.cv_editor import CVEditorStore
from app.services.storage import Storage


@pytest.fixture
def storage_setup(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    storage = Storage(data_dir)

    # Create a sample application
    slug = "test-app-1"
    app_folder = data_dir / "generated" / slug
    app_folder.mkdir(parents=True)

    metadata = {
        "company": "Test Company",
        "role": "Test Role",
        "date": "2023-10-30",
        "cv_name": "Original Name",
        "summary_confirmation": "token123",
        "summary_confirmed_at": "2023-10-30T12:00:00Z",
        "truth_lock_enabled": True,
        "truth_lock_level": 1.0,
        "candidate_data_status": "Source validation enabled"
    }

    # Create some files in the folder
    with open(app_folder / "metadata.json", "w") as f:
        json.dump(metadata, f)

    with open(app_folder / "resume.json", "w") as f:
        json.dump({"some": "data"}, f)
    with open(app_folder / "resume.generated.json", "w") as f:
        json.dump({"some": "data"}, f)
    with open(app_folder / "job.json", "w") as f:
        json.dump({"job_description": "some description"}, f)
    with open(app_folder / "job.txt", "w") as f:
        f.write("some description")
    with open(app_folder / "analysis.json", "w") as f:
        json.dump({"match_level": 0.9}, f)

    return storage, slug

def test_rename_application_success(storage_setup):
    storage, slug = storage_setup
    new_name = "New Valid Name"

    storage.rename_application(slug, new_name)

    folder = storage.application_folder(slug)
    metadata = json.loads((folder / "metadata.json").read_text())
    assert metadata["cv_name"] == new_name

def test_rename_application_invalid_name_short(storage_setup):
    storage, slug = storage_setup
    with pytest.raises(ValueError, match="Name must be between 1 and 150 characters"):
        storage.rename_application(slug, "")

def test_rename_application_invalid_name_long(storage_setup):
    storage, slug = storage_setup
    long_name = "a" * 151
    with pytest.raises(ValueError, match="Name must be between 1 and 150 characters"):
        storage.rename_application(slug, long_name)

def test_rename_application_strips_whitespace(storage_setup):
    storage, slug = storage_setup
    new_name = "  New Name  "
    storage.rename_application(slug, new_name)

    folder = storage.application_folder(slug)
    metadata = json.loads((folder / "metadata.json").read_text())
    assert metadata["cv_name"] == "New Name"

def test_duplicate_application_success(storage_setup):
    storage, slug = storage_setup

    new_slug = storage.duplicate_application(slug)

    assert "-" in new_slug
    assert new_slug.startswith(slug)

    new_folder = storage.application_folder(new_slug)
    new_metadata = json.loads((new_folder / "metadata.json").read_text())

    assert new_metadata["cv_name"] == "Original Name (copy)"
    assert "summary_confirmation" not in new_metadata
    assert "summary_confirmed_at" not in new_metadata

    # Ensure source is not modified
    source_folder = storage.application_folder(slug)
    source_metadata = json.loads((source_folder / "metadata.json").read_text())
    assert source_metadata["cv_name"] == "Original Name"
    assert "summary_confirmation" in source_metadata

@pytest.fixture
def cv_editor_store(tmp_path):
    return CVEditorStore(tmp_path)

def test_cv_editor_create_with_valid_template(cv_editor_store):
    name = "Test CV"
    text = "Content"
    identifier = cv_editor_store.create(name, text, template_name="modern_sidebar")
    doc = cv_editor_store.load(identifier)
    assert doc["template_name"] == "modern_sidebar"

def test_cv_editor_create_with_invalid_template(cv_editor_store):
    with pytest.raises(ValueError, match="Invalid template name"):
        cv_editor_store.create("Test", "Text", template_name="invalid")

def test_cv_editor_load_legacy_cv_default_template(cv_editor_store):
    id_hex = "00000000000000000000000000000001"
    doc_no_tmpl = {
        "id": id_hex,
        "name": "Legacy",
        "original": "...",
        "current": "...",
        "revision": 0,
        "versions": [],
        "pending": None,
        "created_at": "2023-01-01"
    }
    path = cv_editor_store.directory / f"{id_hex}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc_no_tmpl, f)

    original_bytes = path.read_bytes()
    loaded = cv_editor_store.load(id_hex)
    assert loaded["template_name"] == "ats_classic"
    assert path.read_bytes() == original_bytes

def test_cv_editor_duplicate_preserves_template(cv_editor_store):
    id1 = cv_editor_store.create("CV1", "Content", template_name="modern_sidebar")
    id2 = cv_editor_store.duplicate(id1)
    doc2 = cv_editor_store.load(id2)
    assert doc2["template_name"] == "modern_sidebar"

def test_cv_editor_update_template_success(cv_editor_store):
    id1 = cv_editor_store.create("CV1", "Content", template_name="ats_classic")
    cv_editor_store.update(id1, 0, "template", template_name="modern_sidebar")
    doc = cv_editor_store.load(id1)
    assert doc["template_name"] == "modern_sidebar"

def test_cv_editor_update_template_invalid_fails(cv_editor_store):
    id1 = cv_editor_store.create("CV1", "Content", template_name="ats_classic")
    with pytest.raises(ValueError, match="Invalid template name"):
        cv_editor_store.update(id1, 0, "template", template_name="invalid")

def test_cv_editor_propose_does_not_change_template(cv_editor_store):
    id1 = cv_editor_store.create("CV1", "Content", template_name="modern_sidebar")
    cv_editor_store.propose(id1, 0, "New Content", "Instruction")
    doc = cv_editor_store.load(id1)
    assert doc["template_name"] == "modern_sidebar"

def test_cv_editor_actions_keep_template(cv_editor_store):
    id1 = cv_editor_store.create("CV1", "Content", template_name="modern_sidebar")

    cv_editor_store.update(id1, 0, "manual", text="New Content")
    assert cv_editor_store.load(id1)["template_name"] == "modern_sidebar"

    cv_editor_store.update(id1, 1, "undo")
    assert cv_editor_store.load(id1)["template_name"] == "modern_sidebar"

    cv_editor_store.update(id1, 2, "restore")
    assert cv_editor_store.load(id1)["template_name"] == "modern_sidebar"

    cv_editor_store.update(id1, 3, "discard")
    assert cv_editor_store.load(id1)["template_name"] == "modern_sidebar"

def test_cv_editor_pending_revision_updates_on_template(cv_editor_store):
    id1 = cv_editor_store.create("CV1", "Content", template_name="ats_classic")
    cv_editor_store.propose(id1, 0, "Proposal", "Instruction")
    doc = cv_editor_store.load(id1)
    assert doc["pending"]["revision"] == 0

    cv_editor_store.update(id1, 0, "template", template_name="modern_sidebar")
    doc = cv_editor_store.load(id1)
    assert doc["pending"]["revision"] == 1

    cv_editor_store.update(id1, 1, "accept")
    doc = cv_editor_store.load(id1)
    assert doc["pending"] is None
    assert doc["current"] == "Proposal"
    assert doc["template_name"] == "modern_sidebar"
