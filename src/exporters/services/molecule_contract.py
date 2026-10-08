"""Shared Molecule scenario contract values used by generation and validation."""

DEFAULT_LINUX_IMAGE = "registry.access.redhat.com/ubi9/ubi-init:latest"
COLLECTIONS_PATH_TEMPLATE = "${MOLECULE_PROJECT_DIRECTORY}/collections"
SYSTEMD_COMMAND = "/sbin/init"
SYSTEMD_MODE = "always"
MOLECULE_DRIVER = "podman"
PODMAN_COLLECTION = "containers.podman"
REQUIREMENTS_FILE = "molecule/requirements.yml"
