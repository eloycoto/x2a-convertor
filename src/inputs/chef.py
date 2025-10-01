import click
import os

from langchain_community.tools.file_management.file_search import FileSearchTool
from langchain_community.tools.file_management.list_dir import ListDirectoryTool
from langchain_community.tools.file_management.read import ReadFileTool
from langchain_community.tools.file_management.write import WriteFileTool
from langgraph_supervisor.handoff import create_handoff_tool
from langgraph.prebuilt import create_react_agent
from prompts.get_prompt import get_prompt
from src.model import get_model


def create_chef_detailed_agent():
    """Create an agent that explores Chef cookbooks and generates detailed migration plans to Ansible.

    The agent will:
    - Explore cookbook directory structure using file tools
    - Read and analyze recipes, templates, and attributes
    - Generate step-by-step migration instructions with validation commands
    """
    name = "chef_cookbook_migration_specialist"
    model = get_model()

    # Set up file management tools
    tools = [
        FileSearchTool(),
        ListDirectoryTool(),
        ReadFileTool(),
    ]

    # Get the Chef detailed migration prompt
    system_prompt = get_prompt("chef_detailed")

    # Create the agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt=system_prompt,
        name=name,
    )

    chef_handoff_tool = create_handoff_tool(
        agent_name=name,
        description="Analyzes Chef cookbooks and creates detailed specifications on what the cookbook does"
    )
    
    return agent, chef_handoff_tool
