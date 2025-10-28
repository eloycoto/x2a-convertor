Fix validation errors for module: {module}

CHEF SOURCE PATH: {chef_path}
ANSIBLE OUTPUT PATH: {ansible_path}

HIGH-LEVEL MIGRATION PLAN:
{high_level_migration_plan}

MODULE MIGRATION PLAN:
{migration_plan}

CHECKLIST:
<document>
{checklist}
</document>

ERROR REPORT:
{error_report}

{fragment_yaml_hints}

Your task: Fix ALL errors listed in the error report above.

Step-by-step workflow:
1. Read the ERROR REPORT carefully and identify which files have errors
2. For EACH file with errors:
   a. Read the current file content using read_file
   b. Identify the specific error (schema, syntax, missing handlers, etc.)
   c. Fix the error following the examples in the hints above
   d. Write the corrected file using ansible_write (for YAML) or write_file (for templates)
3. After fixing ALL files, optionally verify with ansible_lint and ansible_role_check

IMPORTANT - When you see [schema] errors about "not of type 'array'", this means:
- The file has playbook syntax (with tasks: wrapper at the top level)
- You MUST remove the tasks: wrapper entirely
- The file should be a direct list of tasks starting with "- name:"
- See the fragment_yaml_hints above for exact example

Instructions:
1. Analyze the error report - identify ALL files with errors
2. For undefined variables or missing loops:
   - Compare with source files to understand the ORIGINAL INTENT
   - If source iterates, ADD a loop in Ansible
   - If source uses variables, ADD variable definitions
3. Fix ALL issues systematically:
   - Fix structural issues (role-check errors)
   - Fix lint issues (ansible-lint errors)
   - Consider cross-file dependencies (variables, handlers)
4. Write fixed files using:
   - ansible_write for YAML files (tasks, handlers, defaults, vars, meta)
   - write_file for templates and other files
5. After fixing ALL files, optionally re-run tools to verify:
   - ansible_role_check to verify structure
   - ansible_lint to verify syntax

Common fixes:
- Remove playbook syntax from task files (hosts:, tasks: wrappers)
- Use FQCN: ansible.builtin.service NOT service
- Fix YAML quoting issues
- ADD missing handlers that are referenced by notify
- ADD missing variables that are used in tasks
- ADD missing loops when source code iterates

CRITICAL - When fixing "undefined variable" errors:
1. Check source files - does it iterate over a collection?
2. If YES: ADD the loop in Ansible (loop: or with_items:), don't remove variables
3. If NO: ADD variable definitions in defaults/main.yml or vars/main.yml

CRITICAL - When fixing "handler not found" errors:
1. ADD the handler to handlers/main.yml
2. NEVER remove the notify statement from tasks

CRITICAL - PREVENT REGRESSIONS:
1. BEFORE modifying a file, READ IT FIRST to understand what's already working
2. If a file has a loop (loop: or with_items:), DO NOT REMOVE IT unless the error specifically says to
3. If fixing ansible-lint errors (like [no-changed-when]), ADD fixes WITHOUT changing logic
4. NEVER simplify or reduce functionality to fix lint errors
5. Fix syntax/lint issues while PRESERVING all loops, variables, and logic

Examples of WRONG fixes (regressions):
- Removing a loop to fix a lint error → WRONG, add changed_when instead
- Replacing dynamic variables with hardcoded values → WRONG, keep the variables
- Simplifying multi-item tasks to single-item → WRONG, keep the iteration

The goal is to maintain 100% functional equivalence with source code.
Work systematically through all errors. Focus on fixing, not just reporting.
DO NOT introduce regressions by removing working functionality.

When done, provide a summary:
- What errors were found
- What fixes were applied
- Whether all errors are resolved
