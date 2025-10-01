import click
import os

from langchain_community.tools.file_management.file_search import FileSearchTool
from langchain_community.tools.file_management.list_dir import ListDirectoryTool
from langchain_community.tools.file_management.read import ReadFileTool
from langchain_community.tools.file_management.write import WriteFileTool
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
        name="chef_cookbook_migration_specialist"
    )
    return agent


def create_detailed_migration_plan(module_name: str, module_path: str, description: str, target_dir: str = "."):
    """Create detailed migration plan for a specific Chef cookbook"""
    click.echo(f"Creating detailed Chef migration plan for: {module_name}")
    
    # Change to target directory
    os.chdir(target_dir)
    
    try:
        # Create the Chef specialist agent
        agent = create_chef_detailed_agent()
        
        # Prepare detailed analysis message
        user_message = f"""
        Create a comprehensive, detailed migration plan for the Chef cookbook: {module_name}
        
        Module Information:
        - Name: {module_name}
        - Path: {module_path}
        - Description: {description}
        
        You are a senior software engineer writing a detailed migration guide for a junior contractor.
        The junior engineer will follow this guide exactly to migrate this Chef cookbook to Ansible.
        
        Requirements:
        1. Explore the cookbook directory: {module_path}
        2. Analyze all recipes, attributes, templates, and files
        3. Map Chef resources to Ansible equivalents
        4. Create step-by-step migration instructions
        5. Include all validation checkpoints and commands
        6. Identify risks and provide mitigation strategies
        7. Write the complete plan to 'migration-plan-{module_name}.md'
        
        The guide must be so detailed that a junior engineer can follow it without senior assistance.
        Include specific commands to verify each step works correctly.
        """
        
        # Execute the agent
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_message}]},
            config={
                "recursion_limit": 50,
                "max_concurrency": 50,
            },
        )
        
        # Check if the detailed plan was created
        detailed_plan_path = f"migration-plan-{module_name}.md"
        if os.path.exists(detailed_plan_path):
            click.echo(f"Detailed migration plan created: {detailed_plan_path}")
        else:
            click.echo(f"Warning: {detailed_plan_path} was not created.")
            
        return result
        
    except Exception as e:
        click.echo(f"Error during Chef migration planning: {str(e)}")
        raise


def chef_node(state):
    """Chef specialist node for LangGraph multi-agent workflow"""
    chef_agent = create_chef_detailed_agent()
    
    # Extract module info from state
    module_name = state.get("module_name", "unknown")
    module_path = state.get("module_path", ".")
    description = state.get("description", "Chef cookbook")
    
    # Create detailed message for Chef agent
    chef_message = f"""
    You are receiving a handoff from the analyzer agent.
    
    Module Information:
    - Name: {module_name}
    - Path: {module_path}
    - Description: {description}
    
    Create a comprehensive, detailed migration plan for this Chef cookbook.
    You are a senior software engineer writing a detailed migration guide for a junior contractor.
    The junior engineer will follow this guide exactly to migrate this Chef cookbook to Ansible.
    
    Requirements:
    1. Explore the cookbook directory: {module_path}
    2. Analyze all recipes, attributes, templates, and files
    3. Map Chef resources to Ansible equivalents
    4. Create step-by-step migration instructions
    5. Include all validation checkpoints and commands
    6. Identify risks and provide mitigation strategies
    7. Write the complete plan to 'migration-plan-{module_name}.md'
    
    The guide must be so detailed that a junior engineer can follow it without senior assistance.
    Include specific commands to verify each step works correctly.
    """
    
    # Add the chef message to the state
    chef_state = {
        **state,
        "messages": state["messages"] + [{"role": "user", "content": chef_message}]
    }
    
    click.echo(f"🍳 Chef agent processing: {module_name}")
    result = chef_agent.invoke(chef_state)
    
    # Check if detailed plan was created
    detailed_plan_path = f"migration-plan-{module_name}.md"
    if os.path.exists(detailed_plan_path):
        click.echo(f"✅ Chef migration plan created: {detailed_plan_path}")
    else:
        click.echo(f"⚠️  Warning: {detailed_plan_path} was not created")
    
    return result


def analyze_chef_cookbooks():
    """Chef cookbook analyzer"""
    click.echo("Analyzing Chef cookbooks")
    # TODO: Implement Chef analysis logic
    pass
