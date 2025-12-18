"""Export API endpoints."""
from flask import request, jsonify, Response
from app.api import api_bp
from app.services.exports import export_service


@api_bp.route("/export/scan/<uuid:scan_id>/csv", methods=["GET"])
def export_scan_csv(scan_id):
    """Export scan results to CSV."""
    try:
        csv_data = export_service.export_scan_csv(str(scan_id))
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=scan_{scan_id}.csv"}
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@api_bp.route("/export/scan/<uuid:scan_id>/failures/csv", methods=["GET"])
def export_failures_csv(scan_id):
    """Export only failures to CSV."""
    try:
        csv_data = export_service.export_failures_csv(str(scan_id))
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=failures_{scan_id}.csv"}
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@api_bp.route("/export/matrix/csv", methods=["GET"])
def export_matrix_csv():
    """Export compliance matrix to CSV."""
    scan_id = request.args.get("scan_id")
    try:
        csv_data = export_service.export_matrix_csv(scan_id)
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=compliance_matrix.csv"}
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@api_bp.route("/export/scan/<uuid:scan_id>/summary", methods=["GET"])
def get_scan_summary_report(scan_id):
    """Get summary report data."""
    try:
        summary = export_service.generate_summary_report(str(scan_id))
        return jsonify(summary)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
