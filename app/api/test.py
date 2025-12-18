"""Test/Sandbox API endpoints for Rule Builder."""
from flask import request, jsonify
from app.api import api_bp
from app.engine import RuleEvaluator


@api_bp.route("/test/rule", methods=["POST"])
def test_rule():
    """
    Test a rule against sample configuration (sandbox mode).
    
    Request body:
    {
        "config": "... config text ...",
        "logic_type": "simple_match",
        "logic_payload": { ... }
    }
    """
    data = request.get_json()
    
    if not data.get("config"):
        return jsonify({"error": "config is required"}), 400
    if not data.get("logic_type"):
        return jsonify({"error": "logic_type is required"}), 400
    if not data.get("logic_payload"):
        return jsonify({"error": "logic_payload is required"}), 400
    
    evaluator = RuleEvaluator()
    result = evaluator.test_rule(
        config=data["config"],
        logic_type=data["logic_type"],
        logic_payload=data["logic_payload"]
    )
    
    return jsonify(result)


@api_bp.route("/test/parse", methods=["POST"])
def test_parse():
    """
    Parse a config and return block structure (for debugging).
    Uses ciscoconfparse2.
    """
    data = request.get_json()
    config = data.get("config", "")
    
    try:
        from ciscoconfparse2 import CiscoConfParse
        parse = CiscoConfParse(config.splitlines())
        
        # Get all parent objects
        parents = []
        for obj in parse.objs:
            if not obj.parent or obj.parent.text == "":
                parents.append({
                    "text": obj.text,
                    "linenum": obj.linenum,
                    "children": [
                        {"text": c.text, "linenum": c.linenum}
                        for c in obj.children
                    ]
                })
        
        return jsonify({
            "success": True,
            "total_lines": len(parse.objs),
            "structure": parents
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })


@api_bp.route("/test/logic-types", methods=["GET"])
def get_logic_types():
    """Get available logic types with descriptions."""
    types = {
        "simple_match": {
            "name": "Simple Match",
            "description": "Text or regex pattern matching",
            "payload_schema": {
                "pattern": {"type": "string", "required": True},
                "match_mode": {"type": "enum", "values": ["must_exist", "must_not_exist"]},
                "is_regex": {"type": "boolean", "default": False},
                "case_insensitive": {"type": "boolean", "default": False}
            }
        },
        "block_match": {
            "name": "Block Context Match",
            "description": "Hierarchical block checking (Cisco/Eltex)",
            "payload_schema": {
                "parent_block_start": {"type": "string", "required": True},
                "exclude_filter": {"type": "string"},
                "child_rules": {"type": "array", "required": True},
                "logic": {"type": "enum", "values": ["ALL", "ANY"], "default": "ALL"}
            }
        },
        "structure_check": {
            "name": "Structure Check",
            "description": "JSON/JMESPath checking for API configs",
            "payload_schema": {
                "path": {"type": "string", "required": True},
                "operator": {"type": "enum", "values": ["eq", "neq", "contains", "gt", "lt", "exists"]},
                "value": {"type": "any"},
                "all_must_match": {"type": "boolean", "default": True}
            }
        }
    }
    
    return jsonify(types)
