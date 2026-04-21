#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Inject anomaly events into the hackathon-agent and trigger Bedrock analysis.
#
# Usage:
#   ./scripts/trigger_anomaly.sh                     # defaults to localhost:8080
#   ./scripts/trigger_anomaly.sh http://10.0.1.5:8080  # custom endpoint
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BASE_URL="${1:-http://localhost:8080}"
NOW=$(date +%s)

echo "🔧 Target: $BASE_URL"
echo ""

# ── Step 1: Inject UC1 Supply Chain anomaly events ───────────────────────────
echo "📦 Injecting UC1 supply chain disruption events..."

curl -s -X POST "$BASE_URL/api/events" \
  -H "Content-Type: application/json" \
  -d @- <<'EOF' | python3 -m json.tool
{
  "events": [
    {
      "source": "UC1/supplier-capacity",
      "data": {
        "event_type": "capacity_alert",
        "supplier": "CoreFab International",
        "region": "APAC-East",
        "component": "cellular-modem",
        "capacity_pct": 12,
        "previous_capacity_pct": 85,
        "reason": "export_restriction_escalation",
        "severity": "CRITICAL",
        "message": "CoreFab International capacity collapsed from 85% to 12% due to new APAC-East export restrictions on semiconductor components"
      }
    },
    {
      "source": "UC1/supplier-capacity",
      "data": {
        "event_type": "capacity_alert",
        "supplier": "CoreFab International",
        "region": "APAC-East",
        "component": "cellular-modem",
        "capacity_pct": 8,
        "previous_capacity_pct": 12,
        "reason": "production_line_shutdown",
        "severity": "CRITICAL",
        "message": "CoreFab production line 3 shut down — capacity now at 8%"
      }
    },
    {
      "source": "UC1/geopolitical",
      "data": {
        "event_type": "policy_change",
        "region": "APAC-East",
        "category": "export_controls",
        "severity": "HIGH",
        "affected_components": ["cellular-modem", "rf-amplifier", "baseband-chip"],
        "message": "APAC-East government expanded export restrictions to cover all Category 5 telecommunications components effective immediately"
      }
    },
    {
      "source": "UC1/logistics",
      "data": {
        "event_type": "congestion_alert",
        "route": "APAC-East → NA-West",
        "delay_hours": 168,
        "normal_delay_hours": 48,
        "containers_stuck": 342,
        "severity": "HIGH",
        "message": "Major port congestion at APAC-East hub — 342 containers held for export compliance review, 7-day delay"
      }
    },
    {
      "source": "UC1/logistics",
      "data": {
        "event_type": "route_disruption",
        "route": "APAC-East → EU-Central",
        "status": "SUSPENDED",
        "severity": "CRITICAL",
        "message": "All shipments from CoreFab suspended pending regulatory clearance"
      }
    },
    {
      "source": "UC1/inventory",
      "data": {
        "event_type": "stock_alert",
        "component": "cellular-modem",
        "warehouse": "NA-West-Primary",
        "current_units": 1200,
        "safety_stock": 15000,
        "daily_consumption": 800,
        "days_of_supply": 1.5,
        "severity": "CRITICAL",
        "message": "Cellular modem inventory at 1.5 days of supply — well below 15,000 unit safety stock threshold"
      }
    },
    {
      "source": "UC1/inventory",
      "data": {
        "event_type": "stock_alert",
        "component": "cellular-modem",
        "warehouse": "EU-Central-Primary",
        "current_units": 450,
        "safety_stock": 8000,
        "daily_consumption": 400,
        "days_of_supply": 1.1,
        "severity": "CRITICAL",
        "message": "EU warehouse cellular modem stock critically low — 1.1 days remaining"
      }
    }
  ]
}
EOF

echo ""

# ── Step 2: Inject UC2 App Store Compliance anomaly events ───────────────────
echo "📱 Injecting UC2 app store compliance anomaly events..."

curl -s -X POST "$BASE_URL/api/events" \
  -H "Content-Type: application/json" \
  -d @- <<'EOF' | python3 -m json.tool
{
  "events": [
    {
      "source": "UC2/submission-queue",
      "data": {
        "event_type": "submission_review",
        "developer_account": "dev_account_7741",
        "app_id": "com.obscure.tracker",
        "version": "3.4.1",
        "privacy_manifest_status": "INCOMPLETE",
        "declared_data_types": ["analytics"],
        "detected_data_types": ["location", "contacts", "device_id", "browsing_history", "analytics"],
        "discrepancy_count": 4,
        "severity": "HIGH",
        "message": "Privacy manifest declares only 'analytics' but binary analysis detected 5 data collection categories including location and contacts"
      }
    },
    {
      "source": "UC2/policy-kb",
      "data": {
        "event_type": "policy_violation_match",
        "rule_id": "PRIVACY-2024-017",
        "app_id": "com.obscure.tracker",
        "violation": "undisclosed_tracking_capability",
        "details": "App contains ATT-bypass fingerprinting SDK (DeviceGraph v2.1) not declared in privacy manifest",
        "severity": "CRITICAL",
        "message": "Policy PRIVACY-2024-017 violated: undisclosed device fingerprinting SDK detected in com.obscure.tracker"
      }
    },
    {
      "source": "UC2/submission-history",
      "data": {
        "event_type": "pattern_detected",
        "developer_account": "dev_account_7741",
        "app_id": "com.obscure.tracker",
        "pattern": "progressive_obfuscation",
        "history": [
          {"version": "3.1.0", "undisclosed_types": 1},
          {"version": "3.2.0", "undisclosed_types": 2},
          {"version": "3.3.0", "undisclosed_types": 3},
          {"version": "3.4.1", "undisclosed_types": 4}
        ],
        "severity": "CRITICAL",
        "message": "Progressive obfuscation pattern: dev_account_7741 has increased undisclosed data types from 1 to 4 over last 4 releases"
      }
    },
    {
      "source": "UC2/escalation-queue",
      "data": {
        "event_type": "auto_escalation",
        "developer_account": "dev_account_7741",
        "app_id": "com.obscure.tracker",
        "reason": "repeated_privacy_violations",
        "prior_warnings": 3,
        "recommended_action": "SUSPEND_REVIEW",
        "severity": "CRITICAL",
        "message": "Auto-escalated: dev_account_7741 has 3 prior privacy warnings and now shows deliberate obfuscation pattern — recommend immediate review suspension"
      }
    },
    {
      "source": "UC2/submission-queue",
      "data": {
        "event_type": "binary_analysis",
        "app_id": "com.obscure.tracker",
        "version": "3.4.1",
        "findings": [
          "Embedded SDK: DeviceGraph v2.1 (fingerprinting)",
          "API calls to tracking.obscure-analytics.net (undeclared)",
          "Background location access without declared purpose",
          "Contacts framework linked but not in privacy manifest"
        ],
        "risk_score": 0.94,
        "severity": "CRITICAL",
        "message": "Binary analysis risk score 0.94 — multiple undeclared tracking capabilities found"
      }
    }
  ]
}
EOF

echo ""

# ── Step 3: Trigger Bedrock analysis ─────────────────────────────────────────
echo "🔍 Triggering Bedrock anomaly analysis..."
echo ""

curl -s -X POST "$BASE_URL/api/analyze" \
  -H "Content-Type: application/json" | python3 -m json.tool

echo ""
echo "✅ Done! Check the dashboard at $BASE_URL"
