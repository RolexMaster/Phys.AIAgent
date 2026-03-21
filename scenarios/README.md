# Scenarios

Each file is a JSON object with this shape:

```json
{
  "name": "scenario_name",
  "queries": [
    "first query",
    "second query"
  ]
}
```

Default selection in the notebook:

- `SCENARIO_NAME=eots_advanced_commands_en`
- `SCENARIO_FILE=scenarios/<name>.json`

How to switch:

```python
SCENARIO_NAME = os.getenv("SCENARIO_NAME", "eots_intermediate_commands_en")
```

Or set an explicit file:

```python
SCENARIO_FILE = Path("scenarios/template.json")
```

Recommended workflow:

1. Copy `template.json`.
2. Rename it for your scenario.
3. Edit only the `queries` list.
4. Change `SCENARIO_NAME` or `SCENARIO_FILE` in the notebook.
