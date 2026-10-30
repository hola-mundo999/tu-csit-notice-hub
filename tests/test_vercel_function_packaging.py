import ast
import fnmatch
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _local_module_path(module_name):
    module_path = ROOT.joinpath(*module_name.split("."))
    module_file = module_path.with_suffix(".py")
    package_file = module_path / "__init__.py"
    if module_file.is_file():
        return module_file
    if package_file.is_file():
        return package_file
    return None


def _local_dependencies(entrypoint):
    pending = [entrypoint]
    dependencies = set()
    visited = set()

    while pending:
        source = pending.pop()
        if source in visited:
            continue
        visited.add(source)
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.append(node.module)

            for module_name in modules:
                module_path = _local_module_path(module_name)
                if module_path and module_path != entrypoint and module_path not in dependencies:
                    dependencies.add(module_path)
                    pending.append(module_path)

    return dependencies


def _matches_include(pattern, relative_path):
    if "{" in pattern and "}" in pattern:
        prefix, alternatives = pattern.split("{", 1)
        alternatives, suffix = alternatives.split("}", 1)
        patterns = [f"{prefix}{alternative}{suffix}" for alternative in alternatives.split(",")]
    else:
        patterns = [pattern]
    return any(fnmatch.fnmatch(relative_path, candidate) for candidate in patterns)


def test_every_api_entrypoint_includes_its_transitive_local_modules():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    function_configs = config.get("functions", {})
    api_entrypoints = sorted((ROOT / "api").glob("*.py"))
    ignored_patterns = [
        line.strip()
        for line in (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert api_entrypoints
    for entrypoint in api_entrypoints:
        relative_entrypoint = entrypoint.relative_to(ROOT).as_posix()
        assert relative_entrypoint in function_configs
        function_config = function_configs[relative_entrypoint]
        include_files = function_config.get("includeFiles")
        include_patterns = [include_files] if isinstance(include_files, str) else include_files
        assert include_patterns, f"{relative_entrypoint} must configure its local modules"

        for dependency in _local_dependencies(entrypoint):
            relative_dependency = dependency.relative_to(ROOT).as_posix()
            assert any(
                _matches_include(pattern, relative_dependency)
                for pattern in include_patterns
            ), f"{relative_dependency} is not included for {relative_entrypoint}"
            assert not any(
                _matches_include(pattern, relative_dependency)
                for pattern in ignored_patterns
            ), f"{relative_dependency} is excluded by .vercelignore"
