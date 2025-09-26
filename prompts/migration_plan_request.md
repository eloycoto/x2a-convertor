Analyze this directory for migration to Ansible.

User requirements: {user_requirements}

## Analysis Phase
Start by systematically exploring the directory structure to understand the current infrastructure automation setup:

1. **Technology Stack Identification**
   - Scan for configuration files: `.chef/`, `Puppetfile`, `metadata.rb`, `Berksfile`, `Vagrantfile`, etc.
   - Identify the primary automation tool (Chef, Puppet, Salt, SaltStack, etc.)
   - Document version information and dependencies

2. **Comprehensive Inventory**
   - Catalog all cookbooks/modules/manifests/states with their purposes
   - Map resource types (packages, services, files, templates, etc.)
   - Identify custom resources and library functions
   - Document data bags, hiera data, or pillar configurations

3. **Dependency Analysis**
   - External cookbook/module dependencies
   - System package requirements
   - Network dependencies and firewall rules
   - Integration points with external services

4. **Security and Compliance**
   - Authentication and authorization mechanisms
   - Secrets management approaches
   - Compliance frameworks in use
   - Security hardening configurations

5. **Risk Assessment**
   - Critical services that cannot afford downtime
   - Complex configurations that may be difficult to migrate
   - Deprecated or unsupported components
   - Potential compatibility issues

## Output Requirements
Write a comprehensive migration plan to the file `{migration_plan_file}` in the root directory that includes:

- **Executive Summary** with complexity rating and timeline estimate
- **Current State Analysis** with detailed inventory
- **Migration Strategy** with phased approach and rollback procedures
- **Resource Mapping** showing Chef/Puppet → Ansible equivalents
- **Testing Plan** with validation criteria
- **Risk Mitigation** strategies for identified concerns
- **Team Coordination** guidelines and training requirements
- **Success Metrics** and acceptance criteria

Ensure the plan is actionable, includes specific Ansible module recommendations, and provides clear next steps for implementation.

**MANDATORY FINAL STEP:**
You MUST make an actual TOOL CALL to the write_file function with the REAL migration plan content you analyzed.

CRITICAL: In the write_file tool call, the "text" parameter must contain your ACTUAL migration plan analysis - NOT placeholder text like "[your complete migration plan content]".

Example of WRONG tool call:
write_file(file_path="migration-plan.md", text="[your complete migration plan content]")

Example of CORRECT tool call:
write_file(file_path="{migration_plan_file}", text="# MIGRATION FROM CHEF TO ANSIBLE\n\n## Executive Summary\nThis project contains 2 Chef cookbooks: nginx-multisite and cache...\n\n## Current State Analysis\n...")

Replace the placeholder with your ACTUAL analysis findings. The text parameter must contain the complete migration plan you generated from your repository exploration.