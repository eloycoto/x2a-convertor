#!/usr/bin/env python3

import click
import logging
import os
import sys
from dotenv import load_dotenv

from langchain.globals import set_debug
from src.init import init_project
from src.validate import validate_component
from src.inputs.analyze import  analyze_migration_request


def setup_logging():
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(stream=sys.stderr, level=log_level)
    if log_level == "DEBUG":
        set_debug(True)


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """X2Ansible - Infrastructure Migration Tool"""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("user_requirements")
@click.option("--source-dir", default=".", help="Source directory to analyze")
def init(user_requirements, source_dir):
    """Initialize project with interactive message"""
    init_project(user_requirements=user_requirements, source_dir=source_dir)


@cli.command()
@click.argument("message")
@click.option("--dir", default=".", help="Target repository directory")
def analyze(message, dir):
    analyze_migration_request(message, dir)


@cli.command()
def migrate(component_name, dir):
    pass

@cli.command()
@click.argument("component_name")
def validate(component_name):
    """Validate migrated component against original configuration"""
    validate_component(component_name)


if __name__ == "__main__":
    load_dotenv()
    setup_logging()
    cli()
