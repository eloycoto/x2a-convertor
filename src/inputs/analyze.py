import click
import os

from langchain_community.tools.file_management.file_search import FileSearchTool
from langchain_community.tools.file_management.list_dir import ListDirectoryTool
from langchain_community.tools.file_management.read import ReadFileTool
from langchain_community.tools.file_management.write import WriteFileTool
from langgraph_supervisor import create_supervisor
from prompts.get_prompt import get_prompt
from src.model import get_model
from src.inputs.chef import create_chef_detailed_agent


def create_migration_supervisor():
    """Create migration supervisor with Chef agent"""
    
    # Create the chef agent with a name
    chef_agent = create_chef_detailed_agent()
    
    # Use the existing analyzer prompt
    supervisor_prompt = get_prompt("analyzer") 
    tools = [
        FileSearchTool(),
        ListDirectoryTool(),
        ReadFileTool(),
        WriteFileTool(),
    ]

    # Create supervisor with chef agent
    supervisor = create_supervisor(
        model=get_model(),
        agents=[chef_agent],
        tools=tools,
        prompt=supervisor_prompt,
        add_handoff_back_messages=True,
        output_mode="full_history",
    )
    
    return supervisor


def analyze_migration_request(user_request: str, target_dir: str = "."):
    """Intelligently analyze user request and route to appropriate migration agent"""
    click.echo(f"Analyzing migration request: {user_request}")
    
    # Change to target directory
    os.chdir(target_dir)
    
    try:
        # Create the migration supervisor
        supervisor = create_migration_supervisor().compile()
        
        # Prepare the analysis message
        analysis_message = f"""
        The user wants to: {user_request}
        
        Your task is to:
        1. Read the migration-plan.md file to understand what modules are available
        2. Identify which module the user is referring to
        3. Determine what technology that module uses (Chef, Puppet, Salt, etc.)
        4. If it's a Chef cookbook, delegate to the chef_agent
        5. For other technologies, create a basic migration plan yourself
        
        Start by reading migration-plan.md and identifying the relevant module.
        """
        
        # Execute the supervisor
        result = supervisor.invoke(
            {"messages": [{"role": "user", "content": analysis_message}]},
            config={
                "recursion_limit": 50,
                "max_concurrency": 50,
            },
        )

        # Print results
        click.echo("\n✅ Migration analysis completed")
        for message in result["messages"]:
            if hasattr(message, 'pretty_print'):
                message.pretty_print()

        return result

    except Exception as e:
        click.echo(f"Error during migration analysis: {str(e)}")
        raise
