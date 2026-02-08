"""Devices API endpoints."""
from flask import Blueprint, request, jsonify
from datetime import datetime
from app.extensions import db
from app.models import Device, DeviceGroup, Policy, Vendor

devices_bp = Blueprint("devices", __name__)


@devices_bp.route("", methods=["GET"])
def list_devices():
    """List all devices with optional filters."""
    query = Device.query
    
    # Filters
    if request.args.get("vendor_code"):
        query = query.filter_by(vendor_code=request.args.get("vendor_code"))
    if request.args.get("group_id"):
        query = query.filter_by(group_id=request.args.get("group_id"))
    if request.args.get("is_active"):
        query = query.filter_by(is_active=request.args.get("is_active").lower() == "true")
    if request.args.get("search"):
        search = f"%{request.args.get('search')}%"
        query = query.filter(
            db.or_(Device.hostname.ilike(search), Device.ip_address.ilike(search))
        )
    
    devices = query.order_by(Device.hostname).all()
    return jsonify([d.to_dict() for d in devices])


@devices_bp.route("", methods=["POST"])
def create_device():
    """Create a new device manually."""
    data = request.get_json()
    
    if not data.get("hostname"):
        return jsonify({"error": "Hostname is required"}), 400
    
    # Check if vendor exists
    if data.get("vendor_code") and not Vendor.query.get(data["vendor_code"]):
        return jsonify({"error": f"Vendor '{data['vendor_code']}' not found"}), 400
    
    device = Device(
        hostname=data["hostname"],
        ip_address=data.get("ip_address"),
        vendor_code=data.get("vendor_code"),
        group_id=data.get("group_id"),
        location=data.get("location"),
        os_version=data.get("os_version"),
        hardware=data.get("hardware"),
        extra_data=data.get("extra_data", {}),
        is_active=data.get("is_active", True)
    )
    
    # Assign policies
    if data.get("policy_ids"):
        policies = Policy.query.filter(Policy.id.in_(data["policy_ids"])).all()
        device.policies = policies
    
    db.session.add(device)
    db.session.commit()
    
    return jsonify(device.to_dict()), 201


@devices_bp.route("/<uuid:device_id>", methods=["GET"])
def get_device(device_id):
    """Get a single device."""
    device = Device.query.get_or_404(device_id)
    return jsonify(device.to_dict())


@devices_bp.route("/<uuid:device_id>", methods=["PUT"])
def update_device(device_id):
    """Update a device."""
    device = Device.query.get_or_404(device_id)
    data = request.get_json()
    
    if "hostname" in data:
        device.hostname = data["hostname"]
    if "ip_address" in data:
        device.ip_address = data["ip_address"]
    if "vendor_code" in data:
        if data["vendor_code"] and not Vendor.query.get(data["vendor_code"]):
            return jsonify({"error": f"Vendor '{data['vendor_code']}' not found"}), 400
        device.vendor_code = data["vendor_code"]
    if "group_id" in data:
        device.group_id = data["group_id"]
    if "location" in data:
        device.location = data["location"]
    if "os_version" in data:
        device.os_version = data["os_version"]
    if "hardware" in data:
        device.hardware = data["hardware"]
    if "extra_data" in data:
        device.extra_data = data["extra_data"]
    if "is_active" in data:
        device.is_active = data["is_active"]
    if "policy_ids" in data:
        policies = Policy.query.filter(Policy.id.in_(data["policy_ids"])).all()
        device.policies = policies
    
    db.session.commit()
    return jsonify(device.to_dict())


@devices_bp.route("/<uuid:device_id>", methods=["DELETE"])
def delete_device(device_id):
    """Delete a device."""
    device = Device.query.get_or_404(device_id)
    db.session.delete(device)
    db.session.commit()
    return "", 204


@devices_bp.route("/sync", methods=["POST"])
def sync_devices():
    """Sync devices from all active inventory sources."""
    from app.models import InventorySource
    from app.services.inventory_sync import InventorySyncService
    
    sources = InventorySource.query.filter_by(is_active=True).all()
    service = InventorySyncService()
    
    total_created = 0
    total_updated = 0
    total_deactivated = 0
    errors = []
    
    for source in sources:
        try:
            result = service.sync(source, trigger="api")
            total_created += result.created
            total_updated += result.updated
            total_deactivated += result.deactivated
            errors.extend(result.errors)
        except Exception as e:
            errors.append(f"{source.name}: {str(e)}")
    
    return jsonify({
        "success": len(errors) == 0,
        "created": total_created,
        "updated": total_updated,
        "deactivated": total_deactivated,
        "errors": errors
    })


@devices_bp.route("/import-csv", methods=["POST"])
def import_csv():
    """Import devices from CSV data."""
    data = request.get_json()
    csv_data = data.get("csv", "")
    
    if not csv_data:
        return jsonify({"error": "No CSV data provided"}), 400
    
    lines = [l.strip() for l in csv_data.strip().split("\n") if l.strip()]
    if not lines:
        return jsonify({"error": "Empty CSV"}), 400
    
    # Parse header
    header = [h.strip().lower() for h in lines[0].split(",")]
    required = {"hostname"}
    if not required.issubset(set(header)):
        return jsonify({"error": "CSV must have 'hostname' column"}), 400
    
    created = 0
    updated = 0
    
    for line in lines[1:]:
        values = [v.strip() for v in line.split(",")]
        if len(values) != len(header):
            continue
        
        row = dict(zip(header, values))
        hostname = row.get("hostname")
        if not hostname:
            continue
        
        # Find or create
        device = Device.query.filter_by(hostname=hostname).first()
        if device:
            # Update
            if "ip_address" in row or "ip" in row:
                device.ip_address = row.get("ip_address") or row.get("ip")
            if "vendor_code" in row or "vendor" in row:
                device.vendor_code = row.get("vendor_code") or row.get("vendor")
            if "os_version" in row or "os" in row or "version" in row:
                device.os_version = row.get("os_version") or row.get("os") or row.get("version")
            if "hardware" in row or "hw" in row:
                device.hardware = row.get("hardware") or row.get("hw")
            if "location" in row:
                device.location = row.get("location")
            updated += 1
        else:
            # Create
            device = Device(
                hostname=hostname,
                ip_address=row.get("ip_address") or row.get("ip"),
                vendor_code=row.get("vendor_code") or row.get("vendor"),
                os_version=row.get("os_version") or row.get("os") or row.get("version"),
                hardware=row.get("hardware") or row.get("hw"),
                location=row.get("location")
            )
            db.session.add(device)
            created += 1
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "created": created,
        "updated": updated
    })
