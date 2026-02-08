"""Rule import/export API — pack rules as JSON and import them."""
import json
import logging
from flask import request, jsonify

from app.api import api_bp
from app.extensions import db
from app.models.rule import Rule
from app.models.policy import Policy
from app.models.vendor import Vendor

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Export
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_bp.route("/rules/export", methods=["GET"])
def export_rules():
    """Export rules as JSON pack.
    
    Query params:
        policy_id  - filter by policy (optional)
        vendor     - filter by vendor_code (optional)
        format     - 'json' (default) or 'compact'
    """
    policy_id = request.args.get("policy_id")
    vendor = request.args.get("vendor")
    fmt = request.args.get("format", "json")
    
    query = Rule.query.filter_by(is_active=True)
    
    if policy_id:
        query = query.filter_by(policy_id=policy_id)
    if vendor:
        query = query.filter_by(vendor_code=vendor)
    
    rules = query.all()
    
    # Build export pack
    pack = {
        "version": "1.0",
        "exported_at": db.func.now(),
        "count": len(rules),
        "rules": [],
    }
    
    for rule in rules:
        entry = {
            "title": rule.title,
            "description": rule.description,
            "remediation": rule.remediation,
            "vendor_code": rule.vendor_code,
            "logic_type": rule.logic_type,
            "logic_payload": rule.logic_payload,
            "severity": rule.severity,
            "applicability": rule.applicability,
        }
        if fmt != "compact":
            entry["policy_name"] = rule.policy.name if rule.policy else None
        pack["rules"].append(entry)
    
    from datetime import datetime
    pack["exported_at"] = datetime.utcnow().isoformat()
    
    return jsonify(pack)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Import
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_bp.route("/rules/import", methods=["POST"])
def import_rules():
    """Import rules from JSON pack.
    
    JSON body:
    {
        "rules": [...],         // array of rule objects
        "policy_id": "...",     // target policy UUID (required)
        "mode": "merge",        // "merge" (skip duplicates) or "replace" (delete existing + import)
        "dry_run": false        // if true, validate only
    }
    
    Each rule object:
    {
        "title": "...",
        "vendor_code": "cisco_ios",
        "logic_type": "simple_match",
        "logic_payload": {...},
        "severity": "high",
        "description": "...",
        "remediation": "...",
        "applicability": {...}   // optional
    }
    """
    data = request.get_json(force=True)
    rules_data = data.get("rules", [])
    policy_id = data.get("policy_id")
    mode = data.get("mode", "merge")
    dry_run = data.get("dry_run", False)
    
    if not policy_id:
        return jsonify({"error": "policy_id is required"}), 400
    
    # Validate policy exists
    policy = Policy.query.get(policy_id)
    if not policy:
        return jsonify({"error": f"Policy {policy_id} not found"}), 404
    
    # Validate vendor codes
    valid_vendors = {v.code for v in Vendor.query.all()}
    
    results = {
        "total": len(rules_data),
        "imported": 0,
        "skipped": 0,
        "errors": [],
    }
    
    # In replace mode, delete existing rules for this policy
    if mode == "replace" and not dry_run:
        deleted = Rule.query.filter_by(policy_id=policy_id).delete()
        results["deleted"] = deleted
    
    for i, rule_data in enumerate(rules_data):
        title = rule_data.get("title", "").strip()
        vendor_code = rule_data.get("vendor_code", "")
        logic_type = rule_data.get("logic_type", "")
        logic_payload = rule_data.get("logic_payload")
        
        # Validate required fields
        if not title:
            results["errors"].append(f"[{i}] missing title")
            continue
        if not logic_type:
            results["errors"].append(f"[{i}] missing logic_type")
            continue
        if not logic_payload:
            results["errors"].append(f"[{i}] missing logic_payload")
            continue
        if not vendor_code:
            results["errors"].append(f"[{i}] missing vendor_code (required)")
            continue
        if vendor_code not in valid_vendors:
            results["errors"].append(f"[{i}] unknown vendor: {vendor_code}")
            continue
        
        # Check for duplicates (merge mode)
        if mode == "merge":
            existing = Rule.query.filter_by(
                policy_id=policy_id,
                title=title,
                vendor_code=vendor_code,
            ).first()
            if existing:
                results["skipped"] += 1
                continue
        
        if dry_run:
            results["imported"] += 1
            continue
        
        rule = Rule(
            policy_id=policy_id,
            title=title,
            vendor_code=vendor_code,
            logic_type=logic_type,
            logic_payload=logic_payload,
            severity=rule_data.get("severity", "medium"),
            description=rule_data.get("description"),
            remediation=rule_data.get("remediation"),
            applicability=rule_data.get("applicability"),
        )
        db.session.add(rule)
        results["imported"] += 1
    
    if not dry_run:
        db.session.commit()
    
    results["dry_run"] = dry_run
    return jsonify(results), 200 if not results["errors"] else 207


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Provider capabilities info
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_bp.route("/capabilities", methods=["GET"])
def get_capabilities():
    """Return platform capabilities for UI/integrations."""
    from app.engine.evaluator import RuleEvaluator
    from app.providers.ssh import SSHProvider
    
    return jsonify({
        "logic_types": sorted(set(RuleEvaluator.CHECKERS.keys())),
        "ssh_device_types": sorted(SSHProvider.DEVICE_TYPE_MAP.keys()),
        "provider_types": [
            {
                "type": "ssh_direct",
                "name": "SSH (Netmiko)",
                "description": "Direct SSH to network devices",
                "supports": "CLI configs (text)",
            },
            {
                "type": "api_rest",
                "name": "REST API (Generic)",
                "description": "Generic REST API for JSON/XML endpoints",
                "supports": "JSON/text configs",
            },
            {
                "type": "checkpoint",
                "name": "CheckPoint SmartConsole",
                "description": "CheckPoint Management API (R80+)",
                "supports": "JSON policies, rulebases, objects",
            },
            {
                "type": "fortigate",
                "name": "FortiGate REST API",
                "description": "FortiOS CMDB API (6.x/7.x)",
                "supports": "JSON configs, policies, profiles",
            },
            {
                "type": "usergate",
                "name": "UserGate UTM API",
                "description": "UserGate REST API (v5/v6/v7)",
                "supports": "JSON rules, zones, profiles",
            },
            {
                "type": "paloalto",
                "name": "Palo Alto PAN-OS API",
                "description": "PAN-OS XML/REST API",
                "supports": "XML/JSON policies, objects, profiles",
            },
            {
                "type": "netconf",
                "name": "NETCONF/YANG",
                "description": "NETCONF protocol via ncclient",
                "supports": "XML configs (Juniper, Cisco, Huawei, Nokia)",
            },
            {
                "type": "snmp",
                "name": "SNMP",
                "description": "SNMPv2c/v3 polling",
                "supports": "OID values, walks",
            },
            {
                "type": "gitlab",
                "name": "GitLab",
                "description": "Configs stored in Git (Oxidized, RANCID)",
                "supports": "Any text format from Git repos",
            },
            {
                "type": "local",
                "name": "Local / NFS",
                "description": "Files on local filesystem",
                "supports": "Any file format",
            },
        ],
    })
