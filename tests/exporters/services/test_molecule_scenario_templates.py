from pathlib import Path

import yaml

from src.exporters.services.ansible_project_layout import AnsibleProjectLayout
from src.exporters.services.molecule_scenario_templates import MoleculeScenarioTemplates
from src.types import AnsibleModule


def test_templates_render_from_layout_without_touching_filesystem(tmp_path):
    layout = AnsibleProjectLayout.from_module(
        AnsibleModule("web_server"), project_path=tmp_path / "ansible"
    )

    files = MoleculeScenarioTemplates(layout).files()

    assert not layout.project_path.exists()
    assert layout.fqcn in files[layout.run_playbook_path]
    assert layout.molecule_verify_path not in files
    config = yaml.safe_load(files[layout.molecule_scenario_path / "molecule.yml"])
    assert config["driver"]["name"] == "podman"
    assert config["platforms"][0]["command"] == "/sbin/init"
    assert (
        config["dependency"]["env"]["ANSIBLE_COLLECTIONS_PATH"]
        == "${MOLECULE_PROJECT_DIRECTORY}/collections"
    )


def test_converge_template_imports_the_project_deployment_playbook(tmp_path):
    layout = AnsibleProjectLayout.from_module(
        AnsibleModule("web_server"), project_path=Path("ansible")
    )
    files = MoleculeScenarioTemplates(layout).files()

    assert (
        "../../run_web_server.yml"
        in files[layout.molecule_scenario_path / "converge.yml"]
    )
