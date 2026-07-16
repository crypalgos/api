import ast

FORBIDDEN_IMPORTS = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "importlib",
    "requests",
    "urllib",
    "socket",
    "builtins",
}
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "open",
    "compile",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
}


def validate_strategy_ast(code: str) -> bool:
    """Validate strategy python code using AST parser to prevent security escalations."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Syntax validation failed: {e}")

    for node in ast.walk(tree):
        # Prevent dangerous imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    raise ValueError(f"Import of '{alias.name}' is strictly forbidden.")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                raise ValueError(f"Import from '{node.module}' is strictly forbidden.")

        # Prevent dangerous built-in dynamic execution functions
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                raise ValueError(
                    f"Calling built-in function '{node.func.id}()' is strictly forbidden."
                )

        # Prevent dunder sandbox escape techniques
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                raise ValueError(
                    f"Access to private attribute '{node.attr}' is strictly forbidden."
                )

    return True
