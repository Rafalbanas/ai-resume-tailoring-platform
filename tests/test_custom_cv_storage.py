import json

import pytest

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
