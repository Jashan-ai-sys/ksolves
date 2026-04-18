from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import json
import os
from datetime import datetime

app = FastAPI(title="ShopWave Intel Dashboard")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ShopWave Intel | Multi-Agent Command Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #020617;
            --bg-card: #0f172a;
            --bg-hover: #1e293b;
            --border: rgba(51, 65, 85, 0.5);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.3);
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --purple: #a855f7;
        }
        
        * { box-sizing: border-box; }
        body {
            background-color: var(--bg-dark);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            margin: 0;
            padding: 0;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }

        /* Sidebar */
        .sidebar {
            width: 360px;
            background-color: var(--bg-card);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            box-shadow: 10px 0 30px rgba(0,0,0,0.5);
            z-index: 10;
        }

        .header {
            padding: 24px;
            background: linear-gradient(135deg, #0f172a 0%, #020617 100%);
            border-bottom: 1px solid var(--border);
        }

        .header h1 {
            margin: 0;
            font-size: 1.4rem;
            color: var(--accent);
            letter-spacing: -0.02em;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .header p { color: var(--text-muted); font-size: 0.8rem; margin: 8px 0 0 0; }

        .sidebar-scroll {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
        }

        .ticket-card {
            padding: 16px;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border);
            border-radius: 12px;
            margin-bottom: 12px;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
        }

        .ticket-card:hover {
            background: var(--bg-hover);
            border-color: var(--accent);
            transform: translateY(-2px);
            box-shadow: 0 10px 20px -10px rgba(0,0,0,0.5);
        }

        .ticket-card.active {
            background: rgba(56, 189, 248, 0.1);
            border-color: var(--accent);
            box-shadow: inset 0 0 20px rgba(56, 189, 248, 0.1);
        }

        .ticket-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .ticket-id { font-weight: 700; color: var(--accent); font-family: 'Fira Code', monospace; font-size: 0.9rem; }
        .ticket-subject { font-size: 0.9rem; font-weight: 500; color: #e2e8f0; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ticket-preview { font-size: 0.75rem; color: var(--text-muted); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

        .tier-badge {
            font-size: 0.65rem;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 800;
            text-transform: uppercase;
        }
        .tier-3 { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
        .tier-2 { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
        .tier-1 { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }

        /* Main Context */
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            background: radial-gradient(circle at top right, #0f172a, #020617);
        }

        .stats-bar {
            padding: 20px 40px;
            display: flex;
            gap: 40px;
            background: rgba(15, 23, 42, 0.8);
            backdrop-filter: blur(10px);
            border-bottom: 1px solid var(--border);
        }

        .stat-item { display: flex; flex-direction: column; }
        .stat-label { font-size: 0.7rem; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.1em; font-weight: 700; margin-bottom: 4px; }
        .stat-value { font-size: 1.5rem; font-weight: 700; color: var(--text-main); }
        .stat-value.success { color: var(--success); }

        .content-scroll {
            flex: 1;
            overflow-y: auto;
            padding: 40px;
            scroll-behavior: smooth;
        }

        .ticket-header-large {
            margin-bottom: 40px;
            max-width: 900px;
            margin-left: auto;
            margin-right: auto;
        }

        .timeline {
            position: relative;
            max-width: 900px;
            margin: 0 auto;
        }

        .timeline::before {
            content: '';
            position: absolute;
            top: 0; bottom: 0; left: 30px;
            width: 2px;
            background: linear-gradient(to bottom, var(--accent), var(--purple), var(--border));
            border-radius: 1px;
        }

        .node {
            position: relative;
            padding-left: 80px;
            margin-bottom: 40px;
            animation: slideIn 0.5s ease-out forwards;
            opacity: 0;
        }

        @keyframes slideIn {
            from { transform: translateX(20px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }

        .node-icon {
            position: absolute;
            left: 14px; top: 0;
            width: 34px; height: 34px;
            border-radius: 50%;
            background: var(--bg-dark);
            border: 2px solid var(--accent);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
            z-index: 2;
            box-shadow: 0 0 15px var(--accent-glow);
        }

        .panel {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.3);
            transition: border-color 0.3s;
        }

        .panel:hover { border-color: rgba(56, 189, 248, 0.4); }

        .panel-title {
            font-size: 1rem;
            font-weight: 700;
            color: #f1f5f9;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .json-viewer {
            background: #020617;
            border-radius: 8px;
            padding: 16px;
            color: #7dd3fc;
            font-family: 'Fira Code', monospace;
            font-size: 0.85rem;
            line-height: 1.5;
            overflow-x: auto;
            border: 1px solid rgba(255,255,255,0.05);
            margin-top: 12px;
        }

        .step-tag { font-size: 0.7rem; background: var(--accent); color: var(--bg-dark); padding: 2px 8px; border-radius: 4px; font-weight: 800; margin-right: 8px; }

        /* Status colors */
        .node.planner .node-icon { border-color: var(--accent); color: var(--accent); box-shadow: 0 0 15px rgba(56, 189, 248, 0.4); }
        .node.validator .node-icon { border-color: var(--success); color: var(--success); box-shadow: 0 0 15px rgba(16, 185, 129, 0.4); }
        .node.executor .node-icon { border-color: var(--warning); color: var(--warning); box-shadow: 0 0 15px rgba(245, 158, 11, 0.4); }
        .node.responder .node-icon { border-color: var(--purple); color: var(--purple); box-shadow: 0 0 15px rgba(168, 85, 247, 0.4); }

        .empty-state {
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            padding: 40px;
        }
        
        .code-accent { color: var(--accent); font-family: 'Fira Code', monospace; }

        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
    </style>
</head>
<body>

    <div class="sidebar">
        <div class="header">
            <h1>🌊 ShopWave Intel</h1>
            <p>Production Multi-Agent Audit Logic</p>
        </div>
        <div class="sidebar-scroll" id="ticketList">
            <!-- Tickets injected -->
        </div>
    </div>

    <div class="main">
        <div class="stats-bar" id="statsBar">
            <div class="stat-item">
                <span class="stat-label">System State</span>
                <span class="stat-value" style="color:var(--success); font-size: 1rem;">● Operational</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Total Tickets</span>
                <span id="stat-total" class="stat-value">0</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Success Rate</span>
                <span id="stat-rate" class="stat-value success">0%</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Avg Confidence</span>
                <span id="stat-conf" class="stat-value">0.00</span>
            </div>
        </div>

        <div class="content-scroll" id="mainContent">
            <div class="empty-state">
                <h1 style="font-size: 3rem; margin-bottom: 0;">🛸</h1>
                <h2 style="font-size: 2rem;">Command Center Ready</h2>
                <p style="color: var(--text-muted); max-width: 500px;">Select a ticket from the left to visualize the Multi-Agent reasoning chain and MCP tool execution steps in real-time.</p>
                <div class="code-accent" style="margin-top:20px;">Watching output/audit_log.json...</div>
            </div>
        </div>
    </div>

    <script>
        let auditData = [];
        let ticketMap = {};

        async function refreshData() {
            try {
                const response = await fetch('/api/audit-log');
                const data = await response.json();
                auditData = data;
                process();
                renderSidebar();
                updateStats();
            } catch (e) { console.error("Poll error", e); }
        }

        function process() {
            ticketMap = {};
            auditData.forEach(ev => {
                const tid = ev.ticket_id;
                if (!tid) return;
                if (!ticketMap[tid]) ticketMap[tid] = { events: [], priority: 1, subject: 'Unknown Order' };
                ticketMap[tid].events.push(ev);
                
                if (ev.event_type === 'TICKET_START') {
                    ticketMap[tid].subject = ev.ticket.subject;
                    ticketMap[tid].tier = ev.ticket.tier || 1;
                    ticketMap[tid].body = ev.ticket.body || ev.ticket.message;
                }
                if (ev.event_type === 'TICKET_END') {
                    ticketMap[tid].outcome = ev.outcome;
                    ticketMap[tid].summary = ev.summary;
                }
            });
        }

        function updateStats() {
            const tickets = Object.values(ticketMap);
            const total = tickets.length;
            const success = tickets.filter(t => t.outcome === 'success').length;
            const avgConf = tickets.reduce((acc, t) => acc + (t.summary?.confidence || 0), 0) / (total || 1);
            
            document.getElementById('stat-total').innerText = total;
            document.getElementById('stat-rate').innerText = total ? Math.round((success/total)*100) + '%' : '0%';
            document.getElementById('stat-conf').innerText = avgConf.toFixed(2);
        }

        function renderSidebar() {
            const list = document.getElementById('ticketList');
            const currentActive = document.querySelector('.ticket-card.active')?.dataset.id;
            list.innerHTML = '';
            
            Object.keys(ticketMap).sort().reverse().forEach(tid => {
                const ticket = ticketMap[tid];
                const card = document.createElement('div');
                card.className = `ticket-card ${currentActive === tid ? 'active' : ''}`;
                card.dataset.id = tid;
                card.onclick = () => renderMain(tid);
                
                card.innerHTML = `
                    <div class="ticket-meta">
                        <span class="ticket-id">${tid}</span>
                        <span class="tier-badge tier-${ticket.tier || 1}">Tier ${ticket.tier || 1}</span>
                    </div>
                    <div class="ticket-subject">${ticket.subject}</div>
                    <div class="ticket-preview">${ticket.body || ''}</div>
                `;
                list.appendChild(card);
            });
        }

        function renderMain(tid) {
            document.querySelectorAll('.ticket-card').forEach(c => c.classList.toggle('active', c.dataset.id === tid));
            const ticket = ticketMap[tid];
            const main = document.getElementById('mainContent');
            main.innerHTML = `
                <div class="ticket-header-large">
                    <h1 style="font-size: 2.5rem; margin:0;">${tid}</h1>
                    <p style="color:var(--accent); font-weight:600; font-size:1.1rem;">${ticket.subject}</p>
                    <div style="background:rgba(255,255,255,0.05); padding:20px; border-radius:12px; margin-top:20px; border:1px solid var(--border);">
                        <div class="stat-label">Original Request</div>
                        <div style="line-height:1.6; color:#e2e8f0;">${ticket.body}</div>
                    </div>
                </div>
                <div class="timeline" id="activeTimeline"></div>
            `;

            const timeline = document.getElementById('activeTimeline');
            ticket.events.forEach((ev, idx) => {
                const node = document.createElement('div');
                let typeClass = "";
                let icon = "•";
                let title = ev.event_type;
                let body = "";

                if (ev.event_type === 'THOUGHT') {
                    typeClass = ev.agent === 'planner' ? 'planner' : 'validator';
                    icon = ev.agent === 'planner' ? '🧠' : '🛡️';
                    title = `${ev.agent.toUpperCase()} Reasoning`;
                    body = `
                        <p style="color:var(--text-muted); font-style:italic;">"${ev.thought}"</p>
                        ${ev.data ? `<div class="json-viewer">${JSON.stringify(ev.data, null, 2)}</div>` : ''}
                    `;
                } else if (ev.event_type === 'ACTION' && ev.action.includes('planner')) {
                    typeClass = "planner"; icon = "📝"; title = "Planner Invoked";
                    body = `Initial plan generation started...`;
                } else if (ev.event_type === 'OUTPUT') {
                    typeClass = ev.agent === 'planner' ? 'planner' : (ev.agent === 'executor' ? 'executor' : 'responder');
                    icon = ev.agent === 'planner' ? '📋' : (ev.agent === 'executor' ? '⚙️' : '📨');
                    title = `${ev.agent.toUpperCase()} Result`;
                    body = `<div class="json-viewer">${JSON.stringify(ev.output, null, 2)}</div>`;
                } else if (ev.event_type === 'ERROR') {
                    typeClass = "executor"; icon = "⚠️"; title = "System Error";
                    body = `<div style="color:var(--danger); font-weight:700;">${ev.error}</div><div class="json-viewer">${JSON.stringify(ev.details, null, 2)}</div>`;
                } else if (ev.event_type === 'DECISION') {
                    typeClass = "validator"; icon = "⚖️"; title = `Decision: ${ev.decision}`;
                    body = `<div style="font-weight:700;">${ev.reasoning}</div>${ev.data ? `<div class="json-viewer">${JSON.stringify(ev.data, null, 2)}</div>` : ''}`;
                } else {
                    return; // Skip meta events
                }

                node.className = `node ${typeClass}`;
                node.style.animationDelay = `${idx * 0.1}s`;
                node.innerHTML = `
                    <div class="node-icon">${icon}</div>
                    <div class="panel">
                        <div class="panel-title">${title} <span>${new Date(ev.timestamp).toLocaleTimeString()}</span></div>
                        <div class="panel-body">${body}</div>
                    </div>
                `;
                timeline.appendChild(node);
            });
        }

        setInterval(refreshData, 3000);
        refreshData();
    </script>
</body>
</html>
"""

@app.get("/")
def read_root():
    return HTMLResponse(content=HTML_TEMPLATE, status_code=200)

@app.get("/api/audit-log")
def get_audit_log():
    log_path = os.path.join(os.path.dirname(__file__), "output", "audit_log.json")
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

if __name__ == "__main__":
    import uvicorn
    print("\n🚀 Starting Premium ShopWave Intel Dashboard...")
    print("👉 Open your browser to: http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
