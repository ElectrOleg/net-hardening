
import click
from flask.cli import with_appcontext
from app.extensions import db
from app.models import Vendor, Policy, Rule, DataSource

@click.command("seed")
@with_appcontext
def seed_command():
    """Seed the database with initial data."""
    click.echo("Seeding database...")
    
    # 1. Vendors
    vendors = [
        {"code": "cisco_ios", "name": "Cisco IOS", "parser_driver": "ciscoconfparse"},
        {"code": "cisco_iosxe", "name": "Cisco IOS-XE", "parser_driver": "ciscoconfparse"},
        {"code": "cisco_iosxr", "name": "Cisco IOS-XR", "parser_driver": "ciscoconfparse"},
        {"code": "cisco_nxos", "name": "Cisco NX-OS", "parser_driver": "ciscoconfparse"},
        {"code": "juniper_junos", "name": "Juniper JunOS", "parser_driver": "json"},
        {"code": "arista_eos", "name": "Arista EOS", "parser_driver": "ciscoconfparse"},
        {"code": "huawei", "name": "Huawei VRP", "parser_driver": "ciscoconfparse"},
        {"code": "eltex_esr", "name": "Eltex ESR", "parser_driver": "ciscoconfparse"},
        {"code": "fortinet_fortios", "name": "Fortinet FortiOS", "parser_driver": "json"},
        {"code": "paloalto_panos", "name": "Palo Alto PAN-OS", "parser_driver": "json"},
        {"code": "mikrotik_routeros", "name": "MikroTik RouterOS", "parser_driver": "ciscoconfparse"},
        {"code": "linux", "name": "Linux", "parser_driver": "json"},
        {"code": "usergate", "name": "UserGate", "parser_driver": "json"},
        {"code": "checkpoint", "name": "Check Point", "parser_driver": "json"},
    ]
    
    for v_data in vendors:
        if not Vendor.query.get(v_data["code"]):
            v = Vendor(**v_data)
            db.session.add(v)
    
    db.session.commit()
    click.echo(f"Vendors seeded.")

    # 2. Policies
    policy = Policy.query.filter_by(name="Standard Hardening").first()
    if not policy:
        policy = Policy(
            name="Standard Hardening",
            description="Baseline security checks",
            severity="high"
        )
        db.session.add(policy)
        db.session.commit()
        click.echo("Created 'Standard Hardening' policy.")

    # 3. Rules
    rules_data = [
        {
            "title": "No Telnet",
            "vendor_code": "cisco_ios",
            "logic_type": "simple_match",
            "logic_payload": {"pattern": "transport input telnet", "match_mode": "must_not_exist"},
            "description": "Telnet should be disabled",
            "remediation": "line vty 0 4\n transport input ssh"
        },
        {
            "title": "Minimum Password Length",
            "vendor_code": "cisco_ios",
            "logic_type": "simple_match",
            "logic_payload": {"pattern": "security passwords min-length 8", "match_mode": "must_exist"},
            "description": "Password length must be at least 8",
            "remediation": "security passwords min-length 8"
        },
        {
            "title": "Service Password Encryption",
            "vendor_code": "cisco_ios",
            "logic_type": "simple_match",
            "logic_payload": {"pattern": "service password-encryption", "match_mode": "must_exist"},
            "description": "Passwords must be encrypted",
            "remediation": "service password-encryption"
        }
    ]
    
    for r_data in rules_data:
        if not Rule.query.filter_by(title=r_data["title"], policy_id=policy.id).first():
            r = Rule(policy_id=policy.id, **r_data)
            db.session.add(r)
            
    db.session.commit()
    click.echo("Rules seeded.")
    
    click.echo("Database seeding completed!")


@click.command("seed-admin")
@click.option("--username", default="admin", help="Admin username")
@click.option("--password", default="admin123", help="Admin password")
@with_appcontext
def seed_admin_command(username, password):
    """Create default admin user for first-time setup."""
    from app.models.user import User

    existing = User.query.filter_by(username=username).first()
    if existing:
        click.echo(f"User '{username}' already exists (role={existing.role})")
        return

    user = User(
        username=username,
        display_name="Administrator",
        email="",
        auth_source="local",
        role="admin",
        is_active=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    click.echo(f"Created admin user '{username}' with password '{password}'")
    click.echo("⚠️  Change the password after first login!")
