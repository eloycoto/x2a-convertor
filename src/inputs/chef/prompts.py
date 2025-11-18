"""Chef LLM prompt factory.

This module creates prompts for analyzing Chef files using LLM.
All prompts are centralized here for easy maintenance and consistency.
"""


class ChefPromptFactory:
    """Factory for creating LLM prompts for Chef analysis.

    All prompts use advanced prompt engineering techniques optimized for
    extracting structured information from Chef code.
    """

    @staticmethod
    def create_attributes_extraction_prompt(file_path: str, file_content: str) -> str:
        """Build prompt for extracting default attributes."""
        return f"""You are extracting DEFAULT attribute values from a Chef attributes file.

FILE PATH: {file_path}

FILE CONTENT:
```ruby
{file_content}
```

TASK:
Extract all `default['...']['...']` assignments and return them as a nested dictionary.

RULES:
1. For simple assignments like `default['redis']['port'] = 6379`, extract as {{"redis": {{"port": 6379}}}}
2. For platform-specific conditionals (case/when), extract the MOST COMMON default value:
   - If `systemd?` is used, assume systemd is available (true)
   - If `platform_family?('debian')`, use the debian value as default
   - If rhel/fedora, use rhel value
3. Skip helper variables (like `shell = '/bin/sh'`) unless they're assigned to default[]
4. For complex values (arrays, hashes), preserve the structure
5. Add notes about platform-specific logic in platform_specific_notes

EXAMPLE:

Input:
```ruby
default['redis']['port'] = 6379
default['redis']['host'] = 'localhost'

default['redis']['job_control'] = if systemd?
                                    'systemd'
                                  else
                                    'initd'
                                  end
```

Output:
```json
{{
  "attributes": {{
    "redis": {{
      "port": 6379,
      "host": "localhost",
      "job_control": "systemd"
    }}
  }},
  "platform_specific_notes": [
    "job_control defaults to 'systemd' if systemd? is true, otherwise 'initd'"
  ]
}}
```

Now extract the attributes from the file above and return JSON.
"""

    @staticmethod
    def create_recipe_analysis_prompt(file_path: str, file_content: str) -> str:
        """Build prompt for recipe execution order analysis."""
        return f"""You are a Chef recipe analyzer. Your task is to extract the EXECUTION ORDER of operations from a Chef recipe file.

CHAIN OF THOUGHT PROCESS:
Step 1: Read through the file and identify all operations
Step 2: Assign sequence numbers based on top-to-bottom execution order
Step 3: Classify each operation by type
Step 4: Extract attributes and parameters for each operation
Step 5: Build nested structures for conditionals and includes
Step 6: Return valid JSON

FILE PATH: {file_path}

FILE CONTENT:
```ruby
{file_content}
```

OPERATION TYPES:
1. include_recipe: Include another recipe
2. attribute_assignment: Set node attributes (node.default['key'] = value)
3. resource: Standard Chef resource (directory, package, service, etc.)
4. custom_resource: LWRP/custom resource invocation
5. conditional: if/unless/case blocks with nested execution_order

FEW-SHOT EXAMPLES:

Example 1 - Simple recipe:
```ruby
include_recipe 'cookbook_a'
node.default['app']['port'] = 8080
directory '/var/app' do
  owner 'root'
end
```

Expected JSON:
```json
{{
  "execution_order": [
    {{
      "seq": 1,
      "type": "include_recipe",
      "recipe_name": "cookbook_a"
    }},
    {{
      "seq": 2,
      "type": "attribute_assignment",
      "attribute_path": "node.default['app']['port']",
      "value": 8080
    }},
    {{
      "seq": 3,
      "type": "resource",
      "resource_type": "directory",
      "name": "/var/app",
      "attributes": {{"owner": "root"}}
    }}
  ]
}}
```

Example 2 - With conditional:
```ruby
unless node['app']['skip_install']
  include_recipe 'app::install'
  package 'nginx'
end
```

Expected JSON:
```json
{{
  "execution_order": [
    {{
      "seq": 1,
      "type": "conditional",
      "condition": "unless node['app']['skip_install']",
      "execution_order": [
        {{
          "seq": 1,
          "type": "include_recipe",
          "recipe_name": "app::install"
        }},
        {{
          "seq": 2,
          "type": "resource",
          "resource_type": "package",
          "name": "nginx",
          "attributes": {{}}
        }}
      ]
    }}
  ]
}}
```

Example 3 - Custom resource:
```ruby
my_custom_resource 'instance1' do
  port 8080
  user 'appuser'
  action [:start, :enable]
end
```

Expected JSON:
```json
{{
  "execution_order": [
    {{
      "seq": 1,
      "type": "custom_resource",
      "resource_type": "my_custom_resource",
      "name": "instance1",
      "attributes": {{
        "port": "8080",
        "user": "appuser",
        "action": ["start", "enable"]
      }}
    }}
  ]
}}
```

CRITICAL REQUIREMENTS:
- Sequence numbers start at 1 and increment
- Preserve Ruby interpolations like "#{{var}}" as-is
- Conditionals have their own nested execution_order
- Each operation must have a "type" field
- Return ONLY valid JSON, no explanations

Now analyze the file above and return the execution_order JSON:
```json
{{
  "execution_order": [

  ]
}}
```"""

    @staticmethod
    def create_provider_analysis_prompt(file_path: str, file_content: str) -> str:
        """Build prompt for provider template/resource analysis."""
        return f"""You are a Chef provider analyzer. Extract what this provider CREATES when invoked.

CHAIN OF THOUGHT:
Step 1: Identify unconditional templates (outside case/when blocks)
Step 2: Identify case/when blocks and templates inside each branch
Step 3: Extract files and resources created
Step 4: Assign when_value to each case branch
Step 5: Return JSON with templates categorized correctly

FILE PATH: {file_path}

FILE CONTENT:
```ruby
{file_content}
```

FEW-SHOT EXAMPLE:

Provider with case/when:
```ruby
template "/etc/app/config.conf" do
  source 'config.erb'
end

case node['app']['init']
when 'systemd'
  template "/lib/systemd/system/app.service" do
    source 'app.service.erb'
  end
when 'initd'
  template "/etc/init.d/app" do
    source 'app.init.erb'
  end
end
```

Expected JSON:
```json
{{
  "unconditional_templates": [
    {{
      "destination": "/etc/app/config.conf",
      "source": "templates/default/config.erb"
    }}
  ],
  "conditionals": [
    {{
      "condition": "node['app']['init']",
      "condition_type": "case",
      "when_value": "systemd",
      "templates": [
        {{
          "destination": "/lib/systemd/system/app.service",
          "source": "templates/default/app.service.erb"
        }}
      ]
    }},
    {{
      "condition": "node['app']['init']",
      "condition_type": "case",
      "when_value": "initd",
      "templates": [
        {{
          "destination": "/etc/init.d/app",
          "source": "templates/default/app.init.erb"
        }}
      ]
    }}
  ]
}}
```

REQUIREMENTS:
- Templates OUTSIDE case/when go in unconditional_templates
- Each when branch creates ONE conditional object
- when_value must be the actual value ("systemd", "initd", etc.), NOT null
- Prefix template sources with "templates/default/"
- Return ONLY valid JSON

Analyze the provider and return JSON:
```json
{{
  "unconditional_templates": [],
  "conditionals": []
}}
```"""
