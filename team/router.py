"""
Smart Router - Morphs 1 prompt into 5 tailored prompts

Takes a high-level user prompt like "Build a waitlist feature"
and creates role-specific versions for each agent.
"""

from pathlib import Path
from .templates import format_agent_prompt

# Default agents in the software-dev team
SOFTWARE_DEV_AGENTS = [
    "frontend-dev",
    "backend-dev",
    "devops",
    "qa-tester",
    "security-reviewer",
]


def route_prompt(
    prompt: str,
    project: str = "workspace",
    agents: list = None,
    working_dir: str = None
) -> dict:
    """
    Take one user prompt and morph it into agent-specific prompts.

    Args:
        prompt: The user's high-level task description
        project: Project name for context
        agents: List of agent names to route to (default: all software-dev agents)
        working_dir: Working directory path

    Returns:
        dict mapping agent names to their tailored prompts

    Example:
        Input: "Build a waitlist feature"
        Output: {
            "frontend-dev": "# Task for Frontend Dev\n\nYou are the Frontend Dev...",
            "backend-dev": "# Task for Backend Dev\n\nYou are the Backend Dev...",
            ...
        }
    """
    if agents is None:
        agents = SOFTWARE_DEV_AGENTS

    if working_dir is None:
        working_dir = str(Path("C:/Users/<user>/workspace"))

    routed_prompts = {}

    for agent in agents:
        tailored_prompt = format_agent_prompt(
            agent_name=agent,
            prompt=prompt,
            project=project,
            working_dir=working_dir
        )
        routed_prompts[agent] = tailored_prompt

    return routed_prompts


def get_agents_for_task(prompt: str) -> list:
    """
    Analyze prompt to determine which agents should be involved.

    For now, returns all agents. Future: use LLM or rules to select.

    Args:
        prompt: The user's task description

    Returns:
        List of agent names that should work on this task
    """
    # TODO: Implement smart agent selection based on prompt content
    # For now, all agents participate
    return SOFTWARE_DEV_AGENTS


def analyze_prompt(prompt: str) -> dict:
    """
    Analyze the prompt to extract key information.

    Returns:
        dict with:
        - keywords: list of detected keywords
        - agents_needed: suggested agents
        - complexity: low/medium/high
    """
    prompt_lower = prompt.lower()

    # Simple keyword detection
    frontend_keywords = ["ui", "component", "form", "button", "style", "css", "react", "page"]
    backend_keywords = ["api", "endpoint", "database", "server", "route", "auth"]
    devops_keywords = ["deploy", "docker", "ci", "cd", "build", "config"]
    qa_keywords = ["test", "bug", "edge case", "quality", "coverage"]
    security_keywords = ["security", "auth", "password", "token", "vulnerability"]

    agents_needed = []

    if any(kw in prompt_lower for kw in frontend_keywords):
        agents_needed.append("frontend-dev")
    if any(kw in prompt_lower for kw in backend_keywords):
        agents_needed.append("backend-dev")
    if any(kw in prompt_lower for kw in devops_keywords):
        agents_needed.append("devops")
    if any(kw in prompt_lower for kw in qa_keywords):
        agents_needed.append("qa-tester")
    if any(kw in prompt_lower for kw in security_keywords):
        agents_needed.append("security-reviewer")

    # Default: all agents if none detected
    if not agents_needed:
        agents_needed = SOFTWARE_DEV_AGENTS

    return {
        "agents_needed": agents_needed,
        "complexity": "medium",  # TODO: implement complexity detection
    }
