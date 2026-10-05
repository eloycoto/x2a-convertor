from src.exporters.types import MigrationCategory
from src.exporters.write_agent import WriteAgent
from src.types import Checklist


def test_scaffolded_pending_role_file_is_not_treated_as_completed(tmp_path):
    path = tmp_path / "tasks" / "main.yml"
    path.parent.mkdir()
    path.write_text("- name: creator placeholder\n  ansible.builtin.debug: {}\n")
    checklist = Checklist("sample", MigrationCategory)
    checklist.add_task("recipes", "recipes/default.rb", str(path), status="pending")

    assert WriteAgent._all_checklist_files_complete(checklist) is False


def test_completed_existing_role_file_can_skip_writer(tmp_path):
    path = tmp_path / "tasks" / "main.yml"
    path.parent.mkdir()
    path.write_text("- name: migrated task\n  ansible.builtin.debug: {}\n")
    checklist = Checklist("sample", MigrationCategory)
    checklist.add_task("recipes", "recipes/default.rb", str(path), status="complete")

    assert WriteAgent._all_checklist_files_complete(checklist) is True


def test_pending_molecule_files_are_excluded_from_writer_completion(tmp_path):
    path = tmp_path / "molecule" / "verify.yml"
    path.parent.mkdir()
    path.write_text("---\n")
    checklist = Checklist("sample", MigrationCategory)
    checklist.add_task("molecule", "N/A", str(path), status="pending")

    assert WriteAgent._all_checklist_files_complete(checklist) is True
