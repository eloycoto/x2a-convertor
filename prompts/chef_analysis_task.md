**Analyze the Chef cookbook at path: {path}**
**User requirements: {user_message}**

# CRITICAL: STRUCTURED ANALYSIS DATA (USE THIS AS YOUR SOURCE OF TRUTH)

The following structured analysis has ALREADY been performed on ALL cookbook files.
You MUST use this data. Do NOT hallucinate or invent files that aren't listed here.

```
{structured_analysis}
```

**VALIDATION RULES:**
- File Structure: List ONLY files shown in "Recipes Analyzed", "Providers Analyzed", "Attributes Analyzed" sections above
- Module Explanation: Use the execution order shown in the structured analysis for each recipe
- Custom Resources: Reference the provider paths shown in the analysis
- Templates: Use the template paths shown in provider analysis (unconditional/conditional templates)
- DO NOT invent recipes, providers, or templates not shown in the structured analysis

**CRITICAL: EXPANDING ITERATIONS**
When recipes contain iterations or loops:
1. **Identify iteration patterns**: Look for `.each`, loops, or repeated resources in the structured analysis
2. **Cross-reference with Attributes Analyzed**: Find collection attributes (dicts with keys)
3. **Extract ALL keys**: List every single key from the collection attribute
4. **Expand explicitly**: DO NOT write "for each X" - name every item

**Generic Example:**
Recipe execution shows: "Iteration" or "loop over collection"
Attributes show: `collection_name: dict with 3 keys: ['keyA', 'keyB', 'keyC']`

YOU MUST WRITE:
- Iterations: Runs 3 times for items: **keyA**, **keyB**, **keyC**
  - keyA: [details from attribute values]
  - keyB: [details from attribute values]
  - keyC: [details from attribute values]

NEVER WRITE: "For each item", "Configures multiple X", "Iterates over Y"
If you write "for each", you FAILED. List all items explicitly by their actual names.

---

**Directory listing for {path}:**
```
{directory_listing}
```

**Tree-sitter structural analysis:**
{tree_sitter_report}

**INSTRUCTIONS:**
1. **PRIMARY SOURCE**: Use the structured analysis data above - it contains the complete execution flow
2. Use the `read_file` tool ONLY if you need to see specific file content not in the structured analysis
3. Use the `file_search` tool to find specific patterns if needed
4. Use the `list_directory` tool if you need to explore subdirectories
5. **CRITICAL**: Cross-check your migration plan against the structured analysis - every file you mention MUST be in the analysis
6. Provide your final response as a detailed text migration plan (NOT as a tool call)

Follow the MANDATORY ANALYSIS STEPS from the system prompt and write the migration plan using the template format provided in the system prompt.
