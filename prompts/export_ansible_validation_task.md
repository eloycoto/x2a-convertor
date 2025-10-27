Fix validation errors for module: {module}

CHEF SOURCE PATH: {chef_path}
ANSIBLE OUTPUT PATH: {ansible_path}

MIGRATION PLAN:
{migration_plan}

CHECKLIST:
<document>
{checklist}
</document>

ERROR REPORT:
{error_report}

{fragment_yaml_hints}

Your task: Fix ALL errors listed in the error report above.

Instructions:
1. Analyze the error report - understand what's failing
2. Read the affected Ansible files to see current state
3. Fix ALL issues in batch:
   - Fix structural issues (role-check errors)
   - Fix lint issues (ansible-lint errors)
   - Consider cross-file dependencies (variables, handlers)
4. Write fixed files using:
   - ansible_write for YAML files (tasks, handlers, defaults, vars, meta)
   - write_file for templates and other files
5. After fixing, optionally re-run tools to verify:
   - ansible_role_check to verify structure
   - ansible_lint to verify syntax

Common fixes:
- Remove playbook syntax from task files (hosts:, tasks: wrappers)
- Use FQCN: ansible.builtin.service NOT service
- Fix YAML quoting issues
- Ensure handlers are defined if referenced
- Ensure variables are defined before use

Work systematically through all errors. Focus on fixing, not just reporting.

When done, provide a summary:
- What errors were found
- What fixes were applied
- Whether all errors are resolved
