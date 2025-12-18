"""Remediation API endpoints."""
from flask import request, jsonify, Response
from app.api import api_bp
from app.services.remediation import remediation_service


@api_bp.route("/remediation/scan/<uuid:scan_id>/playbook", methods=["GET"])
def get_scan_playbook(scan_id):
    """Generate Ansible playbook for all failures in a scan."""
    device_id = request.args.get("device_id")
    
    playbook, tasks = remediation_service.generate_playbook_for_scan(
        str(scan_id), 
        device_id
    )
    
    if not playbook:
        return jsonify({
            "error": "No remediation available", 
            "message": "No failed checks with remediation commands found"
        }), 404
    
    # Return as downloadable YAML or JSON
    format_type = request.args.get("format", "yaml")
    
    if format_type == "yaml":
        return Response(
            playbook,
            mimetype="text/yaml",
            headers={
                "Content-Disposition": f"attachment; filename=remediation_{scan_id}.yml"
            }
        )
    else:
        return jsonify({
            "playbook": playbook,
            "tasks_count": len(tasks),
            "tasks": [
                {
                    "device_id": t.device_id,
                    "rule_id": t.rule_id,
                    "rule_title": t.rule_title,
                    "vendor": t.vendor_code,
                    "commands": t.commands
                }
                for t in tasks
            ]
        })


@api_bp.route("/remediation/rule/<uuid:rule_id>/preview", methods=["GET"])
def preview_rule_remediation(rule_id):
    """Preview remediation for a specific rule."""
    preview = remediation_service.preview_remediation(str(rule_id))
    if "error" in preview:
        return jsonify(preview), 404
    return jsonify(preview)


@api_bp.route("/remediation/rule/<uuid:rule_id>/playbook", methods=["POST"])
def generate_rule_playbook(rule_id):
    """Generate playbook for applying a rule to specified devices."""
    data = request.get_json() or {}
    device_ids = data.get("device_ids", [])
    
    if not device_ids:
        return jsonify({"error": "device_ids required"}), 400
    
    playbook = remediation_service.generate_playbook_for_rule(
        str(rule_id), 
        device_ids
    )
    
    if not playbook:
        return jsonify({
            "error": "No remediation available",
            "message": "Rule has no remediation commands"
        }), 404
    
    format_type = request.args.get("format", "yaml")
    
    if format_type == "yaml":
        return Response(
            playbook,
            mimetype="text/yaml",
            headers={
                "Content-Disposition": f"attachment; filename=rule_{rule_id}_remediation.yml"
            }
        )
    else:
        return jsonify({"playbook": playbook})


@api_bp.route("/remediation/device/<device_id>/playbook", methods=["GET"])
def get_device_playbook(device_id):
    """Get remediation playbook for all failures on a device (latest scan)."""
    from app.models import Scan
    
    # Get latest completed scan
    scan = Scan.query.filter_by(status="completed").order_by(
        Scan.finished_at.desc()
    ).first()
    
    if not scan:
        return jsonify({"error": "No completed scans found"}), 404
    
    playbook, tasks = remediation_service.generate_playbook_for_scan(
        str(scan.id), 
        device_id
    )
    
    if not playbook:
        return jsonify({
            "error": "No remediation needed",
            "message": "Device has no failed checks with remediation"
        }), 404
    
    return Response(
        playbook,
        mimetype="text/yaml",
        headers={
            "Content-Disposition": f"attachment; filename={device_id}_remediation.yml"
        }
    )


@api_bp.route("/remediation/scan/<uuid:scan_id>/execute", methods=["POST"])
def execute_scan_remediation(scan_id):
    """
    Execute remediation playbook on remote Ansible server.
    
    Request body:
    {
        "device_id": "optional - limit to one device",
        "check_mode": true/false (dry-run),
        "executor_config": {
            "type": "awx" | "ssh",
            "host": "ansible.example.com",  # for SSH
            "template_id": 123  # for AWX
        }
    }
    """
    from app.services.ansible_executor import get_ansible_executor
    
    data = request.get_json() or {}
    device_id = data.get("device_id")
    check_mode = data.get("check_mode", True)  # Default to dry-run for safety
    executor_config = data.get("executor_config")
    
    # Generate playbook
    playbook, tasks = remediation_service.generate_playbook_for_scan(
        str(scan_id), 
        device_id
    )
    
    if not playbook:
        return jsonify({
            "error": "No remediation available",
            "message": "No failed checks with remediation commands found"
        }), 404
    
    # Execute
    executor = get_ansible_executor(executor_config)
    result = executor.execute(
        playbook_content=playbook,
        playbook_name=f"scan_{scan_id}_remediation.yml",
        limit=device_id,
        check_mode=check_mode
    )
    
    return jsonify({
        "success": result.success,
        "status": result.status,
        "job_id": result.job_id,
        "url": result.url,
        "output": result.output,
        "error": result.error,
        "tasks_count": len(tasks),
        "check_mode": check_mode
    })


@api_bp.route("/remediation/awx/templates", methods=["GET"])
def list_awx_templates():
    """List available AWX job templates (requires AWX configuration)."""
    from app.services.ansible_executor import AWXExecutor
    import os
    
    config = {
        "url": os.environ.get("AWX_URL", ""),
        "token": os.environ.get("AWX_TOKEN", ""),
    }
    
    if not config["url"] or not config["token"]:
        return jsonify({"error": "AWX not configured"}), 400
    
    try:
        import requests
        response = requests.get(
            f"{config['url']}/api/v2/job_templates/",
            headers={"Authorization": f"Bearer {config['token']}"},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            templates = [
                {"id": t["id"], "name": t["name"], "description": t.get("description", "")}
                for t in data.get("results", [])
            ]
            return jsonify({"templates": templates})
        else:
            return jsonify({"error": f"AWX error: {response.status_code}"}), 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/remediation/awx/execute/<int:template_id>", methods=["POST"])
def execute_awx_template(template_id):
    """
    Execute AWX job template with optional extra vars.
    
    Request body:
    {
        "extra_vars": {"key": "value"},
        "limit": "host1,host2"
    }
    """
    from app.services.ansible_executor import get_ansible_executor
    
    # Force AWX executor
    import os
    config = {
        "type": "awx",
        "url": os.environ.get("AWX_URL", ""),
        "token": os.environ.get("AWX_TOKEN", ""),
    }
    
    if not config["url"] or not config["token"]:
        return jsonify({"error": "AWX not configured"}), 400
    
    data = request.get_json() or {}
    extra_vars = data.get("extra_vars")
    limit = data.get("limit")
    
    executor = get_ansible_executor(config)
    result = executor.execute_job_template(template_id, extra_vars, limit)
    
    return jsonify({
        "success": result.success,
        "job_id": result.job_id,
        "status": result.status,
        "url": result.url,
        "error": result.error
    })


@api_bp.route("/remediation/awx/job/<job_id>/status", methods=["GET"])
def get_awx_job_status(job_id):
    """Get status of AWX job."""
    from app.services.ansible_executor import get_ansible_executor
    import os
    
    config = {
        "type": "awx",
        "url": os.environ.get("AWX_URL", ""),
        "token": os.environ.get("AWX_TOKEN", ""),
    }
    
    executor = get_ansible_executor(config)
    result = executor.get_job_status(job_id)
    
    return jsonify({
        "success": result.success,
        "job_id": result.job_id,
        "status": result.status,
        "url": result.url,
        "error": result.error
    })
