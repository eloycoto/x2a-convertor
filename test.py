import os
import json
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_ruby as tsruby
import tree_sitter_json as tsjson

FOLDER = "/home/eloy/dev/upstream/x2ansible/chef-example/cookbooks/nginx-multisite/"

class TreeSitterAnalyzer:
    def __init__(self):
        self.ruby_language = Language(tsruby.language())
        self.json_language = Language(tsjson.language())
        self.ruby_parser = Parser(self.ruby_language)
        self.json_parser = Parser(self.json_language)
    
    def parse_file(self, file_path: str):
        """Parse a file and return its AST structure"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            if file_path.endswith('.rb'):
                tree = self.ruby_parser.parse(content)
                return self._extract_ruby_structure(tree.root_node, content)
            elif file_path.endswith('.json'):
                tree = self.json_parser.parse(content)
                return self._extract_json_structure(tree.root_node, content)
            else:
                return {"error": f"Unsupported file type: {file_path}"}
        except Exception as e:
            return {"error": f"Failed to parse {file_path}: {str(e)}"}
    
    def _extract_ruby_structure(self, node, content):
        """Extract meaningful structure from Ruby AST"""
        structure = {
            "type": "ruby_file",
            "classes": [],
            "methods": [],
            "constants": [],
            "includes": [],
            "requires": [],
            "chef_resources": []
        }
        
        self._traverse_ruby_node(node, content, structure, debug=False)
        return structure
    
    def _extract_json_structure(self, node, content):
        """Extract structure from JSON AST"""
        structure = {
            "type": "json_file",
            "keys": [],
            "structure": {}
        }
        
        self._traverse_json_node(node, content, structure)
        return structure
    
    def _traverse_ruby_node(self, node, content, structure, debug=False):
        """Traverse Ruby AST and extract Chef-specific patterns"""
        if debug and node.type == 'call':
            method_node = node.child_by_field_name('method')
            if method_node:
                method_name = self._get_node_text(method_node, content)
                print(f"DEBUG: Found call to '{method_name}' at line {node.start_point[0] + 1}")
        
        if node.type == 'class':
            class_name = self._get_node_text(node.child_by_field_name('name'), content)
            structure["classes"].append({
                "name": class_name,
                "line": node.start_point[0] + 1
            })
        
        elif node.type == 'method':
            method_name = self._get_node_text(node.child_by_field_name('name'), content)
            structure["methods"].append({
                "name": method_name,
                "line": node.start_point[0] + 1
            })
        
        elif node.type == 'call':
            method_node = node.child_by_field_name('method')
            if method_node:
                method_name = self._get_node_text(method_node, content)
                
                # Chef-specific resource detection
                chef_resources = [
                    'package', 'service', 'file', 'template', 'cookbook_file',
                    'directory', 'user', 'group', 'execute', 'script', 'cron',
                    'mount', 'route', 'apt_package', 'yum_package', 'gem_package',
                    'remote_file', 'link', 'ruby_block', 'bash', 'powershell_script'
                ]
                
                if method_name in chef_resources:
                    resource = self._parse_chef_resource(node, content, method_name)
                    structure["chef_resources"].append(resource)
                
                # Include/require detection
                elif method_name in ['include_recipe', 'require']:
                    args = self._extract_string_args(node, content)
                    if method_name == 'include_recipe':
                        structure["includes"].extend(args)
                    else:
                        structure["requires"].extend(args)
        
        elif node.type == 'assignment':
            left = node.child_by_field_name('left')
            if left and left.type in ['constant', 'call']:
                assignment = self._parse_assignment(node, content)
                if assignment:
                    structure["constants"].append(assignment)
        
        # Recursively traverse children
        for child in node.children:
            self._traverse_ruby_node(child, content, structure, debug)
    
    def _parse_chef_resource(self, node, content, resource_type):
        """Parse a Chef resource with its block and attributes"""
        resource = {
            "type": resource_type,
            "name": None,
            "attributes": {},
            "line": node.start_point[0] + 1,
            "block_content": None
        }
        
        # Extract resource name from arguments
        for child in node.children:
            if child.type == 'argument_list':
                for arg in child.children:
                    if arg.type == 'string':
                        if resource["name"] is None:
                            resource["name"] = self._get_node_text(arg, content).strip('"\'')
            elif child.type in ['block', 'do_block']:
                # Parse the resource block for Chef attributes
                resource["block_content"] = self._get_node_text(child, content)
                resource["attributes"] = self._parse_chef_block(child, content)
        
        return resource
    
    def _parse_chef_block(self, block_node, content):
        """Parse Chef resource block to extract attributes like action, notifies, etc."""
        attributes = {}
        
        def parse_node_for_attributes(node):
            if node.type == 'call':
                method_node = node.child_by_field_name('method')
                if method_node:
                    attr_name = self._get_node_text(method_node, content)
                    
                    # Common Chef resource attributes
                    if attr_name in ['action', 'notifies', 'subscribes', 'only_if', 'not_if', 
                                   'user', 'group', 'mode', 'owner', 'source', 'variables',
                                   'cookbook', 'template', 'path', 'content', 'command', 'supports']:
                        
                        attr_value = self._extract_attribute_value(node, content)
                        attributes[attr_name] = attr_value
                        
            elif node.type == 'assignment':
                # Handle assignments within resource blocks
                left = node.child_by_field_name('left')
                right = node.child_by_field_name('right')
                if left and right:
                    attr_name = self._get_node_text(left, content)
                    attr_value = self._get_node_text(right, content)
                    attributes[attr_name] = attr_value
            
            # Recursively parse children
            for child in node.children:
                parse_node_for_attributes(child)
        
        # Start parsing from the block node
        parse_node_for_attributes(block_node)
        
        return attributes
    
    def _extract_attribute_value(self, node, content):
        """Extract the value of a Chef resource attribute"""
        # Look for argument list
        for child in node.children:
            if child.type == 'argument_list':
                values = []
                for arg in child.children:
                    if arg.type == 'string':
                        values.append(self._get_node_text(arg, content).strip('"\''))
                    elif arg.type in ['symbol', 'simple_symbol']:
                        values.append(self._get_node_text(arg, content))
                    elif arg.type == 'array':
                        # Handle arrays like action [:enable, :start]
                        array_values = []
                        for array_child in arg.children:
                            if array_child.type in ['string', 'symbol', 'simple_symbol']:
                                val = self._get_node_text(array_child, content).strip('":')
                                array_values.append(val)
                        values.append(array_values)
                    elif arg.type == 'hash':
                        # Handle hash values like supports restart: true
                        hash_text = self._get_node_text(arg, content)
                        values.append(f"hash: {hash_text}")
                    elif arg.type not in [',']:  # Skip commas
                        # Handle other types like booleans, numbers
                        val = self._get_node_text(arg, content)
                        if val not in [',', ' ']:
                            values.append(val)
                
                return values[0] if len(values) == 1 else values
        
        return None
    
    def _extract_string_args(self, node, content):
        """Extract string arguments from a method call"""
        args = []
        for child in node.children:
            if child.type == 'argument_list':
                for arg in child.children:
                    if arg.type == 'string':
                        args.append(self._get_node_text(arg, content).strip('"\''))
        return args
    
    def _parse_assignment(self, node, content):
        """Parse variable assignments, especially Chef attributes"""
        left = node.child_by_field_name('left')
        right = node.child_by_field_name('right')
        
        if not left or not right:
            return None
            
        var_name = self._get_node_text(left, content)
        var_value = self._get_node_text(right, content)
        
        # Always return assignments - let the caller decide if they're Chef attributes
        return {
            "name": var_name,
            "value": var_value,
            "type": "chef_attribute" if var_name.startswith('default[') or var_name.startswith('node[') else "variable",
            "line": node.start_point[0] + 1
        }
    
    def _traverse_json_node(self, node, content, structure):
        """Traverse JSON AST and extract keys"""
        if node.type == 'pair':
            key_node = node.child_by_field_name('key')
            if key_node:
                key = self._get_node_text(key_node, content).strip('"')
                structure["keys"].append(key)
        
        # Recursively traverse children
        for child in node.children:
            self._traverse_json_node(child, content, structure)
    
    def _get_node_text(self, node, content):
        """Get text content of a node"""
        if node is None:
            return ""
        return content[node.start_byte:node.end_byte].decode('utf-8')
    
    def analyze_directory(self, directory_path: str):
        """Analyze all Ruby and JSON files in a directory"""
        results = {}
        path = Path(directory_path)
        
        for file_path in path.rglob('*.rb'):
            results[str(file_path)] = self.parse_file(str(file_path))
        
        for file_path in path.rglob('*.json'):
            results[str(file_path)] = self.parse_file(str(file_path))
        
        return results
    

def main():
    os.chdir(FOLDER)
    
    analyzer = TreeSitterAnalyzer()
    
    # Analyze the current directory
    results = analyzer.analyze_directory(".")
    
    print("Chef Cookbook Structure Analysis")
    print("=" * 40)
    
    # Find all template files
    template_files = []
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith('.erb'):
                template_files.append(os.path.join(root, file))
    
    # Analyze each file type
    for file_path, analysis in results.items():
        if "error" in analysis:
            continue
            
        rel_path = file_path if not file_path.startswith('./') else file_path[2:]
        
        if rel_path.startswith('attributes/'):
            print(f"\n{rel_path}:")
            if analysis.get("constants"):
                print("  Variables assigned:")
                for const in analysis["constants"]:
                    print(f"    • {const['name']} = {const.get('value', 'N/A')}")
            else:
                # Debug: Let's see what we're actually detecting
                print("  Variables assigned:")
                # Read the file directly to extract Chef attributes
                try:
                    with open(rel_path, 'r') as f:
                        lines = f.readlines()
                    for i, line in enumerate(lines, 1):
                        line = line.strip()
                        if line.startswith('default[') and '=' in line:
                            parts = line.split(' = ', 1)
                            if len(parts) == 2:
                                attr_name = parts[0].strip()
                                attr_value = parts[1].strip()
                                # Truncate long values
                                if len(attr_value) > 50:
                                    attr_value = attr_value[:47] + "..."
                                print(f"    • {attr_name} = {attr_value}")
                except Exception as e:
                    print(f"  (Error reading file: {e})")
                
        elif rel_path.startswith('recipes/'):
            recipe_name = Path(rel_path).stem
            print(f"\n{rel_path}:")
            
            # Show includes
            includes = analysis.get("includes", [])
            if includes:
                print("  Include the following recipes:")
                for include in includes:
                    # Convert include names to file paths
                    recipe_file = include.replace('::', '/').replace('nginx-multisite/', '') + '.rb'
                    print(f"    • {recipe_file}")
            
            # Show resources
            resources = analysis.get("chef_resources", [])
            if resources:
                print("  Resources:")
                
                # Check if there are any .each loops in the file
                file_content = ""
                try:
                    with open(rel_path, 'r') as f:
                        file_content = f.read()
                except:
                    pass
                
                if '.each do |' in file_content:
                    # Extract the loop variable
                    import re
                    loop_match = re.search(r"(\w+\[.*?\])\.each do \|([^|]+)\|", file_content)
                    if loop_match:
                        loop_var = loop_match.group(1)
                        iterator_vars = loop_match.group(2)
                        print(f"    Loop: {loop_var}.each do |{iterator_vars}|")
                
                for resource in resources:
                    print(f"      • {resource['type']}")
                    if resource.get('name'):
                        name = resource['name']
                        if '#{' in name:  # Template variable in name
                            print(f"        name: {name}")
                    if resource.get('attributes'):
                        key_attrs = [k for k in resource['attributes'].keys() if k in ['action', 'source', 'mode', 'variables']]
                        if key_attrs:
                            print(f"        ({', '.join(key_attrs)})")
                            
        elif rel_path.startswith('resources/'):
            print(f"\n{rel_path}:")
            print("  Custom resource definition")
            
        elif rel_path == 'metadata.rb':
            print(f"\n{rel_path}:")
            print("  Cookbook metadata")
    
    # Show template files
    if template_files:
        print(f"\nTemplate files:")
        for template in sorted(template_files):
            print(f"  • {template}")
    
    print(f"\n🎯 Simple tree structure for LLM analysis complete!")

if __name__ == "__main__":
    main()
