"""
Flight Path - Project Scanner

Scans a project directory and builds a high-level graph of:
- Directories as nodes (modules/components)
- Import relationships as edges
- File types and their purposes

The goal is a bird's-eye view to prevent getting lost in tangents.
"""
import os
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict


# Patterns to detect imports in different languages
IMPORT_PATTERNS = {
    "python": [
        re.compile(r'^from\s+(\S+)\s+import', re.MULTILINE),
        re.compile(r'^import\s+(\S+)', re.MULTILINE),
    ],
    "javascript": [
        re.compile(r'from\s+[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        re.compile(r'require\s*\(\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
    ],
    "typescript": [
        re.compile(r'from\s+[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        re.compile(r'require\s*\(\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
    ],
}

# File extensions to language mapping
EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

# Directories to always skip
SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__",
    ".next", "dist", "build", ".cache", "coverage",
    ".stversions", ".stfolder", ".idea", ".vscode"
}

# Files to always skip
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    ".DS_Store", "Thumbs.db"
}


@dataclass
class FileNode:
    """Represents a single file in the graph."""
    path: str
    name: str
    extension: str
    language: Optional[str] = None
    imports: list = field(default_factory=list)
    size_bytes: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class DirectoryNode:
    """Represents a directory (module/component) in the graph."""
    path: str
    name: str
    purpose: str = ""  # Inferred or configured purpose
    file_count: int = 0
    languages: list = field(default_factory=list)
    children: list = field(default_factory=list)  # Sub-directories

    def to_dict(self):
        return asdict(self)


@dataclass
class Edge:
    """Represents a connection between nodes."""
    source: str  # Path of source node
    target: str  # Path of target node
    edge_type: str  # "import", "sibling", "parent-child"
    weight: int = 1  # Number of connections

    def to_dict(self):
        return asdict(self)


@dataclass
class ProjectGraph:
    """The complete project graph."""
    root: str
    name: str
    directories: list = field(default_factory=list)
    files: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "root": self.root,
            "name": self.name,
            "directories": [d.to_dict() for d in self.directories],
            "files": [f.to_dict() for f in self.files],
            "edges": [e.to_dict() for e in self.edges],
            "summary": self.summary,
        }


def infer_purpose(dir_name: str, files: list[str]) -> str:
    """Infer the purpose of a directory based on name and contents."""
    name_lower = dir_name.lower()

    # Common patterns
    purpose_map = {
        "api": "API endpoints and handlers",
        "components": "UI components",
        "pages": "Page routes",
        "app": "Application routes (App Router)",
        "lib": "Utility libraries",
        "utils": "Helper utilities",
        "hooks": "React hooks",
        "services": "Business logic services",
        "models": "Data models",
        "types": "Type definitions",
        "styles": "Stylesheets",
        "public": "Static assets",
        "tests": "Test files",
        "__tests__": "Test files",
        "test": "Test files",
        "actions": "Actions/Commands",
        "team": "Team/Agent coordination",
        "ui": "User interface",
        "data": "Data storage",
        "config": "Configuration",
        "migrations": "Database migrations",
        "middleware": "Middleware functions",
    }

    if name_lower in purpose_map:
        return purpose_map[name_lower]

    # Check file patterns
    extensions = {Path(f).suffix for f in files}
    if ".test.js" in str(files) or ".spec.js" in str(files):
        return "Test files"
    if ".css" in extensions or ".scss" in extensions:
        return "Stylesheets"
    if ".md" in extensions:
        return "Documentation"

    return ""


def extract_imports(file_path: Path, language: str) -> list[str]:
    """Extract import statements from a file."""
    if language not in IMPORT_PATTERNS:
        return []

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    imports = []
    for pattern in IMPORT_PATTERNS[language]:
        matches = pattern.findall(content)
        imports.extend(matches)

    return imports


def resolve_import(import_path: str, source_file: Path, project_root: Path) -> Optional[str]:
    """
    Resolve an import path to an actual file/directory within the project.
    Returns None if it's an external package.
    """
    # Skip external packages (no . or @ prefix for relative imports)
    if not import_path.startswith(".") and not import_path.startswith("@/"):
        return None

    # Handle @/ alias (common in Next.js/TS projects)
    if import_path.startswith("@/"):
        resolved = project_root / import_path[2:]
    else:
        # Relative import
        source_dir = source_file.parent
        resolved = (source_dir / import_path).resolve()

    # Try to find the actual file
    for ext in ["", ".ts", ".tsx", ".js", ".jsx", ".py", "/index.ts", "/index.tsx", "/index.js"]:
        check_path = Path(str(resolved) + ext)
        if check_path.exists() and check_path.is_file():
            try:
                return str(check_path.relative_to(project_root))
            except ValueError:
                return None

    # Check if it's a directory
    if resolved.is_dir():
        try:
            return str(resolved.relative_to(project_root))
        except ValueError:
            return None

    return None


def scan_project(project_path: str, max_depth: int = 4) -> ProjectGraph:
    """
    Scan a project and build the dependency graph.

    Args:
        project_path: Root path of the project
        max_depth: Maximum directory depth to scan (prevents rabbit holes)

    Returns:
        ProjectGraph with all nodes and edges
    """
    root = Path(project_path).resolve()
    graph = ProjectGraph(
        root=str(root),
        name=root.name,
    )

    file_nodes: dict[str, FileNode] = {}
    dir_nodes: dict[str, DirectoryNode] = {}

    # Walk the directory tree
    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)
        relative_dir = current_dir.relative_to(root)
        depth = len(relative_dir.parts)

        # Skip if too deep
        if depth > max_depth:
            dirnames.clear()  # Don't descend further
            continue

        # Skip excluded directories
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        # Create directory node
        if str(relative_dir) != ".":
            languages_in_dir = set()
            for f in filenames:
                ext = Path(f).suffix
                if ext in EXT_TO_LANG:
                    languages_in_dir.add(EXT_TO_LANG[ext])

            dir_node = DirectoryNode(
                path=str(relative_dir),
                name=relative_dir.name,
                purpose=infer_purpose(relative_dir.name, filenames),
                file_count=len([f for f in filenames if f not in SKIP_FILES]),
                languages=list(languages_in_dir),
                children=[str(relative_dir / d) for d in dirnames],
            )
            dir_nodes[str(relative_dir)] = dir_node

        # Process files
        for filename in filenames:
            if filename in SKIP_FILES:
                continue

            file_path = current_dir / filename
            relative_path = file_path.relative_to(root)
            ext = file_path.suffix
            language = EXT_TO_LANG.get(ext)

            # Get file size
            try:
                size = file_path.stat().st_size
            except Exception:
                size = 0

            # Extract imports if it's a code file
            imports = []
            if language:
                raw_imports = extract_imports(file_path, language)
                for imp in raw_imports:
                    resolved = resolve_import(imp, file_path, root)
                    if resolved:
                        imports.append(resolved)

            file_node = FileNode(
                path=str(relative_path),
                name=filename,
                extension=ext,
                language=language,
                imports=imports,
                size_bytes=size,
            )
            file_nodes[str(relative_path)] = file_node

    # Build edges from imports
    edge_map: dict[tuple[str, str], int] = {}
    for file_path, file_node in file_nodes.items():
        source_dir = str(Path(file_path).parent)
        if source_dir == ".":
            source_dir = ""

        for imp in file_node.imports:
            target_dir = str(Path(imp).parent)
            if target_dir == ".":
                target_dir = ""

            # Create edge between directories (high-level view)
            if source_dir and target_dir and source_dir != target_dir:
                key = (source_dir, target_dir)
                edge_map[key] = edge_map.get(key, 0) + 1

    # Convert edge map to Edge objects
    for (source, target), weight in edge_map.items():
        graph.edges.append(Edge(
            source=source,
            target=target,
            edge_type="import",
            weight=weight,
        ))

    # Add parent-child edges for directory structure
    for dir_path, dir_node in dir_nodes.items():
        parent = str(Path(dir_path).parent)
        if parent != "." and parent in dir_nodes:
            graph.edges.append(Edge(
                source=parent,
                target=dir_path,
                edge_type="parent-child",
                weight=1,
            ))

    # Populate graph
    graph.directories = list(dir_nodes.values())
    graph.files = list(file_nodes.values())

    # Build summary
    lang_counts = {}
    total_size = 0
    for f in graph.files:
        if f.language:
            lang_counts[f.language] = lang_counts.get(f.language, 0) + 1
        total_size += f.size_bytes

    graph.summary = {
        "total_directories": len(graph.directories),
        "total_files": len(graph.files),
        "total_edges": len(graph.edges),
        "languages": lang_counts,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
    }

    return graph


def get_directory_graph(project_path: str, max_depth: int = 3) -> dict:
    """
    Get a simplified directory-level graph.

    This is the high-level "flight path" view - just directories and their
    connections, without individual files.
    """
    full_graph = scan_project(project_path, max_depth)

    # Filter to just directory-level data
    return {
        "root": full_graph.root,
        "name": full_graph.name,
        "nodes": [
            {
                "id": d.path,
                "label": d.name,
                "purpose": d.purpose,
                "file_count": d.file_count,
                "languages": d.languages,
            }
            for d in full_graph.directories
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "type": e.edge_type,
                "weight": e.weight,
            }
            for e in full_graph.edges
        ],
        "summary": full_graph.summary,
    }
