import os
import json
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_ruby as tsruby
import tree_sitter_json as tsjson

FOLDER = "/home/eloy/dev/upstream/x2ansible/chef-example/cookbooks/nginx-multisite/"

class RubyParser:
    def __init__(self):
        ruby_language = Language(tsruby.language())
        self.parser = Parser(ruby_language)
    
    def parse_file(self, file_path: str):
        """Parse Ruby file and return Chef structure"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            tree = self.parser.parse(content)
            return self._extract_ruby_structure(tree.root_node, content)
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
    
    def _traverse_ruby_node(self, node, content, structure, debug=False):
        """Traverse Ruby AST and extract Chef-specific patterns"""
        match node.type:
            case 'class':
                class_name = self._get_node_text(node.child_by_field_name('name'), content)
                structure.get("classes", []).append({
                    "name": class_name,
                    "line": node.start_point[0] + 1
                })
            
            case 'method':
                method_name = self._get_node_text(node.child_by_field_name('name'), content)
                structure.get("methods", []).append({
                    "name": method_name,
                    "line": node.start_point[0] + 1
                })
            
            case 'call':
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
                    
                    match method_name:
                        case name if name in chef_resources:
                            resource = self._parse_chef_resource(node, content, method_name)
                            structure.get("chef_resources", []).append(resource)
                        
                        case 'include_recipe' | 'require':
                            args = self._extract_string_args(node, content)
                            target_list = structure.get("includes", []) if method_name == 'include_recipe' else structure.get("requires", [])
                            target_list.extend(args)
            
            case 'assignment':
                left = node.child_by_field_name('left')
                if left and left.type in ['constant', 'call']:
                    assignment = self._parse_assignment(node, content)
                    if assignment:
                        structure.get("constants", []).append(assignment)
        
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
            match child.type:
                case 'argument_list':
                    for arg in child.children:
                        if arg.type == 'string' and resource.get("name") is None:
                            resource["name"] = self._get_node_text(arg, content).strip('"\'')
                
                case 'block' | 'do_block':
                    resource["block_content"] = self._get_node_text(child, content)
                    resource["attributes"] = self._parse_chef_block(child, content)
        
        return resource
    
    def _parse_chef_block(self, block_node, content):
        """Parse Chef resource block to extract attributes"""
        attributes = {}
        
        def parse_node_for_attributes(node):
            match node.type:
                case 'call':
                    method_node = node.child_by_field_name('method')
                    if method_node:
                        attr_name = self._get_node_text(method_node, content)
                        if attr_name in ['action', 'notifies', 'subscribes', 'only_if', 'not_if', 
                                       'user', 'group', 'mode', 'owner', 'source', 'variables',
                                       'cookbook', 'template', 'path', 'content', 'command', 'supports']:
                            attr_value = self._extract_attribute_value(node, content)
                            attributes[attr_name] = attr_value
                
                case 'assignment':
                    left = node.child_by_field_name('left')
                    right = node.child_by_field_name('right')
                    if left and right:
                        attr_name = self._get_node_text(left, content)
                        attr_value = self._get_node_text(right, content)
                        attributes[attr_name] = attr_value
            
            for child in node.children:
                parse_node_for_attributes(child)
        
        parse_node_for_attributes(block_node)
        return attributes
    
    def _extract_attribute_value(self, node, content):
        """Extract the value of a Chef resource attribute - simplified"""
        for child in node.children:
            if child.type == 'argument_list':
                # Just grab the raw text - much simpler
                arg_text = self._get_node_text(child, content)
                return arg_text.strip('() ')
        
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
        
        return {
            "name": var_name,
            "value": var_value,
            "type": "chef_attribute" if var_name.startswith(('default[', 'node[')) else "variable",
            "line": node.start_point[0] + 1
        }
    
    def _get_node_text(self, node, content):
        """Get text content of a node"""
        if node is None:
            return ""
        return content[node.start_byte:node.end_byte].decode('utf-8')


class JsonParser:
    def __init__(self):
        json_language = Language(tsjson.language())
        self.parser = Parser(json_language)
    
    def parse_file(self, file_path: str):
        """Parse JSON file and return structure"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            tree = self.parser.parse(content)
            return self._extract_json_structure(tree.root_node, content)
        except Exception as e:
            return {"error": f"Failed to parse {file_path}: {str(e)}"}
    
    def _extract_json_structure(self, node, content):
        """Extract structure from JSON AST"""
        structure = {
            "type": "json_file",
            "keys": [],
            "structure": {}
        }
        
        self._traverse_json_node(node, content, structure)
        return structure
    
    def _traverse_json_node(self, node, content, structure):
        """Traverse JSON AST and extract keys"""
        match node.type:
            case 'pair':
                key_node = node.child_by_field_name('key')
                if key_node:
                    key = self._get_node_text(key_node, content).strip('"')
                    structure.get("keys", []).append(key)
        
        for child in node.children:
            self._traverse_json_node(child, content, structure)
    
    def _get_node_text(self, node, content):
        """Get text content of a node"""
        if node is None:
            return ""
        return content[node.start_byte:node.end_byte].decode('utf-8')


class TreeSitterAnalyzer:
    def __init__(self):
        self.ruby_parser = RubyParser()
        self.json_parser = JsonParser()
    
    def parse_file(self, file_path: str):
        """Parse a file using appropriate parser"""
        match Path(file_path).suffix:
            case '.rb':
                return self.ruby_parser.parse_file(file_path)
            case '.json':
                return self.json_parser.parse_file(file_path)
            case _:
                return {"error": f"Unsupported file type: {file_path}"}
    
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
                for const in analysis.get("constants", []):
                    print(f"    • {const.get('name')} = {const.get('value', 'N/A')}")
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
                    print(f"      • {resource.get('type')}")
                    if resource.get('name'):
                        name = resource.get('name')
                        if '#{' in name:  # Template variable in name
                            print(f"        name: {name}")
                    if resource.get('attributes'):
                        key_attrs = [k for k in resource.get('attributes', {}).keys() if k in ['action', 'source', 'mode', 'variables']]
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
