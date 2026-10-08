"""Create a private skills.json from an existing private master profile.

This command never reads the public example and never overwrites an existing bank.
"""

import json
from pathlib import Path

from app.models.candidate import CandidateProfile
from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
from app.services.fact_catalog import FactCatalog, normalized_tokens

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "data/master_profile.json"
OUTPUT_PATH = ROOT / "data/skills.json"


def slug(name: str) -> str:
    return "skill_" + "_".join("".join(char if char.isalnum() else " " for char in name.casefold()).split())


# name, category, level, priority, aliases, evidence search, preferred kind, CV wording, subcategory
SPECS = [
    ("Windows", "Windows / Microsoft", "intermediate", 9, ["Microsoft Windows"], "Windows", "experience", "Windows administration", ""),
    ("Windows 11", "Windows / Microsoft", "hands_on", 8, [], "Windows 11", "experience", "Hands-on Windows 11 support", ""),
    ("Windows Server", "Windows / Microsoft", "hands_on", 10, ["Microsoft Windows Server"], "Windows Server", "experience", "Hands-on Windows Server administration", ""),
    ("Active Directory", "Windows / Microsoft", "hands_on", 10, ["AD", "Microsoft Active Directory"], "Active Directory", "experience", "Hands-on Active Directory administration", ""),
    ("Microsoft 365", "Windows / Microsoft", "hands_on", 8, ["M365", "Office 365"], "Microsoft 365", "experience", "Microsoft 365 support", ""),
    ("Windows administration", "Windows / Microsoft", "hands_on", 9, ["Windows admin"], "Windows Server", "experience", "Hands-on Windows administration", ""),
    ("Windows troubleshooting", "Windows / Microsoft", "hands_on", 10, [], "Windows and application issues", "experience", "Windows troubleshooting", ""),
    ("Enterprise workstation support", "Windows / Microsoft", "hands_on", 8, ["desktop support"], "internal users", "experience", "Enterprise workstation support", ""),
    ("PowerShell", "Automation / Scripting", "intermediate", 10, ["PowerShell scripting", "Windows automation"], "PowerShell", "experience", "PowerShell automation", ""),
    ("Python", "Automation / Scripting", "intermediate", 10, ["Python scripting", "Python automation"], "Python", "project", "Python automation", ""),
    ("Bash", "Automation / Scripting", "basic", 6, ["shell scripting"], "Bash", "skill", "Basic Bash", ""),
    ("Linux", "Linux", "hands_on", 10, ["Unix/Linux", "Linux administration", "Unix"], "Linux VPS", "project", "Hands-on Linux administration", ""),
    ("SSH", "Linux", "hands_on", 9, ["Secure Shell"], "SSH", "project", "SSH administration", ""),
    ("systemd", "Linux", "hands_on", 7, ["Linux services"], "systemd", "project", "systemd service administration", ""),
    ("Linux service logs", "Linux", "hands_on", 8, ["Linux logs", "journalctl"], "Linux administration", "project", "Linux service and log troubleshooting", ""),
    ("Linux VPS administration", "Linux", "hands_on", 9, ["VPS administration"], "Linux VPS", "project", "Hands-on Linux VPS administration", ""),
    ("Self-hosting", "Linux", "hands_on", 8, ["self hosted", "self-hosted"], "self-hosted services", "project", "Self-hosted services", ""),
    ("TCP/IP", "Networking", "hands_on", 9, ["TCP", "IP networking"], "TCP/IP", "experience", "TCP/IP troubleshooting", ""),
    ("DNS", "Networking", "hands_on", 9, [], "DNS", "experience", "DNS troubleshooting", ""),
    ("DHCP", "Networking", "hands_on", 8, [], "DHCP", "experience", "DHCP troubleshooting", ""),
    ("VPN", "Networking", "hands_on", 9, ["VPN tunnels"], "VPN", "experience", "VPN troubleshooting", ""),
    ("MikroTik", "Networking", "hands_on", 7, ["RouterOS"], "MikroTik", "experience", "MikroTik networking", ""),
    ("FortiGate", "Networking", "hands_on", 7, ["Fortinet"], "FortiGate", "experience", "FortiGate troubleshooting", ""),
    ("Network troubleshooting", "Networking", "hands_on", 10, ["connectivity troubleshooting"], "network-related issues", "experience", "Network troubleshooting", ""),
    ("VMware ESXi", "Virtualisation", "hands_on", 9, ["VMware", "ESXi"], "VMware ESXi", "experience", "VMware ESXi administration", ""),
    ("Hyper-V", "Virtualisation", "hands_on", 7, ["Microsoft Hyper-V"], "Hyper-V", "skill", "Hyper-V administration", ""),
    ("Proxmox", "Virtualisation", "hands_on", 7, ["Proxmox VE"], "Proxmox", "skill", "Proxmox administration", ""),
    ("VM administration", "Virtualisation", "hands_on", 9, ["virtual machine administration"], "virtual machine administration", "experience", "Virtual machine administration", ""),
    ("MS SQL", "Data / Databases", "hands_on", 8, ["SQL Server", "Microsoft SQL Server", "T-SQL"], "MS SQL Server", "experience", "MS SQL Server", ""),
    ("T-SQL", "Data / Databases", "hands_on", 8, ["Transact-SQL"], "T-SQL", "experience", "T-SQL operational queries", ""),
    ("SQL troubleshooting / operational queries", "Data / Databases", "hands_on", 8, ["SQL troubleshooting", "operational SQL"], "operational queries", "experience", "SQL troubleshooting and operational queries", ""),
    ("Tier 2 Support", "Support / Operations", "hands_on", 10, ["L2 support", "second-line support"], "Tier 2 technical support", "experience", "Tier 2 technical support", ""),
    ("L1/L2 Support", "Support / Operations", "hands_on", 10, ["L1 support", "L2 Support", "service desk"], "L1 and L2", "experience", "L1/L2 support", ""),
    ("Incident handling", "Support / Operations", "hands_on", 9, ["incident management"], "incidents", "experience", "Incident handling", ""),
    ("Incident triage", "Support / Operations", "hands_on", 8, ["issue triage"], "incident spikes", "experience", "Incident triage", ""),
    ("Troubleshooting", "Support / Operations", "hands_on", 10, ["technical troubleshooting"], "Troubleshoots", "experience", "Technical troubleshooting", ""),
    ("Escalation management", "Support / Operations", "hands_on", 9, ["technical escalation"], "escalates complex", "experience", "Escalation management", ""),
    ("Production support", "Support / Operations", "hands_on", 9, ["operations support"], "service disruptions", "experience", "Production support", ""),
    ("Application support", "Support / Operations", "hands_on", 9, ["software support"], "application issues", "experience", "Application support", ""),
    ("Technical documentation", "Support / Operations", "intermediate", 7, ["documentation"], "documentation", "skill", "Technical documentation", ""),
    ("Runbooks", "Support / Operations", "intermediate", 6, ["operational runbooks"], "runbooks", "skill", "Operational runbooks", ""),
    ("Stakeholder communication", "Support / Operations", "hands_on", 8, ["partner communication"], "communicates with partners", "experience", "Stakeholder communication", ""),
    ("English B2 / daily professional use", "Support / Operations", "intermediate", 9, ["English B2", "professional English"], "partners in English", "experience", "English B2 — daily professional use", ""),
    ("Jira", "Tools", "hands_on", 8, [], "Jira", "experience", "Jira", ""),
    ("Salesforce", "Tools", "hands_on", 7, [], "Salesforce", "experience", "Salesforce", ""),
    ("n8n", "Tools", "hands_on", 7, ["n8n automation"], "n8n", "project", "n8n workflow automation", ""),
    ("Docker", "Tools", "basic", 7, ["containers", "containerization"], "Docker", "project", "Basic Docker", ""),
]

AI_SPECS = [
    ("Machine Learning", "hands_on", 10, ["ML"], "Python ML thesis project", "Hands-on machine learning"),
    ("Python for ML / Data Pipelines", "hands_on", 10, ["Python ML", "Python data pipelines"], "Python ML thesis project", "Python for ML and data pipelines"),
    ("Model Training & Comparison", "hands_on", 8, ["model comparison", "ML model evaluation"], "Python ML thesis project", "ML model training and comparison"),
    ("Data preprocessing / ML pipeline", "hands_on", 8, ["data preprocessing", "ML pipeline"], "Python ML thesis project", "Data preprocessing and ML pipelines"),
    ("Large Language Models (LLMs)", "hands_on", 10, ["LLM", "Large Language Models", "Generative AI", "GenAI"], "AI Resume Tailoring Platform", "Hands-on LLM integration"),
    ("Local LLMs", "hands_on", 10, ["local language models"], "AI Resume Tailoring Platform", "Local LLMs"),
    ("Ollama", "hands_on", 10, ["Ollama API"], "AI Resume Tailoring Platform", "Hands-on Ollama integration"),
    ("Local Model Inference", "hands_on", 9, ["local inference", "GPU inference"], "AI Resume Tailoring Platform", "Local model inference"),
    ("LLM Integration", "hands_on", 10, ["LLM API integration"], "AI Resume Tailoring Platform", "LLM integration"),
    ("Prompt Engineering", "hands_on", 9, ["prompt design"], "AI Resume Tailoring Platform", "Prompt engineering"),
    ("Structured LLM Outputs", "hands_on", 10, ["structured outputs", "JSON LLM output"], "AI Resume Tailoring Platform", "Structured LLM outputs"),
    ("Pydantic validation for AI output", "hands_on", 9, ["Pydantic AI validation"], "AI Resume Tailoring Platform", "Pydantic validation for AI outputs"),
    ("AI Guardrails / Fact-Constrained Generation", "hands_on", 10, ["AI guardrails", "Truth Lock", "fact constrained generation"], "AI Resume Tailoring Platform", "AI guardrails and fact-constrained generation"),
    ("AI Workflow Automation", "hands_on", 9, ["AI automation"], "AI Resume Tailoring Platform", "AI workflow automation"),
    ("n8n AI Automation", "hands_on", 8, ["n8n AI workflows"], "AI Resume Tailoring Platform", "n8n AI automation"),
    ("Codex", "hands_on", 8, ["OpenAI Codex"], "AI Resume Tailoring Platform", "Codex-assisted development"),
    ("Hybrid Local / Cloud AI Workflows", "hands_on", 8, ["hybrid AI workflows"], "AI Resume Tailoring Platform", "Hybrid local/cloud AI workflows"),
    ("Tool / Function Calling", "basic", 6, ["function calling", "tool calling"], "AI Resume Tailoring Platform", "Basic tool/function calling"),
    ("LLM Evaluation", "basic", 6, ["LLM evals"], "AI Resume Tailoring Platform", "Basic LLM evaluation"),
    ("Agentic Workflows / AI Agents", "basic", 6, ["agentic AI", "agentic workflows", "AI agents"], "AI Resume Tailoring Platform", "Basic agentic workflows"),
]

AI_DEV_SPECS = [
    ("AI-assisted development", "hands_on", 10, ["AI assisted development", "AI-supported development", "AI coding", "AI-powered development"]),
    ("AI pair programming", "intermediate", 8, ["AI pair programmer", "pair programming with AI"]),
    ("AI coding workflows", "hands_on", 9, ["AI development workflows", "AI coding workflow", "LLM coding workflow"]),
    ("Agent-assisted software development", "intermediate", 7, ["agentic coding", "agent-assisted coding", "AI coding agents"]),
    ("Rapid prototyping with AI coding tools", "hands_on", 8, ["AI rapid prototyping", "rapid prototyping with LLMs"]),
    ("LLM-assisted development", "hands_on", 9, ["LLM assisted coding", "LLM-assisted coding", "LLM development workflow"]),
    ("AI-assisted debugging and code review", "hands_on", 9, ["AI debugging", "AI code review", "LLM-assisted debugging", "LLM code review", "AI-assisted troubleshooting"]),
    ("AI-assisted refactoring", "intermediate", 7, ["LLM-assisted refactoring"]),
    ("AI-assisted test generation", "intermediate", 7, ["LLM test generation"]),
    ("Human-in-the-loop AI development", "hands_on", 9, ["human in the loop development", "human-reviewed AI development"]),
]

LEARNING = [
    ("Retrieval-Augmented Generation (RAG)", ["RAG", "Retrieval Augmented Generation", "Retrieval-Augmented Generation"]),
    ("Embeddings", ["vector embeddings"]),
    ("Vector Databases", ["vector database"]),
    ("Vector Search", ["vector retrieval"]),
    ("Semantic Search", ["semantic retrieval"]),
    ("Chunking Strategies", ["document chunking"]),
    ("Retrieval Strategies", ["retrieval methods"]),
    ("Reranking", ["re-ranking"]),
    ("Advanced LLM Evaluation", ["advanced LLM evals"]),
]


def evidence_for(catalog: FactCatalog, query: str, preferred_kind: str) -> SkillEvidence | None:
    query_tokens = normalized_tokens(query)
    candidates = []
    for entry in catalog.prompt_entries:
        score = len(query_tokens & normalized_tokens(f"{entry.owner_name} {entry.text}"))
        if score:
            candidates.append((entry.kind == preferred_kind, score, entry))
    if not candidates:
        return None
    entry = sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0][2]
    source_type = {"experience": "employment", "project": "project", "education": "education"}.get(
        entry.kind, "master_profile"
    )
    return SkillEvidence(source_type=source_type, source_id=entry.source_id, description=entry.owner_name or entry.text)


def main() -> None:
    if OUTPUT_PATH.exists():
        raise SystemExit(f"Refusing to overwrite existing private bank: {OUTPUT_PATH}")
    profile = CandidateProfile.model_validate_json(PROFILE_PATH.read_text(encoding="utf-8"))
    catalog = FactCatalog(profile)
    skills = []
    for name, category, level, priority, aliases, query, kind, wording, subcategory in SPECS:
        evidence = evidence_for(catalog, query, kind)
        if not evidence:
            continue
        skills.append(VerifiedSkill(id=slug(name), name=name, category=category, subcategory=subcategory, level=level,
            verified=True, allowed_in_cv=True, priority=priority, aliases=aliases, evidence=[evidence], cv_wording=wording))
    for name, level, priority, aliases, query, wording in AI_SPECS:
        evidence = evidence_for(catalog, query, "project")
        if evidence:
            skills.append(VerifiedSkill(id=slug(name), name=name, category="AI / ML", level=level, verified=True,
                allowed_in_cv=True, priority=priority, aliases=aliases, evidence=[evidence], cv_wording=wording))
    for name, level, priority, aliases in AI_DEV_SPECS:
        evidence = evidence_for(catalog, "AI Resume Tailoring Platform", "project")
        if evidence:
            skills.append(VerifiedSkill(id=slug(name), name=name, category="AI / ML", subcategory="AI-Assisted Development",
                level=level, verified=True, allowed_in_cv=True, priority=priority, aliases=aliases, evidence=[evidence], cv_wording=name))
    for name, aliases in LEARNING:
        skills.append(VerifiedSkill(id=slug(name), name=name, category="AI / ML", level="learning", verified=False,
            allowed_in_cv=False, priority=4, aliases=aliases, notes="Learning only; not professional experience."))
    OUTPUT_PATH.write_text(SkillsDocument(skills=skills).model_dump_json(indent=2) + "\n", encoding="utf-8")
    OUTPUT_PATH.chmod(0o600)
    print(json.dumps({"created": len(skills), "path": str(OUTPUT_PATH)}))


if __name__ == "__main__":
    main()
