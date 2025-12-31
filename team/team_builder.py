"""
Team Builder - Dynamic Agent Team Generation

Allows creating specialized agent teams on the fly:
- Define team templates (e.g., "project-management", "data-pipeline", "security-audit")
- Specify 3-5+ agents with roles and expertise
- Generate tailored prompts for each agent based on task description

The user describes what they need, and we assemble the right team.
"""

import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# =============================================================================
# DATA MODELS
# =============================================================================

class AgentRole(BaseModel):
    """Definition of an agent role within a team."""
    id: str = Field(..., description="Unique agent ID (e.g., 'tech-lead', 'researcher')")
    name: str = Field(..., description="Display name (e.g., 'Tech Lead', 'Researcher')")
    expertise: list[str] = Field(default_factory=list, description="Areas of expertise")
    responsibilities: list[str] = Field(default_factory=list, description="What this agent does")
    constraints: list[str] = Field(default_factory=list, description="What this agent should NOT do")
    collaborates_with: list[str] = Field(default_factory=list, description="Other agents it works with")
    prompt_template: Optional[str] = Field(None, description="Custom prompt template (optional)")


class TeamTemplate(BaseModel):
    """A reusable team configuration template."""
    id: str = Field(..., description="Unique template ID (e.g., 'project-management')")
    name: str = Field(..., description="Display name (e.g., 'Project Management Team')")
    description: str = Field(..., description="What this team does")
    agents: list[AgentRole] = Field(..., description="Agents in this team (3-10)")
    min_agents: int = Field(default=3, ge=1, le=10, description="Minimum agents required")
    max_agents: int = Field(default=5, ge=3, le=10, description="Maximum agents allowed")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    use_count: int = Field(default=0, description="How many times this template was used")


class TeamInstance(BaseModel):
    """A spawned team instance (runtime)."""
    id: str = Field(..., description="Unique instance ID")
    template_id: str = Field(..., description="Which template was used")
    task_description: str = Field(..., description="What the team is working on")
    agents: list[str] = Field(..., description="Agent IDs that were spawned")
    status: str = Field(default="spawning", description="spawning|active|completed|failed")
    spawned_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    completed_at: Optional[str] = None
    session_id: Optional[str] = None


# =============================================================================
# STORAGE
# =============================================================================

# File paths
IHIM_PATH = Path("C:/Users/<user>/workspace/IHIM")
DATA_PATH = IHIM_PATH / "data"
TEMPLATES_FILE = DATA_PATH / "team_templates.json"
INSTANCES_FILE = DATA_PATH / "team_instances.json"


def ensure_data_dir():
    """Ensure data directory exists."""
    DATA_PATH.mkdir(parents=True, exist_ok=True)


def load_templates() -> list[TeamTemplate]:
    """Load all team templates from storage."""
    ensure_data_dir()
    if not TEMPLATES_FILE.exists():
        # Create with default templates
        defaults = get_default_templates()
        save_templates(defaults)
        return defaults

    try:
        data = json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
        return [TeamTemplate(**t) for t in data.get("templates", [])]
    except Exception as e:
        # Log the error and return defaults to prevent total failure
        print(f"ERROR: Failed to load templates from {TEMPLATES_FILE}: {e}")
        print("WARNING: Returning default templates. Your custom templates may be lost.")
        return get_default_templates()


def save_templates(templates: list[TeamTemplate]):
    """Save all team templates to storage."""
    ensure_data_dir()
    data = {"templates": [t.model_dump() for t in templates]}
    TEMPLATES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_instances() -> list[TeamInstance]:
    """Load all team instances from storage."""
    ensure_data_dir()
    if not INSTANCES_FILE.exists():
        return []

    try:
        data = json.loads(INSTANCES_FILE.read_text(encoding="utf-8"))
        return [TeamInstance(**i) for i in data.get("instances", [])]
    except Exception:
        return []


def save_instances(instances: list[TeamInstance]):
    """Save all team instances to storage."""
    ensure_data_dir()
    data = {"instances": [i.model_dump() for i in instances]}
    INSTANCES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# =============================================================================
# TEMPLATE CRUD
# =============================================================================

def get_template(template_id: str) -> Optional[TeamTemplate]:
    """Get a specific template by ID."""
    templates = load_templates()
    for t in templates:
        if t.id == template_id:
            return t
    return None


def create_template(template: TeamTemplate) -> TeamTemplate:
    """Create a new team template."""
    templates = load_templates()

    # Check for duplicate ID
    for t in templates:
        if t.id == template.id:
            raise ValueError(f"Template with ID '{template.id}' already exists")

    # Validate agent count
    if len(template.agents) < template.min_agents:
        raise ValueError(f"Template must have at least {template.min_agents} agents")
    if len(template.agents) > template.max_agents:
        raise ValueError(f"Template cannot have more than {template.max_agents} agents")

    templates.append(template)
    save_templates(templates)
    return template


def update_template(template_id: str, updates: dict) -> Optional[TeamTemplate]:
    """Update an existing template."""
    templates = load_templates()

    for i, t in enumerate(templates):
        if t.id == template_id:
            # Apply updates
            data = t.model_dump()
            data.update(updates)
            data["updated_at"] = datetime.utcnow().isoformat() + "Z"
            templates[i] = TeamTemplate(**data)
            save_templates(templates)
            return templates[i]

    return None


def delete_template(template_id: str) -> bool:
    """Delete a template by ID."""
    templates = load_templates()
    original_count = len(templates)
    templates = [t for t in templates if t.id != template_id]

    if len(templates) < original_count:
        save_templates(templates)
        return True
    return False


def increment_use_count(template_id: str):
    """Increment the use count for a template."""
    templates = load_templates()
    for t in templates:
        if t.id == template_id:
            t.use_count += 1
            t.updated_at = datetime.utcnow().isoformat() + "Z"
    save_templates(templates)


# =============================================================================
# PROMPT GENERATION
# =============================================================================

def generate_agent_prompt(
    agent: AgentRole,
    task_description: str,
    project: str = "workspace",
    working_dir: str = "C:/Users/<user>/workspace",
    session_id: str = None,
    team_name: str = None,
    teammates: list[str] = None
) -> str:
    """
    Generate a tailored prompt for an agent.

    Args:
        agent: The agent role definition
        task_description: What the team is working on
        project: Project name
        working_dir: Working directory
        session_id: Unique session ID
        team_name: Name of the team
        teammates: List of other agent IDs in the team

    Returns:
        Formatted prompt string for the agent
    """
    teammates = teammates or []
    teammates_str = ", ".join(teammates) if teammates else "None"

    # Use custom template if provided, otherwise use default
    if agent.prompt_template:
        return agent.prompt_template.format(
            agent_name=agent.name,
            agent_id=agent.id,
            task=task_description,
            project=project,
            working_dir=working_dir,
            session_id=session_id or "unknown",
            team_name=team_name or "Custom Team",
            teammates=teammates_str,
            expertise=", ".join(agent.expertise),
            responsibilities="\n".join(f"- {r}" for r in agent.responsibilities),
            constraints="\n".join(f"- {c}" for c in agent.constraints),
            collaborates_with=", ".join(agent.collaborates_with),
        )

    # Default template
    return f"""# Task for {agent.name}

You are the **{agent.name}** specialist on the **{team_name or 'Custom Team'}**.

## Your Expertise
{chr(10).join(f"- {e}" for e in agent.expertise) if agent.expertise else "- General expertise"}

## Your Responsibilities
{chr(10).join(f"- {r}" for r in agent.responsibilities) if agent.responsibilities else "- Complete assigned tasks"}

## Your Task
{task_description}

## Project Context
- Project: {project}
- Working directory: {working_dir}
- Session ID: {session_id or 'unknown'}
- Your teammates: {teammates_str}

## Collaboration
You work with: {', '.join(agent.collaborates_with) if agent.collaborates_with else 'all team members'}

Use the blackboard (IHIM/team/blackboard.json) to:
- Post updates when you complete something
- Ask questions to teammates (@agent-id)
- Report blockers if you're stuck

## Constraints
{chr(10).join(f"- {c}" for c in agent.constraints) if agent.constraints else "- Stay within your role's scope"}

## Deliverables
When done, write your report to: IHIM/team/results/{agent.id}-result.json

Format:
```json
{{
  "agent": "{agent.id}",
  "status": "complete|partial|blocked",
  "summary": "What you accomplished",
  "files_modified": ["list", "of", "files"],
  "blockers": ["if any"],
  "handoff_notes": "For other agents"
}}
```

Begin your work now.
"""


def route_to_team(
    template: TeamTemplate,
    task_description: str,
    project: str = "workspace",
    working_dir: str = "C:/Users/<user>/workspace",
    agent_subset: list[str] = None
) -> dict[str, str]:
    """
    Route a task to all agents in a team template.

    Args:
        template: The team template to use
        task_description: What the team should work on
        project: Project name
        working_dir: Working directory
        agent_subset: Optional subset of agent IDs to spawn (defaults to all)

    Returns:
        Dict mapping agent IDs to their tailored prompts
    """
    session_id = f"team-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    # Determine which agents to include
    agents_to_spawn = template.agents
    if agent_subset:
        agents_to_spawn = [a for a in template.agents if a.id in agent_subset]

    # Get list of teammate IDs (excluding self)
    all_agent_ids = [a.id for a in agents_to_spawn]

    prompts = {}
    for agent in agents_to_spawn:
        teammates = [aid for aid in all_agent_ids if aid != agent.id]
        prompts[agent.id] = generate_agent_prompt(
            agent=agent,
            task_description=task_description,
            project=project,
            working_dir=working_dir,
            session_id=session_id,
            team_name=template.name,
            teammates=teammates
        )

    return prompts


# =============================================================================
# DEFAULT TEMPLATES
# =============================================================================

def get_default_templates() -> list[TeamTemplate]:
    """Get the default built-in team templates."""
    return [
        # Software Development Team (existing)
        TeamTemplate(
            id="software-dev",
            name="Software Development Team",
            description="Full-stack development team for building features. Frontend, backend, QA, security, and DevOps.",
            min_agents=3,
            max_agents=5,
            tags=["development", "coding", "features", "full-stack"],
            agents=[
                AgentRole(
                    id="frontend-dev",
                    name="Frontend Dev",
                    expertise=["React", "Next.js", "TypeScript", "CSS", "UI/UX"],
                    responsibilities=[
                        "Build UI components",
                        "Implement client-side logic",
                        "Style with Tailwind/CSS",
                        "Handle user interactions"
                    ],
                    constraints=[
                        "Do NOT touch backend code",
                        "Do NOT modify environment files"
                    ],
                    collaborates_with=["backend-dev", "qa-tester"]
                ),
                AgentRole(
                    id="backend-dev",
                    name="Backend Dev",
                    expertise=["Python", "FastAPI", "Node.js", "Databases", "API Design"],
                    responsibilities=[
                        "Design and implement APIs",
                        "Handle data persistence",
                        "Implement business logic",
                        "Data validation"
                    ],
                    constraints=[
                        "Do NOT touch frontend code",
                        "Do NOT commit secrets"
                    ],
                    collaborates_with=["frontend-dev", "devops"]
                ),
                AgentRole(
                    id="devops",
                    name="DevOps / Integration Lead",
                    expertise=["Docker", "CI/CD", "Deployment", "Infrastructure"],
                    responsibilities=[
                        "Wire components together",
                        "Register new actions",
                        "Restart services",
                        "Verify end-to-end functionality"
                    ],
                    constraints=[
                        "Do NOT modify application logic",
                        "Test locally before marking complete"
                    ],
                    collaborates_with=["backend-dev", "frontend-dev"]
                ),
                AgentRole(
                    id="qa-tester",
                    name="QA Tester",
                    expertise=["Testing", "Test Automation", "Edge Cases", "Bug Hunting"],
                    responsibilities=[
                        "Write unit and integration tests",
                        "Identify edge cases",
                        "Verify functionality",
                        "Report bugs"
                    ],
                    constraints=[
                        "Do NOT modify production source code",
                        "Only modify test files"
                    ],
                    collaborates_with=["frontend-dev", "backend-dev"]
                ),
                AgentRole(
                    id="security-reviewer",
                    name="Security Reviewer",
                    expertise=["Security", "OWASP", "Code Review", "Vulnerability Assessment"],
                    responsibilities=[
                        "Review code for vulnerabilities",
                        "Check for OWASP Top 10",
                        "Flag security issues",
                        "Recommend fixes"
                    ],
                    constraints=[
                        "READ ONLY - do not modify code",
                        "Document severity for each finding"
                    ],
                    collaborates_with=["backend-dev", "devops"]
                ),
            ]
        ),

        # Project Management Team
        TeamTemplate(
            id="project-management",
            name="Project Management Team",
            description="Team for planning, coordinating, and tracking project work. Good for complex initiatives.",
            min_agents=3,
            max_agents=5,
            tags=["planning", "coordination", "management", "strategy"],
            agents=[
                AgentRole(
                    id="project-lead",
                    name="Project Lead",
                    expertise=["Project Management", "Coordination", "Planning", "Stakeholder Communication"],
                    responsibilities=[
                        "Break down the project into phases",
                        "Define milestones and deliverables",
                        "Coordinate between team members",
                        "Track overall progress"
                    ],
                    constraints=[
                        "Do NOT write code directly",
                        "Focus on planning and coordination"
                    ],
                    collaborates_with=["tech-lead", "researcher", "documenter"]
                ),
                AgentRole(
                    id="tech-lead",
                    name="Tech Lead",
                    expertise=["Architecture", "Technical Decisions", "Code Review", "System Design"],
                    responsibilities=[
                        "Define technical approach",
                        "Make architecture decisions",
                        "Review technical feasibility",
                        "Identify technical risks"
                    ],
                    constraints=[
                        "Focus on high-level design",
                        "Defer implementation to dev teams"
                    ],
                    collaborates_with=["project-lead", "researcher"]
                ),
                AgentRole(
                    id="researcher",
                    name="Researcher",
                    expertise=["Research", "Analysis", "Competitive Analysis", "Best Practices"],
                    responsibilities=[
                        "Research existing solutions",
                        "Analyze alternatives",
                        "Gather requirements",
                        "Document findings"
                    ],
                    constraints=[
                        "Focus on research and analysis",
                        "Present options, don't make final decisions"
                    ],
                    collaborates_with=["project-lead", "tech-lead"]
                ),
                AgentRole(
                    id="documenter",
                    name="Documenter",
                    expertise=["Documentation", "Technical Writing", "Diagrams", "Knowledge Management"],
                    responsibilities=[
                        "Document decisions and rationale",
                        "Create architecture diagrams",
                        "Write user guides",
                        "Maintain project wiki"
                    ],
                    constraints=[
                        "Do NOT make decisions",
                        "Document what others decide"
                    ],
                    collaborates_with=["project-lead", "tech-lead"]
                ),
            ]
        ),

        # Research Team
        TeamTemplate(
            id="research",
            name="Research Team",
            description="Deep-dive research team for exploring topics, analyzing options, and making recommendations.",
            min_agents=3,
            max_agents=4,
            tags=["research", "analysis", "exploration", "recommendations"],
            agents=[
                AgentRole(
                    id="lead-researcher",
                    name="Lead Researcher",
                    expertise=["Research Methodology", "Synthesis", "Critical Analysis"],
                    responsibilities=[
                        "Define research questions",
                        "Coordinate research efforts",
                        "Synthesize findings",
                        "Present conclusions"
                    ],
                    constraints=[
                        "Remain objective",
                        "Present evidence-based conclusions"
                    ],
                    collaborates_with=["analyst", "domain-expert"]
                ),
                AgentRole(
                    id="analyst",
                    name="Data Analyst",
                    expertise=["Data Analysis", "Statistics", "Visualization", "Trends"],
                    responsibilities=[
                        "Analyze quantitative data",
                        "Identify patterns and trends",
                        "Create visualizations",
                        "Support conclusions with data"
                    ],
                    constraints=[
                        "Base claims on data",
                        "Acknowledge limitations"
                    ],
                    collaborates_with=["lead-researcher"]
                ),
                AgentRole(
                    id="domain-expert",
                    name="Domain Expert",
                    expertise=["Domain Knowledge", "Industry Context", "Best Practices"],
                    responsibilities=[
                        "Provide domain context",
                        "Evaluate solutions in context",
                        "Identify industry best practices",
                        "Flag domain-specific concerns"
                    ],
                    constraints=[
                        "Stay within domain expertise",
                        "Defer to analysts for data"
                    ],
                    collaborates_with=["lead-researcher", "analyst"]
                ),
            ]
        ),

        # Security Audit Team
        TeamTemplate(
            id="security-audit",
            name="Security Audit Team",
            description="Comprehensive security review team for auditing code, infrastructure, and practices.",
            min_agents=3,
            max_agents=4,
            tags=["security", "audit", "compliance", "vulnerability"],
            agents=[
                AgentRole(
                    id="security-lead",
                    name="Security Lead",
                    expertise=["Security Architecture", "Risk Assessment", "Compliance"],
                    responsibilities=[
                        "Define audit scope",
                        "Prioritize findings",
                        "Create remediation plan",
                        "Coordinate team"
                    ],
                    constraints=[
                        "READ ONLY - do not modify code",
                        "Document all findings"
                    ],
                    collaborates_with=["code-auditor", "infra-auditor"]
                ),
                AgentRole(
                    id="code-auditor",
                    name="Code Auditor",
                    expertise=["Code Review", "OWASP", "Secure Coding", "Vulnerability Detection"],
                    responsibilities=[
                        "Review application code",
                        "Check for OWASP Top 10",
                        "Identify injection points",
                        "Review auth/authz logic"
                    ],
                    constraints=[
                        "READ ONLY",
                        "Rate severity for each finding"
                    ],
                    collaborates_with=["security-lead"]
                ),
                AgentRole(
                    id="infra-auditor",
                    name="Infrastructure Auditor",
                    expertise=["Cloud Security", "Network Security", "Configuration", "Secrets Management"],
                    responsibilities=[
                        "Review infrastructure config",
                        "Check for exposed secrets",
                        "Audit access controls",
                        "Review network policies"
                    ],
                    constraints=[
                        "READ ONLY",
                        "Do NOT access production systems"
                    ],
                    collaborates_with=["security-lead"]
                ),
            ]
        ),
    ]


# =============================================================================
# INSTANCE MANAGEMENT
# =============================================================================

def create_instance(
    template_id: str,
    task_description: str,
    agent_ids: list[str] = None,
    session_id: str = None
) -> TeamInstance:
    """
    Create a new team instance record.

    Args:
        template_id: Which template is being used
        task_description: What the team is working on
        agent_ids: Which agents were spawned
        session_id: Session ID from spawner

    Returns:
        The created instance
    """
    instance = TeamInstance(
        id=f"inst-{str(uuid.uuid4())[:8]}",
        template_id=template_id,
        task_description=task_description,
        agents=agent_ids or [],
        session_id=session_id,
        status="spawning"
    )

    # TODO: Add file locking to prevent race conditions
    # For now, this is acceptable for single-user operation
    instances = load_instances()
    instances.append(instance)
    save_instances(instances)

    # Increment template use count
    increment_use_count(template_id)

    return instance


def update_instance_status(instance_id: str, status: str) -> Optional[TeamInstance]:
    """Update an instance's status."""
    instances = load_instances()

    for inst in instances:
        if inst.id == instance_id:
            inst.status = status
            if status == "completed":
                inst.completed_at = datetime.utcnow().isoformat() + "Z"
            save_instances(instances)
            return inst

    return None


def get_active_instances() -> list[TeamInstance]:
    """Get all active (non-completed) instances."""
    instances = load_instances()
    return [i for i in instances if i.status not in ["completed", "failed"]]


def get_instance(instance_id: str) -> Optional[TeamInstance]:
    """Get a specific instance by ID."""
    instances = load_instances()
    for inst in instances:
        if inst.id == instance_id:
            return inst
    return None
