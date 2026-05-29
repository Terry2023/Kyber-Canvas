from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import requests
import os

app = Flask(__name__)
CORS(app)

OLLAMA_URL = "http://localhost:11434/api/generate"
DB_FILE = os.path.join(os.path.dirname(__file__), "BezosAuditor.sql")
print("DB PATH:", os.path.abspath(DB_FILE))
print("DB EXISTS:", os.path.exists(DB_FILE))

AUDITOR_MODEL = "deepseek-r1:14b"

def get_db():
    return sqlite3.connect(DB_FILE)

def query_bezos_framework(node_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.principle, r.action_required 
            FROM risk_thresholds r
            LEFT JOIN operational_principles p ON r.node_id = p.id
            WHERE r.node_id = ?
        """, (node_id,))
        result = cur.fetchone()
        conn.close()
        return result if result else ("Protect the flywheel", "Diagnose imbalance")
    except Exception as e:
        print(f"DB error: {e}")
        return None

def get_coherence_threshold():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT AVG(critical_limit) FROM risk_thresholds WHERE node_id < 8")
        val = cur.fetchone()[0]
        conn.close()
        return float(val) if val else 0.68
    except:
        return 0.68

def call_ollama(model_name, prompt):
    payload = {"model": model_name, "prompt": prompt, "stream": False, "options": {"temperature": 0.25}}
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=60)
        return r.json().get("response", "No response")
    except Exception as e:
        return f"LLM Error: {e}"

@app.route('/get-matrix', methods=['GET'])
def get_matrix():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT node_id_from, node_id_to, coupling_strength FROM flywheel_couplings")
        rows = cur.fetchall()
        conn.close()
        W = [[0.0 for _ in range(12)] for _ in range(12)]
        for f,t,s in rows:
            if 0 <= f < 12 and 0 <= t < 12:
                W[t][f] = max(-0.7, min(0.7, float(s)))  # clamp
        return jsonify({"matrix": W, "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get-thresholds', methods=['GET'])
def get_thresholds():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT node_id, critical_limit FROM risk_thresholds")
        rows = cur.fetchall()
        conn.close()
        thresholds = {nid: lim for nid, lim in rows}
        avg_core = sum([lim for nid, lim in rows if nid < 8]) / 8
        return jsonify({"thresholds": thresholds, "coherence_threshold": avg_core})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/audit-state', methods=['POST'])
def audit_state():
    data = request.json
    coherence = data.get("coherence", 1.0)
    values = data.get("values", [])
    threshold = get_coherence_threshold()
    
    if coherence < threshold:
        worst = int(values.index(min(values[:8])))  # only core nodes
        principle, action = query_bezos_framework(worst) or ("","")
        prompt = f"""You are Jeff Bezos, Chief Efficiency Auditor.

State: Coherence {coherence:.3f} (threshold {threshold:.2f})
Values: {values}
Worst Node: {worst}

Axioms:
- {principle}
- {action}

Give a 3-sentence audit: root cause, immediate action, metric to watch."""
        verdict = call_ollama(AUDITOR_MODEL, prompt)
        return jsonify({"status":"audited","verdict":verdict,"target_node":worst,"threshold":threshold})
    return jsonify({"status":"nominal","threshold":threshold})

if __name__ == '__main__':
    print("🚀 Governance Bridge v5 online")
    app.run(port=5000, debug=False)